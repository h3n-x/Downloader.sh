# Auditoría del MVP, scorecard y roadmap

Fecha: 2026-10-06. Base: el commit actual de la primera version completa.
Evidencia: **OBSERVED** (comando/test ejecutado), **INFERRED** (deducido), **PROPOSED**.

## Evidencia medida

| Medida | Resultado | Cómo |
|---|---|---|
| Tests backend | 219 pasan (171 unit/propiedades + 48 integración) en ~7 s | `uv run pytest -q` |
| Tests frontend | 10 Vitest + 12 E2E (6 × escritorio/móvil) | `pnpm test`, `pnpm test:e2e` |
| Tipos | mypy `--strict` 0 errores (53 ficheros); `astro check` strictest 0 errores | CI local |
| Lighthouse 13.5 (móvil, throttling) | Perf 100 · A11y 100 · BP 100 · SEO 100 · LCP 1,5–1,7 s · TBT 0–10 ms · CLS 0 | 2 ejecuciones |
| Peso | HTML 3,9 KB gz · JS 26,9 KB gz · CSS 4,3 KB gz · 0 fuentes | build |
| Accesibilidad | axe WCAG 2.2 AA: 0 violaciones (portada y resultado, 2 viewports); contraste de tokens calculado ≥ 4,5:1 texto / ≥ 3:1 UI en ambos temas | E2E + script |
| Overflow horizontal | 0 px en 320/390/768/1280 | capturas Playwright |
| Dependencias | pip-audit y pnpm audit: 0 vulnerabilidades conocidas | CI local |
| Worker | arranque ~0,5 s, ~50 MB RSS | medido |
| Contenedor | no-root (uid 10001), rootfs RO, worker funciona y solo sale por el proxy | `docker run --read-only …` |

## Hallazgos

| # | Severidad | Área | Evidencia | Impacto | Solución | Archivo(s) | Estado |
|---|---|---|---|---|---|---|---|
| 1 | Alta | Seguridad | `-protocol_whitelist` vía clave `ffmpeg_i` no llegaba a FFmpeg (OBSERVED: `_configuration_args` → `[]`) | Defensa en profundidad inexistente | Claves por postprocesador + test de regresión | `extraction/ytdlp.py` | **Corregido** |
| 2 | Alta | Seguridad | Cuerpo de 30 MB aceptado y parseado antes del 422 (OBSERVED) | Agotamiento de memoria | `BodySizeLimitMiddleware` 16 KiB (declarado y chunked) | `api/middleware.py` | **Corregido** |
| 3 | Alta | Frontend | CSS de componentes solo-cliente ausente en producción (OBSERVED en capturas; warning Rolldown) | UI rota tras analizar; 178 px de overflow a 320 px | `cssCodeSplit: false` + verificación visual | `astro.config.mjs` | **Corregido** (workaround) |
| 4 | Media | Seguridad | `is_global` acepta NAT64→loopback y multicast; 6to4 con IPv4 pública (Hypothesis) | SSRF por rangos de transición | Política propia + propiedades | `security/netpolicy.py` | **Corregido** |
| 5 | Media | Frontend | Páginas `/terminos`… 404 (Astro `format: file` vs StaticFiles) | Enlaces legales rotos | Fallback `.html` sin afectar `/api` | `api/app.py` | **Corregido** |
| 6 | Media | API | HTTP 400 mapeado a `INTERNAL_ERROR` 500 | Errores engañosos | Mapeo 400/413/415 | `api/errors.py` | **Corregido** |
| 7 | Baja | Perf | CLS 0,014 por botón "Pegar" tardío | Salto visual | Render siempre | `Downloader.svelte` | **Corregido** |
| 8 | Alta | Producción | Extracción real no validada en este entorno: su política de red bloquea YouTube y otros (OBSERVED: `CONNECT` 403 del gateway) | Riesgo de mapeos/errores no vistos en real | Ejecutar `pytest -m live` y prueba manual por proveedor en el entorno real | `tests/live/` | **Abierto (P0)** |
| 9 | Alta | Despliegue | Etapa runtime del Dockerfile no construida aquí (apt bloqueado); frontend y venv sí | Imagen final sin validar | CI `image` (build + smoke + Trivy) en verde desde 2026-10-21: imagen sin pip (su copia de urllib3/msgpack/certifi/setuptools tenía avisos con fix), certifi 2026.10.19 y excepción de secretos solo para los extractores de yt-dlp | `Dockerfile`, CI, `trivy-secret.yaml` | **Corregido** |
| 10 | Media | Seguridad | Sin bloqueo de salida a nivel de red del contenedor | Si algo ignorase el proxy, solo quedaría la política de la app | Reglas `DOCKER-USER`/red sin salida salvo proxy | despliegue | Abierto (P1) |
| 11 | Media | Rendimiento/abuso | Cada descarga re-extrae (inspección + descarga = 2 extracciones) | Más peticiones a la plataforma → más bloqueos | Reutilizar el info dict reciente en el worker | `app/`, worker | Abierto (P1) |
| 12 | Media | Abuso | Rate limit solo por IP y en memoria | Ataques distribuidos/IPv6 rotando /64 | PoW/Turnstile-like opcional, límite global por proveedor, store compartido | `api/ratelimit.py` | Abierto (P1) |
| 13 | Baja | Privacidad | Miniaturas cargadas desde CDNs de plataformas (`img-src https:`) | La plataforma ve la IP del usuario | Opción de proxy de miniaturas con caché | frontend/API | Abierto (P2) |
| 14 | Baja | Observabilidad | Sin trazas ni dashboards/alertas versionados | Diagnóstico más lento | OpenTelemetry + reglas Prometheus | `observability.py` | Abierto (P2) |
| 15 | Baja | Operación | Imagen estimada ~0,5 GB (FFmpeg de Debian + Deno ~100 MB) — INFERRED | Pull más lento | FFmpeg mínimo / Deno solo si YouTube habilitado | `Dockerfile` | Abierto (P3) |

