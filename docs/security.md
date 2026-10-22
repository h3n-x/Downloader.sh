# Seguridad

Modelo de amenazas, controles implementados (con su ubicación y test) y riesgos residuales.
La aplicación acepta URLs arbitrarias y ejecuta un parser de terceros sobre contenido
hostil: ambas cosas se tratan como superficie de ataque principal.

## Activos y actores

- **Activos**: red interna/metadatos cloud del host, CPU/RAM/disco/ancho de banda, disponibilidad,
  privacidad de los usuarios, reputación (abuso para piratería).
- **Actores**: usuario anónimo malicioso, bots/scrapers, contenido malicioso servido por una
  plataforma o un CDN comprometido, dependencias comprometidas.

## SSRF (análisis específico)

yt-dlp hace sus propias peticiones (páginas, APIs, redirects, manifiestos HLS/DASH, CDNs),
así que validar la URL de entrada **no es suficiente**. Dos barreras:

1. **Entrada** (`security/url.py`, `tests/unit/test_url.py`): solo `http/https`, sin
   `userinfo`, puertos 80/443, IDNA, rechazo de IP literales no públicas, `localhost`,
   `.local/.internal/.lan/.home.arpa…`, nombres de una etiqueta y TLD numéricos
   (`0x7f.1`, `2130706433`, `0177.0.0.1`). Después, **allowlist de dominios** por proveedor.
2. **Salida** (`infra/egress_proxy.py`, `tests/integration/test_egress_proxy.py`): proxy
   HTTP/CONNECT en `127.0.0.1` obligatorio para el worker (opción `proxy` de yt-dlp):
   - token aleatorio por trabajo, revocado al terminar (cierra conexiones abiertas);
   - **una sola resolución DNS**; si *cualquier* respuesta no es pública se rechaza;
   - conexión a la IP ya validada → sin DNS rebinding; TLS extremo a extremo (CONNECT);
   - puertos 80/443; cabeceras hop-by-hop y credenciales eliminadas en HTTP plano;
   - presupuesto de bytes por trabajo (corta la conexión al excederlo).
   El test `test_ytdlp_networking_uses_proxy_with_credentials` verifica con el stack HTTP
   real de yt-dlp que la resolución ocurre en el proxy y no en el cliente, y
   `test_worker_traffic_is_forced_through_proxy` lo verifica con un worker real.

Política de IP (`security/netpolicy.py`): `ipaddress.is_global` **no basta** en CPython 3.13
(`64:ff9b::7f00:1` NAT64→loopback y `ff02::1` multicast devuelven `True`). Se desempaquetan
IPv4-mapped y NAT64, se rechazan 6to4/Teredo/NAT64 local (deprecados) y multicast, y
`192.0.0.0/24`. Propiedades verificadas con Hypothesis (incluido un contraejemplo real
encontrado por Hypothesis: `2002:100::`).

Extractor *Generic* desactivado: amplía la superficie a "cualquier web". Los enlaces cortos
que solo él entiende (`fb.watch`, `on.soundcloud.com`, `v.redd.it`) se resuelven siguiendo
redirects **a través del proxy** y revalidando el destino contra la allowlist.

## Ejecución de procesos e inyección

- Sin shell en ningún punto; `subprocess.run`/`os.system` prohibidos por lint (`TID251`).
- Worker: `create_subprocess_exec` con argv fijo (`python -I -m downloader.worker`),
  entorno mínimo (sin secretos del API), `start_new_session` (kill del grupo completo),
  `PR_SET_PDEATHSIG`.
- yt-dlp vía API Python, sin opciones del usuario. Los ids de formato se validan
  (`^[A-Za-z0-9._=-]{1,64}$`) y se comprueban contra los formatos reales antes de construir
  el selector: no hay inyección en la sintaxis de formatos.
- FFmpeg nunca descarga: `external_downloader=native`, directos rechazados, solo protocolos
  `http(s)/m3u8/http_dash_segments`, y `-protocol_whitelist file,pipe` en **todas** las
  entradas de los 17 postprocesadores FFmpeg (regresión: la clave genérica `ffmpeg_i` era
  ignorada en silencio por yt-dlp).
