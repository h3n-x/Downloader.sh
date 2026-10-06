# Arquitectura

Estado: implementado (MVP). Decisiones en [`adr/`](adr/). Investigación en [`plan.md`](plan.md).

## Componentes

| Capa | Módulo | Responsabilidad |
|---|---|---|
| Presentación | `frontend/` | Astro estático (SEO, páginas legales sin JS) + isla Svelte `Downloader` |
| API | `backend/src/downloader/api/` | Rutas, contratos Pydantic, envelope de errores, rate limit, CSP, límites de cuerpo, request ids, métricas |
| Aplicación | `app/inspect.py`, `app/jobs.py` | Casos de uso: inspección (caché TTL + single-flight + backpressure) y trabajos (cola, límites, TTL, SSE) |
| Dominio | `domain/` | Modelos (`MediaInfo`, `MediaFormat`, `QualityOption`), taxonomía de errores, proveedores (datos), reglas de calidad (puras) |
| Seguridad | `security/` | Validación/normalización de URL, política de IP, nombres de fichero |
| Extracción | `extraction/` | Puerto `MediaExtractor` + adaptador yt-dlp + clasificador de errores |
| Worker | `worker/` | Proceso aislado: rlimits, protocolo JSONL, ejecución del adaptador |
| Infraestructura | `infra/` | Proxy de salida, lanzador de workers, almacenamiento efímero |

Regla de dependencias: `api → app → domain`; `infra` y `extraction` implementan puertos.
Solo `extraction/ytdlp.py` importa `yt_dlp`.

## Flujo: de URL a archivo

```text
1. POST /api/v1/inspect {url}
   validate_url ─ esquema/userinfo/puerto/IDNA/IP literal/nombres reservados
   ProviderRegistry.detect(host) ─ allowlist de dominios  → 422 UNSUPPORTED_SITE
   caché (sha256 URL, 5 min) | single-flight | semáforo (8) → 503 SERVER_BUSY
   WorkerRunner.inspect ─ subproceso + lease del proxy (64 MiB)
   build_options(formats) ─ clases por lado corto, emparejado sin transcodificar
2. POST /api/v1/downloads {url, option_id}  → 202 + Location
   límites por cliente (HMAC IP/64), cola global, cuota de disco
   JobManager → subproceso download (lease = 1,25 × tamaño máx + 64 MiB)
     yt-dlp re-extrae (URLs frescas), resolve_option(option_id) sobre formatos frescos,
     descarga nativa (HTTP/HLS/DASH) por el proxy → FFmpeg merge/extract (local)
3. GET /api/v1/downloads/{id}/events  (SSE: snapshot completo en cada cambio)
4. GET /api/v1/downloads/{id}/file    (Range, Content-Disposition saneado)
5. TTL (15 min) → expired → borrado; reaper cada 30 s + sweep de huérfanos al arrancar
```

## Ciclo de vida

```text
queued → preparing → downloading → processing → ready → expired
   └──────────┴────────────┴─────────────┴──→ failed(code) | cancelled
```

Los snapshots se versionan; SSE envía el estado completo (idempotente ante reconexiones)
y el cliente cae a polling si el stream se corta.

## Reglas de calidad (`domain/quality.py`)

- Clase de resolución por **lado corto** (vertical 1080×1920 = 1080p); escalera
  2160/1440/1080/720/480/360/240/144 con tolerancia del 10 %.
- Dentro de una clase: códec más compatible (H.264 > AV1/VP9 > HEVC), luego mayor bitrate.
- Vídeo sin audio se empareja con audio de la misma familia de contenedor
  (mp4↔m4a → MP4; webm↔webm → WebM; resto → MKV). Nunca se transcodifica vídeo.
- Audio: mejor pista solo-audio (preferencia m4a) o extracción con copia del códec.
- Ids de opción deterministas (`v1080`, `audio`, `f:<format_id>`): el worker los recalcula
  sobre formatos frescos; si ya no existen → `FORMAT_UNAVAILABLE`.
- Las opciones que superan límites se muestran deshabilitadas con su motivo.

## Protocolo del worker

`stdin`: una `WorkerRequest` (inspect | download). `stdout`: eventos `progress`, `info`,
`done`, `error` (JSON por línea, validados con Pydantic en el padre). El fd 1 se redirige a
stderr dentro del worker para que nada pueda corromper el canal. Precedencia de clasificación
de fallos: denegación del proxy > presupuesto de bytes > señal del kernel > evento del worker.

## Por qué no hay base de datos, Redis ni cola

No hay nada que deba sobrevivir a un reinicio: los archivos son efímeros y los trabajos
duran minutos. Un único proceso con estado en memoria es correcto para un nodo.

## Evolución (cuando haya demanda medida)

```text
1 nodo (actual)                       → N nodos
JobManager en memoria                 → JobStore en Redis/Postgres (interfaz ya aislada)
WorkerRunner (subproceso local)       → cola + workers en contenedores sin red salvo proxy
                                         (mismo protocolo JSONL)
Disco local efímero                   → almacenamiento de objetos con URLs firmadas cortas
Rate limit en memoria                 → contador compartido (Redis) o en el borde
Frontend servido por FastAPI          → CDN (es estático)
```
