# Configuración

Variables de entorno con prefijo `DL_` (Pydantic Settings, `backend/src/downloader/config.py`).
Plantilla: [`.env.example`](../.env.example).

| Variable | Defecto | Descripción |
|---|---|---|
| `DL_ENVIRONMENT` | `production` | `development` habilita `/api/docs` |
| `DL_HOST` / `DL_PORT` | `0.0.0.0` / `8000` | Escucha de uvicorn |
| `DL_FORWARDED_ALLOW_IPS` | `127.0.0.1` | Proxies de confianza para `X-Forwarded-For` |
| `DL_LIMIT_CONCURRENCY` | `2048` | Conexiones simultáneas máximas (incluye SSE) |
| `DL_DATA_DIR` | `/tmp/downloader` | Raíz de trabajos (`jobs/`) y scratch |
| `DL_STATIC_DIR` | — | Build del frontend a servir (la imagen lo fija) |
| `DL_PROVIDERS` | todos | Lista CSV de proveedores habilitados |
| `DL_MAX_FILESIZE` | 2 GiB | Tamaño máximo por archivo |
| `DL_MAX_DURATION` | 10800 s | Duración máxima |
| `DL_INSPECT_TIMEOUT` | 60 s | Tiempo máximo de inspección |
| `DL_DOWNLOAD_TIMEOUT` | 1800 s | Tiempo máximo de descarga |
| `DL_WORKER_CPU_SECONDS` | 900 | `RLIMIT_CPU` del worker |
| `DL_MAX_CONCURRENT_DOWNLOADS` | 4 | Descargas en paralelo |
| `DL_MAX_QUEUED_DOWNLOADS` | 16 | Cola adicional antes de responder 503 |
| `DL_MAX_CONCURRENT_INSPECTS` | 8 | Inspecciones en paralelo (espera ≤ 2×) |
| `DL_MAX_ACTIVE_DOWNLOADS_PER_CLIENT` | 2 | Trabajos activos por cliente |
| `DL_DISK_QUOTA` | 20 GiB | Uso total de disco antes de rechazar trabajos |
| `DL_INSPECT_PER_MINUTE` | 20 | Token bucket de inspección por cliente |
| `DL_DOWNLOADS_PER_MINUTE` | 6 | Token bucket de descargas por cliente |
| `DL_DOWNLOAD_TTL` | 900 s | Vida de un archivo listo |
| `DL_INSPECT_CACHE_TTL` | 300 s | Caché de metadatos (0 = desactivada) |
| `DL_CLIENT_KEY_SECRET` | aleatorio | HMAC para claves de rate limit |
| `DL_HSTS` | `false` | Enviar `Strict-Transport-Security` |
| `DL_METRICS_ENABLED` / `DL_METRICS_TOKEN` | `true` / — | `/metrics` y su token Bearer |
| `DL_LOG_LEVEL` | `INFO` | Nivel de log |
| `DL_LOG_WORKER_STDERR` | `false` | Registrar la cola de stderr del worker en fallos internos (puede contener URLs) |

Frontend (build): `SITE_URL` (canónicas, sitemap), `API_URL` (proxy de `pnpm dev`).
