# Plan técnico — Downloader.sh

Fecha de referencia: **2026-10-06**. Etiquetas: **OBSERVED** (verificado con comando/fuente),
**INFERRED** (deducido), **PROPOSED** (decisión de diseño).

## 0. Estado del repositorio

OBSERVED (`git log`, `ls`): greenfield. Un commit (`ac4d061 Repo Base`) con `README.md` de una línea.
Sin CI. Se diseña desde cero.

OBSERVED (entorno): Ubuntu 24.04, Python 3.13.16, uv 0.11.32, Node 22.22, pnpm 10.28, Bun 1.4.2,
Rust 1.97, Go 1.24, Docker 29.8, FFmpeg 6.1.1. Postgres y Redis instalados pero **no necesarios**.

## 1. Investigación del ecosistema (octubre 2026)

### Motores de extracción

| Motor | Estado (OBSERVED) | Cobertura | Integración | Veredicto |
|---|---|---|---|---|
| **yt-dlp** 2026.8.19 (PyPI) | Muy activo; releases frecuentes; ~1750 extractores (contados con `gen_extractor_classes()`) | La mayor del ecosistema | API Python (`YoutubeDL`) con `progress_hooks`, excepciones tipadas, `allowed_extractors`, `proxy` | **Elegido** como adaptador principal |
| cobalt (imput) | Activo, AGPL-3.0, servicio Node | ~25 sitios | API HTTP propia; habría que operarlo como servicio aparte | Alternativa/adaptador futuro; AGPL condiciona |
| gallery-dl 1.32.15 | Activo | Imágenes/galerías | API Python | Futuro adaptador para imágenes (fuera de MVP) |
| APIs oficiales | Requieren apps/OAuth/cuotas, raramente exponen el binario | Parcial | Por proveedor | Solo si un proveedor lo exige legítimamente |

Hechos verificados que condicionan el diseño:

- yt-dlp necesita un runtime JS externo + `yt-dlp-ejs` para soporte completo de YouTube desde 2025.11.12;
  **Deno** es el único habilitado por defecto ([issue #15012](https://github.com/yt-dlp/yt-dlp/issues/15012)).
  `deno` está publicado en PyPI (2.9.7) → se fija como dependencia reproducible.
- Bun quedó deprecado como runtime de yt-dlp (anuncio 2026-05-21) → no lo usamos.
- OBSERVED en `yt_dlp/extractor/youtube/jsc/_builtin/deno.py`: Deno se ejecuta con
  `--no-remote --no-config --cached-only` y **sin** flags `--allow-*` (Deno es deny-by-default ⇒ sin red ni FS).
- OBSERVED en `yt_dlp/downloader/__init__.py`: FFmpeg actúa como *downloader de red* solo para
  directos, rtmp, secciones o cuando `external_downloader` no es `native`. Con
  `external_downloader={'default': 'native'}` y rechazando directos, **FFmpeg solo toca ficheros locales**.
- yt-dlp ejecuta sus propias peticiones HTTP: **validar la URL de entrada no basta contra SSRF**
  (redirects, manifiestos HLS/DASH, URLs de CDN). Hace falta control en la capa de red (ver §4).

### Hallazgos de tooling (OBSERVED en registros npm/PyPI)

- FastAPI 0.142.2 con **SSE nativo** (`fastapi.sse.EventSourceResponse`, desde 0.135).
- Astro 7.3.6 (Vite 8, compilador Rust), Svelte 5.57, `@astrojs/svelte` 9.0.1.
- TypeScript 7.0.2 es `latest`, pero `@astrojs/check`, `svelte-check` y `@astrojs/svelte` declaran
  `typescript: ^5 || ^6` ⇒ **se fija TypeScript 6.x**.
- SvelteKit 3.0.1 publicado el mismo día de referencia ⇒ demasiado reciente para producción.
- ruff 0.16, mypy 2.4, pytest 9.1, hypothesis 6.168, pip-audit 2.10, Biome 2.5, Vitest 5, Playwright 1.63.

## 2. Comparación de stack

### Backend

| Opción | Ventajas | Desventajas | Complejidad | Rendimiento | Mantenimiento | Adecuación |
|---|---|---|---|---|---|---|
| **Python 3.13 + FastAPI + workers yt-dlp en subproceso** | yt-dlp como librería: info dicts estructurados, hooks de progreso, excepciones tipadas; OpenAPI y SSE nativos; Pydantic genera contratos | GIL irrelevante (I/O + subprocesos); memoria API ~60 MB | Baja | Suficiente: el cuello es red/FFmpeg, no el API | Alto: un lenguaje en backend | **9/10** |
| Python + Litestar 2.24 | Muy buen rendimiento, DI, msgspec | Menor ecosistema; última release junio 2026; SSE propio | Baja-media | Algo mejor que FastAPI | Medio | 7/10 |
| Go (net/http) o Rust (axum) + CLI `yt-dlp` | Memoria mínima, binario único, concurrencia excelente | yt-dlp sigue siendo Python ⇒ dos runtimes; parseo de stdout/stderr; clasificación de errores por texto | Media-alta | Máximo en control-plane (no en el cuello real) | Medio | 6/10 |
| Node/Hono + CLI `yt-dlp` | Tipos compartidos con el frontend | Mismos problemas que Go/Rust sin su ventaja de recursos | Media | Bueno | Medio | 5/10 |

No elegimos Python "porque yt-dlp es Python", sino porque la API in-process da **errores tipados y
progreso estructurado** que con el CLI habría que reconstruir parseando texto, y porque el coste
dominante (ancho de banda, FFmpeg) no depende del lenguaje del API.

### Frontend

| Opción | Ventajas | Desventajas | Complejidad | Rendimiento | Mantenimiento | Adecuación |
|---|---|---|---|---|---|---|
| **Astro 7 (estático) + isla Svelte 5** | HTML estático por defecto; JS solo en la isla; páginas legales/SEO sin JS; sin servidor Node en producción | Dos modelos mentales (Astro + Svelte) | Baja | Excelente (JS mínimo) | Alto | **9/10** |
| SvelteKit 3 (adapter-static) | Un solo framework, routing | 3.0.1 salió el 2026-10-06 (riesgo de madurez) | Baja | Excelente | Medio (hoy) | 7/10 |
| Next.js 16 / React 19 | Ecosistema enorme | Runtime React para una sola pantalla interactiva; servidor Node o export | Media | Bueno | Medio | 5/10 |
| Nuxt 4 / Vue 3.5 | Maduro | Mismo argumento que Next | Media | Bueno | Medio | 5/10 |
| Vanilla TS + Vite | Mínimo absoluto | Estado/UI a mano, peor testabilidad | Baja | Máximo | Bajo a escala | 6/10 |

### Recomendaciones

1. **Principal**: FastAPI (API + gestor de trabajos en proceso) + workers yt-dlp en subprocesos
   aislados + proxy de salida anti-SSRF + Astro estático con una isla Svelte. Una imagen, un proceso.
2. **Conservadora**: la misma, pero con frontend Astro + vanilla TS (sin Svelte) y descargas
   solo en servidor (sin streaming); SQLite si se necesitase persistir algo.
3. **Máximo rendimiento**: control-plane en Rust (axum) o Go, workers yt-dlp detrás de una cola,
   FFmpeg emitiendo fMP4 a stdout para streaming sin disco, frontend en CDN. Solo con demanda real.

## 3. Arquitectura recomendada

```text
Navegador ──HTTP──► FastAPI (un proceso, uvicorn)
                     ├── api/        rutas, contratos Pydantic, errores, rate limit
                     ├── app/        casos de uso: InspectService, JobManager
                     ├── domain/     modelos (MediaInfo, MediaFormat, QualityOption…), errores
                     ├── security/   validación URL, política de IP, nombres de fichero
                     └── infra/
                         ├── egress proxy (asyncio, 127.0.0.1) ◄──── todo el tráfico del worker
                         ├── worker launcher (subprocess_exec, rlimits, JSONL por stdout)
                         └── storage temporal (dir 0700 por trabajo, TTL, sweeper)
                                   │
                     worker (python -m downloader.worker) ── yt-dlp ── Deno (sin permisos)
                                                          └─ FFmpeg (solo ficheros locales)
```

- El **dominio no importa yt-dlp**. `MediaExtractor` es un `Protocol`; `YtDlpExtractor` es un adaptador.
- Los proveedores son **datos** (registro `extractor_key → nombre, slug`), no una cascada `if/elif`.
  La detección usa `suitable()` de los extractores permitidos.
- El worker habla un **protocolo JSONL** (stdin: petición; stdout: eventos). El mismo protocolo
  permite moverlo a un contenedor/cola separados sin tocar API ni dominio.

## 4. Threat model (resumen; detalle en `docs/security.md`)

| Amenaza | Vector | Control principal |
|---|---|---|
| SSRF / metadata cloud / red interna | URL del usuario, redirects, manifiestos, CDN | Validación de entrada **y** proxy de salida obligatorio: resuelve DNS, rechaza IPs no globales, conecta a la IP validada (anti DNS-rebinding), solo puertos 80/443 |
| DNS rebinding | TTL bajo, respuesta distinta en 2ª resolución | El proxy fija la IP comprobada; no hay segunda resolución |
| Inyección de comandos/argumentos | URL/format id al CLI | Sin shell; yt-dlp vía API Python; `format_id` validado contra los formatos reales |
| Path traversal / overwrite / symlinks | Título como nombre de fichero | Nombre en disco fijo (`media.<ext>`), dir por trabajo 0700 creado con `mkdtemp`; nombre visible sanitizado solo en `Content-Disposition` (RFC 6266/5987) |
| Agotamiento de disco/CPU/memoria/procesos | Ficheros grandes, muchos trabajos | Límite de bytes en el proxy + `RLIMIT_FSIZE`, `max_filesize`, duración máx., concurrencia global y por cliente, cola acotada (503 + `Retry-After`), timeouts, kill del grupo de procesos |
| Abuso / DDoS económico | Bots | Rate limit por cliente, cuotas, sin enlaces públicos persistentes, TTL corto |
| XSS | Título/autor del contenido | Svelte escapa por defecto; CSP estricta sin `unsafe-inline` para scripts; miniaturas solo `https:` |
| Fuga de información | Errores, logs | Envelope de error con códigos; sin trazas al cliente; URLs no se registran (solo host + hash) |
| Plugins/config de yt-dlp | Ficheros en `$HOME` | `ignoreconfig`, `HOME` aislado, sin cookies, sin `exec`, sin plugins |

## 5. Flujo de datos

```text
URL ─► validate_url (sintaxis, esquema, userinfo, puerto, IDNA, IP literal)
    ─► provider_registry.detect (suitable() de extractores permitidos) ─► 422 UNSUPPORTED_SITE
    ─► worker inspect (yt-dlp extract_info download=False vía proxy) ─► MediaInfo + QualityOptions
    ─► usuario elige opción (option_id)
    ─► POST /downloads ─► JobManager (cola acotada) ─► worker download
         ─► yt-dlp descarga formatos nativos vía proxy ─► FFmpeg merge/remux/extract (local)
         ─► eventos JSONL ─► SSE al navegador
    ─► GET /downloads/{id}/file (Range, Content-Disposition) ─► expiración TTL ─► borrado
```

## 6. Ciclo de vida de una descarga

```text
queued ─► preparing ─► downloading ─► processing ─► ready ─► expired
   │           │             │              │
   └───────────┴─────────────┴──────────────┴─► failed (code) | cancelled
```

`ready` dura `DOWNLOAD_TTL` (por defecto 15 min). El sweeper borra directorios huérfanos al
arrancar y cada minuto, por lo que un crash no deja ficheros indefinidamente.

## 7. Alcance MVP

- Landing con campo URL protagonista; análisis; metadatos; calidades reales; vídeo/audio.
- Descarga en servidor con progreso SSE (determinado o indeterminado), entrega con Range.
- Errores tipados y accionables. Proveedores: YouTube, X, Instagram, TikTok, Facebook, Reddit,
  Twitch (clips/VOD), Vimeo, SoundCloud, Bluesky, Dailymotion, Streamable (allowlist configurable).
- Seguridad: proxy de salida, límites, rate limit, CSP, contenedor no-root.
- Páginas: Términos, Privacidad, Copyright/Takedown, Uso aceptable (borradores a revisar por abogado).
- Tema claro/oscuro sin flash, i18n preparada (ES inicial), WCAG 2.2 AA.

## 8. Non-goals explícitos

- DRM, paywalls, cookies/credenciales de usuario, contenido privado, *PO tokens* u otros
  generadores de atestación anti-bot, impersonación TLS (`curl_cffi`).
- Directos (live). Playlists y batch (P2). Cuentas de usuario, base de datos, Redis, colas externas.
- Extractor genérico (cualquier web) desactivado por defecto: amplía mucho la superficie SSRF.

## 9. Estructura del repositorio

```text
backend/            Python (uv): src/downloader/{api,app,domain,security,infra,worker}, tests/
frontend/           Astro + Svelte: src/{components,pages,lib,styles,i18n}, tests/
docs/               arquitectura, seguridad, despliegue, ADRs, auditoría
.github/workflows/  CI
Dockerfile, compose.yaml, lefthook.yml
```

## 10. Roadmap de implementación

A. Fundación: uv/pnpm, ruff, mypy strict, pytest, Biome, lefthook, ADRs.
B. Núcleo: validación URL + política IP (con tests de propiedades), modelos de dominio, registro
   de proveedores, adaptador yt-dlp, taxonomía de errores, selección de calidades.
C. API: contratos, endpoints, envelope de error, request id, rate limit, cabeceras de seguridad.
D. Pipeline: proxy de salida, launcher de workers, JobManager, SSE, entrega, limpieza.
E. Frontend: tokens, landing, formulario, resultado, selector, progreso, errores, legales.
F. Hardening: rlimits, límites de tamaño, tests SSRF de extremo a extremo contra el proxy.
G. Calidad: e2e Playwright con API simulada, axe, presupuesto de rendimiento.
H. Producción: Dockerfile multi-stage no-root, CI, observabilidad, documentación de despliegue.

Orden adaptado: el **proxy de salida (F)** se adelanta a D porque el worker no debe hacer ninguna
petición de red sin él.

## Supuestos importantes

1. Un único nodo inicialmente (estado de trabajos en memoria; se pierde al reiniciar — aceptable).
2. Despliegue en VPS/contenedor con ancho de banda generoso; **serverless no es adecuado** para
   el worker (conexiones largas, FFmpeg, disco temporal).
3. YouTube desde IPs de datacenter suele exigir "confirma que no eres un bot"; **no** lo eludimos
   (sin cookies ni PO tokens) y se reporta como `PLATFORM_BLOCKED`. INFERRED a partir de
   comportamiento ampliamente documentado; verificar en el despliegue real.
4. La UI inicial es en español; strings centralizados para añadir idiomas.
5. Los textos legales son borradores técnicos, **no asesoramiento jurídico**.