### Auditorías por área (resumen)

- **Arquitectura**: capas limpias y puertos reales (motor, backend de medios, almacenamiento);
  un único módulo conoce yt-dlp; sin infraestructura innecesaria. Riesgo: estado en memoria
  limita a un nodo (decisión explícita, ADR 0003).
- **Seguridad**: SSRF en dos capas con pinning DNS; procesos sin shell; límites de kernel,
  cgroup y aplicación; CSP estricta con hashes. Ver [security.md](security.md) y riesgos residuales.
- **Dependencias**: pocas y justificadas (FastAPI, Pydantic, uvicorn, prometheus-client,
  yt-dlp, deno; Astro, Svelte, openapi-fetch). Lockfiles congelados, auditorías en CI.
- **Rendimiento**: frontend medido (arriba). Backend: el coste real es red/FFmpeg; sin
  transcodificación de vídeo; worker 0,5 s de arranque aceptable frente a extracciones de segundos.
- **Accesibilidad**: semántica, landmarks, foco gestionado, `aria-live`, `aria-invalid`,
  targets ≥ 44 px, `prefers-reduced-motion`, sin dependencia exclusiva del color. Falta prueba
  manual con lectores de pantalla (VoiceOver/NVDA/TalkBack).
- **UX**: una acción principal, errores accionables por código, calidades reales con tamaño,
  opciones fuera de límite deshabilitadas con motivo, progreso determinado/indeterminado.
  Faltan: posición en cola, publicaciones multi-elemento, historial local.
