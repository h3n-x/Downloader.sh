# ADR 0003 — Ciclo de vida: descarga en servidor efímera + progreso por SSE

- Estado: aceptado (2026-10-06)

## Opciones evaluadas

| Estrategia | Pros | Contras |
|---|---|---|
| A. URL directa al CDN | Cero ancho de banda propio | URLs ligadas a IP/cabeceras del servidor (fallan en el cliente); no hay merge vídeo+audio; expone la IP del usuario |
| B. Proxy en streaming | Sin disco | No permite merge con MP4 estándar ni Content-Length/Range |
| C. Descarga temporal + entrega | Funciona siempre (merge, extracción de audio, faststart), Range, reintentos | Disco y doble ancho de banda |
| D. Combinada | Óptima | Más complejidad |

## Decisión

v1 usa **C** con límites estrictos: tamaño máx. por trabajo, cuota de disco total, TTL corto
(15 min por defecto), borrado al expirar y sweeper de huérfanos. **D** (stream directo para
formatos progresivos únicos, fMP4 por pipe) queda como optimización P2 medida.

Progreso: **SSE** (unidireccional, reconexión nativa, funciona con HTTP/1.1 y proxies) con
`GET /downloads/{id}` como alternativa por polling. WebSockets no aportan nada aquí.

Estado de trabajos **en memoria** (un nodo). Interfaz `JobStore` para migrar a Redis/Postgres
cuando haya varias réplicas. El id del trabajo es un token de 128 bits (capability URL).

Sin transcodificación por defecto: merge/remux con `-c copy`; extracción de audio copia el
códec cuando el contenedor lo permite (m4a/opus) y solo transcodifica a MP3 si se pide.