- Deno (EJS de YouTube) se ejecuta por yt-dlp sin flags `--allow-*` (sin red ni FS) y con
  `--no-remote`.

## Recursos y abuso

| Riesgo | Control | Dónde |
|---|---|---|
| Ficheros enormes | límite por opción (estimación), `max_filesize`, presupuesto de bytes del proxy, `RLIMIT_FSIZE` | `quality.py`, `ytdlp.py`, `egress_proxy.py`, `worker/__main__.py` |
| Duración | `max_duration` antes de descargar | `ytdlp.py` |
| CPU | `RLIMIT_CPU`, sin transcodificación de vídeo, `cpus` del contenedor | worker, compose |
| Memoria | límite del cgroup (`mem_limit`); `RLIMIT_AS` no se usa (rompe V8/Deno) | compose |
| Procesos | `pids_limit`, concurrencia global y por cliente, cola acotada (503 + `Retry-After`) | compose, `jobs.py` |
| Disco | cuota global, TTL, reaper, sweep de huérfanos al arrancar, tmpfs | `jobs.py`, `storage.py` |
| Cuerpos grandes | 16 KiB (declarado y *chunked*) → 413 | `api/middleware.py` |
| Conexiones | `limit_concurrency`, `timeout_keep_alive`, `nofile` | `__main__.py`, compose |
| Bots | token bucket por HMAC(IP o /64 en IPv6); inspección y descarga separadas | `api/ratelimit.py` |
| Slowloris | **proxy inverso** (uvicorn no tiene timeout de cabeceras) | despliegue |

## Web

- CSP estricta sin `unsafe-inline`; los bloques inline del runtime de islas de Astro se
  permiten por **hash** generado en el build (`frontend/scripts/csp-hashes.mjs`).
- `frame-ancestors 'none'`, `nosniff`, `Referrer-Policy: no-referrer`, COOP/CORP,
  `Permissions-Policy` restrictiva, HSTS opcional.
- XSS: Svelte escapa por defecto; test con título `<img onerror>` (unit) y `<b>` (E2E).
- CSRF: sin cookies ni sesión; la API exige `application/json` (sin *simple requests*).
- CORS: no se habilita (mismo origen).
- Redirecciones abiertas: no hay redirects del servidor; el cliente solo navega a su propio
  endpoint de descarga.
- Path traversal: nombres en disco fijos, `mkdtemp` 0700, borrado que rechaza symlinks y
  rutas fuera de la raíz; tests de traversal codificado en estáticos.
- Fugas de información: envelope `{code, message, request_id}`, sin trazas; logs JSON sin
  URLs/IPs/ids de trabajo; `x-request-id` validado (sin inyección en logs).

## Privacidad

Se persiste lo mínimo, y solo en memoria/tmpfs: caché de metadatos (5 min), estado de
trabajos (≤ 25 min tras terminar), archivos (TTL 15 min). Logs: ruta como plantilla,
huella SHA-256 truncada de la URL, código de error. Nada de analítica de terceros.

## Supply chain

`uv.lock` y `pnpm-lock.yaml` con instalación `--frozen`; pnpm bloquea scripts de
instalación por defecto; Actions fijadas por SHA; `pip-audit` y `pnpm audit` en CI;
Trivy sobre la imagen (vulnerabilidades CRITICAL/HIGH con fix y secretos; `trivy-secret.yaml`
solo exceptúa los extractores de yt-dlp, que traen claves públicas de sus APIs) y SBOM
CycloneDX; la imagen final no lleva pip (la app corre desde `/app/.venv`); Dependabot
(yt-dlp agrupado).

## Riesgos residuales

1. Bypass del proxy por código nativo que ignore la opción `proxy` (no observado). Mitigación
   recomendada en producción: red del contenedor sin salida salvo el proxy (P1).
2. Vulnerabilidades en FFmpeg/demuxers con medios maliciosos: mitigado por no-root,
   rootfs RO, rlimits, cgroups y `no-new-privileges`; seccomp/gVisor sería el siguiente paso.
3. Rate limiting en memoria: insuficiente con varias réplicas o ataques distribuidos (P1).
4. Las plataformas pueden bloquear IPs de datacenter: es un riesgo operativo, no se elude.
