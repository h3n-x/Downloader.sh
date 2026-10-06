# ADR 0002 — Extracción: yt-dlp detrás de un puerto, en subproceso, tras un proxy de salida

- Estado: aceptado (2026-10-06)

## Decisión

1. El dominio define `MediaExtractor` (Protocol) y modelos propios (`MediaInfo`, `MediaFormat`…).
   `YtDlpExtractor` es el único módulo que importa `yt_dlp`.
2. yt-dlp se ejecuta en un **subproceso por trabajo** (`python -m downloader.worker`), con
   `setrlimit` (tamaño de fichero, CPU, descriptores, core=0), sesión propia (kill del grupo),
   `HOME` aislado y protocolo JSONL por stdin/stdout. Coste medido: ~0,5 s de arranque, ~50 MB RSS.
3. Todo el tráfico del worker pasa por un **proxy de salida local** con token por trabajo que
   valida destino (IP global, puertos 80/443), fija la IP resuelta y contabiliza bytes.
4. Opciones fijas de yt-dlp: `allowed_extractors` (allowlist), `external_downloader={'default':'native'}`,
   `noplaylist`, sin cookies, sin config, sin plugins, `js_runtimes={'deno':{}}`. Directos rechazados.
5. Sin generadores de PO tokens ni impersonación TLS (non-goal: no eludimos medidas anti-bot).

## Motivo

- Aislar un parser enorme de terceros que procesa HTML/JSON hostil: un crash o fuga de memoria
  mata un worker, no el API.
- yt-dlp hace sus propias peticiones (redirects, manifiestos, CDNs): solo un control en la capa
  de red cubre SSRF de forma completa.
- Sustituir/complementar el motor (p. ej. cobalt, gallery-dl) solo requiere otro adaptador.

## Evolución

El protocolo JSONL permite mover los workers a contenedores separados sin red salvo el proxy,
o detrás de una cola, sin cambiar dominio ni API.

## Nota de implementación (2026-10-06)

La restricción `-protocol_whitelist file,pipe` se aplica con claves por postprocesador
(`"<pp_key>+ffmpeg_i"`): yt-dlp ignora en silencio una clave genérica `ffmpeg_i`
(verificado; test de regresión en `tests/unit/test_ytdlp_adapter.py`).