- **API**: contrato OpenAPI único, errores homogéneos, ids-capacidad, SSE + polling, Range.
- **Tests**: pirámide completa sin red; propiedades que ya encontraron bugs; E2E full-stack.
  Hueco: validación live (#8).
- **Despliegue**: compose endurecido, CI con smoke test de imagen, Trivy (vulnerabilidades y secretos), SBOM; la imagen final ya se valida en CI (#9).
- **Documentación**: README, arquitectura, seguridad, configuración, despliegue, testing,
  troubleshooting, legal, ADRs.

## Scorecard

| Área | Nota | Justificación |
|---|---:|---|
| Arquitectura | 8.5/10 | Separación real y evolutiva, ADRs; −1,5: un nodo, doble extracción |
| Backend | 8/10 | Tipado estricto, errores tipados, límites; −2: comportamiento real por plataforma sin validar aquí |
| Frontend | 8/10 | Rápido, accesible, CSP estricta, tipos generados; −2: workaround de build, sin i18n real ni multi-elemento |
| Seguridad | 8/10 | SSRF robusto y probado, sin shell, hardening de contenedor; −2: sin bloqueo de red de host, rate limit básico, sin seccomp dedicado |
| Rendimiento | 8/10 | Lighthouse 100, CLS 0, 26,9 KB JS gz; −2: doble extracción, sin streaming (espera la descarga completa) |
| Accesibilidad | 8.5/10 | axe 0 violaciones, contraste calculado; −1,5: sin pruebas con lectores de pantalla reales |
| UX | 7.5/10 | Flujo claro y errores útiles; −2,5: sin cola visible, sin carruseles, YouTube puede fallar desde datacenter |
| Testing | 8.5/10 | 241 tests deterministas + live opt-in; −1,5: live no ejecutado, sin fuzzing con cobertura |
| Mantenibilidad | 8.5/10 | Lint/tipos estrictos, contratos generados; −1,5: dependencia crítica de yt-dlp |
| Observabilidad | 7/10 | Logs JSON, request ids, métricas, health/ready; −3: sin trazas, alertas ni dashboards |
| Documentación | 8.5/10 | Completa y basada en evidencia; −1,5: falta runbook de incidentes y guía de contribución |
| Production readiness | 6/10 | Base sólida, pero con P0 abiertos (validación live, imagen final en CI, identidad legal, licencia) |

## Roadmap post-MVP

Formato: Impacto · Esfuerzo · Riesgo · Dependencias · Motivo.

### P0 — Antes de producción

1. **Validación live por proveedor** · Alto · M · Bajo · Internet sin bloqueos · Confirmar extracción, mapeo de errores y formatos reales (#8).
2. ~~**Imagen final verde en CI** (build, smoke, Trivy) · Alto · S · Bajo · CI · #9.~~ Hecho (2026-10-21).
3. **Identidad del operador, contacto de copyright y revisión jurídica** de las páginas legales y de YouTube/EJS · Alto · M · Medio · abogado · [legal.md](legal.md).
4. **Licencia del repositorio** · Medio · S · Bajo · decisión del titular · Necesaria para self-hosting/contribuciones.
5. **Proxy inverso + `DL_FORWARDED_ALLOW_IPS` + bloqueo de salida a redes privadas** · Alto · S · Bajo · host · Slowloris, rate limit correcto, defensa SSRF en red.

### P1 — Próxima versión

1. Reutilizar la extracción reciente al descargar · Alto · M · Medio · — · Menos bloqueos y latencia (#11).
2. Mostrar posición en cola y ETA de inicio · Medio · S · Bajo · — · UX bajo carga.
3. Publicaciones multi-elemento (carruseles, tweets con varios vídeos) · Alto · M · Bajo · — · Muy común en X/Instagram.
4. Defensa anti-bots respetuosa (proof-of-work invisible) + límites globales por proveedor · Alto · M · Medio · — · DDoS económico (#12).
5. Alertas Prometheus versionadas (`PLATFORM_BLOCKED`, `EXTRACTOR_FAILED`, disco) · Medio · S · Bajo · — · Detección temprana de roturas.
6. Pruebas manuales con lectores de pantalla · Medio · S · Bajo · — · Completar WCAG.

### P2 — Evolución

1. Entrega en streaming para formatos progresivos únicos (sin disco) · Alto · M · Medio · medición · Menos latencia y disco.
2. Subtítulos y miniatura como descargas opcionales · Medio · S · Bajo · — · Valor alto, coste bajo.
3. Proxy de miniaturas con caché (privacidad) · Medio · S · Bajo · — · #13.
4. Share target (PWA mínima) + `?url=` ya soportado · Medio · S · Bajo · — · Flujo móvil "compartir → descargar".
5. OpenTelemetry (trazas API→worker) · Medio · M · Bajo · — · #14.
6. Fuzzing con cobertura (atheris) del validador de URL y del proxy · Bajo · S · Bajo · — · Complementa Hypothesis.
7. Segundo idioma (inglés) · Medio · S · Bajo · — · Estructura ya preparada.

### P3 — Experimentos

1. Historial solo local (IndexedDB, opt-in) · Medio · S · Bajo.
2. CLI/companion y bookmarklet que usen la misma API · Medio · S · Medio (abuso).
3. Adaptador gallery-dl para imágenes · Medio · M · Medio.
4. Conversión opcional a MP3 con límite de CPU estricto · Medio · S · Medio.
5. Imagen más pequeña (FFmpeg mínimo, Deno opcional) · Bajo · M · Bajo (#15).

### P4 — Escalabilidad futura (solo con demanda medida)

1. `JobStore` compartido (Redis/Postgres) + rate limit compartido.
2. Workers detrás de una cola, en contenedores sin red salvo el proxy (mismo protocolo JSONL).
3. Almacenamiento de objetos con URLs firmadas de vida corta.
4. Frontend en CDN; API pública con claves y cuotas (el core ya es reutilizable).

## Funcionalidades futuras evaluadas

| Funcionalidad | Impacto | Complejidad | Coste operacional | Riesgo | Valor usuario | Prioridad |
|---|---|---|---|---|---|---|
| Multi-elemento (carruseles) | Alto | Media | Bajo | Bajo | Alto | P1 |
| Subtítulos | Medio | Baja | Bajo | Bajo | Medio | P2 |
| Miniatura | Bajo | Baja | Bajo | Bajo | Medio | P2 |
| Share target / PWA mínima | Medio | Baja | Nulo | Bajo | Alto (móvil) | P2 |
| Historial local | Medio | Baja | Nulo | Bajo | Medio | P3 |
| Presets (p. ej. "siempre audio") | Bajo | Baja | Nulo | Bajo | Medio | P3 |
| Conversión de formato | Medio | Baja | Alto (CPU) | Medio | Medio | P3 |
| Exportar metadatos (JSON) | Bajo | Baja | Nulo | Bajo | Bajo | P3 |
| QR desde móvil | Bajo | Baja | Nulo | Bajo | Bajo | P3 |
| Bookmarklet | Medio | Baja | Medio | Medio (abuso) | Medio | P3 |
| Extensión de navegador | Medio | Media | Medio | Medio (tiendas, ToS) | Medio | P4 |
| CLI companion | Medio | Baja | Medio | Medio | Medio (avanzados) | P3 |
| API pública | Alto | Media | Alto | Alto (abuso) | Medio | P4 |
| Batch / playlists | Alto | Alta | Muy alto | Alto (piratería, bloqueos) | Medio | P4 |
| Plugins/proveedores externos | Medio | Media | Bajo | Alto (código no confiable) | Bajo | No |
| Self-hosting (Compose ya incluido) | Alto | Baja | Nulo (para nosotros) | Bajo | Alto | P1 (documentar) |

## Oportunidades estratégicas

Qué podría hacerlo excelente, no "otro descargador":

1. **Privacidad verificable como producto.** Sin cuentas, sin cookies, logs sin URLs ni IPs,
   archivos que se autodestruyen, CSP estricta: publicarlo como "transparency page" con las
   métricas de retención reales y el código abierto auditable.
2. **El mejor self-hosting del segmento.** Una imagen endurecida, `compose up`, SSRF resuelto
   de serie y límites sensatos: para familias, equipos y creadores que quieren *su* instancia.
   Esto además reduce el riesgo legal y de abuso de una gran instancia pública.
3. **Herramienta de archivo para creadores.** "Guarda tus propias publicaciones" (backup de lo
   que has subido) es el caso de uso más defendible: textos, flujos y límites orientados a ello.
4. **Calidad honesta.** Mostrar solo lo que existe, con tamaño, códec y motivo cuando algo no
   es posible, y nunca transcodificar en secreto: la confianza es el diferenciador.
5. **Velocidad percibida.** Single-flight + caché ya existen; reutilizar la extracción y servir
   en streaming los formatos progresivos haría que muchas descargas empiecen en < 2 s.
6. **Flujo móvil nativo.** Share target: "Compartir → downloader.sh → Guardar", sin copiar enlaces.
7. **Motor intercambiable.** El puerto `MediaExtractor` y el protocolo JSONL permiten añadir
   APIs oficiales donde existan (más estables y legítimas) sin tocar la UI.
