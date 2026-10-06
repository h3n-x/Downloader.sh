# Despliegue

## Dónde (y dónde no)

| Opción | Encaje | Motivo |
|---|---|---|
| **VPS / host de contenedores (recomendado)** | Alto | Conexiones largas, FFmpeg, disco temporal y ancho de banda predecibles; coste por TB bajo |
| PaaS de contenedores (Fly, Railway, Render…) | Medio | Válido si permite tmpfs/disco efímero suficiente y no cobra el egress caro |
| Serverless (Lambda, Vercel/Netlify functions) | **Bajo** | Timeouts, sin procesos largos ni FFmpeg cómodo, egress caro, sin estado de trabajos |
| Frontend en CDN + API en VPS | Alto (más adelante) | El frontend es estático; requiere ajustar CSP/`connect-src` y CORS |

Factor de coste dominante: **ancho de banda** (cada descarga entra y sale del servidor).

## Un nodo con Docker Compose

```bash
cp .env.example .env
python -c "import secrets; print('DL_CLIENT_KEY_SECRET=' + secrets.token_hex(32))" >> .env
docker compose up -d --build
curl -fsS http://127.0.0.1:8000/api/v1/ready
```

`compose.yaml` ya aplica: rootfs de solo lectura, `/data` en tmpfs, `cap_drop: ALL`,
`no-new-privileges`, límites de PIDs/memoria/CPU/descriptores y rotación de logs.
Dimensiona el tmpfs ≥ `DL_DISK_QUOTA` y `mem_limit` contando el tmpfs (usa RAM).

## Proxy inverso (TLS, compresión, slowloris)

uvicorn no tiene timeout de lectura de cabeceras: expón siempre la app detrás de un proxy.
Ejemplo con Caddy:

```caddyfile
downloader.example {
	encode zstd gzip
	reverse_proxy 127.0.0.1:8000 {
		flush_interval -1        # SSE sin buffering
	}
	request_body {
		max_size 16KB
	}
}
```

Y en `.env`: `DL_FORWARDED_ALLOW_IPS=127.0.0.1` (IP del proxy) y `DL_HSTS=true`.
**Importante:** si `DL_FORWARDED_ALLOW_IPS` no coincide con tu proxy, todos los clientes
compartirán la IP del proxy y el rate limiting por cliente dejará de tener sentido.

## Red de salida (recomendado)

El proxy de salida interno es la barrera SSRF de la aplicación. Como defensa en profundidad,
bloquea a nivel de host el acceso del contenedor a rangos privados y al endpoint de
metadatos (p. ej. reglas `DOCKER-USER` de iptables/nftables para 10/8, 172.16/12,
192.168/16, 169.254/16, 100.64/10, fc00::/7).

## Observabilidad

- Logs JSON en stdout (`request_id`, ruta como plantilla, estado, ms, códigos de error).
- `/metrics` (Prometheus) protegido con `DL_METRICS_TOKEN`: peticiones, latencia, resultados
  de inspección/descarga por proveedor, bytes, denegaciones del proxy, trabajos por fase,
  rechazos por rate limit.
- `/api/v1/health` (liveness) y `/api/v1/ready` (ffmpeg, deno, proxy, espacio para un
  trabajo de tamaño máximo).
- Alertas sugeridas: tasa de `PLATFORM_BLOCKED`/`EXTRACTOR_FAILED` por proveedor (señal de
  actualizar yt-dlp o de bloqueo de IP), `dl_egress_denied` en aumento, disco > 80 %.

## Actualizar yt-dlp

Las plataformas cambian a menudo; yt-dlp publica correcciones con frecuencia. Flujo:
Dependabot (grupo `extraction`) → CI → workflow `live` manual → despliegue. Vigila el
anuncio de requisitos de runtime JS (Deno) en las notas de versión.

## Escalado

Ver "Evolución" en [architecture.md](architecture.md). Antes de añadir réplicas: mover
`JobManager` a un almacén compartido, rate limiting compartido y afinidad (o almacenamiento
de objetos) para servir el archivo desde cualquier réplica.
