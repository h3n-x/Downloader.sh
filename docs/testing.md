# Testing

Principio: la suite por defecto es **determinista y sin Internet**. Las plataformas cambian
y bloquean; eso se vigila aparte (`-m live`), nunca rompe CI.

## Pirámide

| Nivel | Qué cubre | Dónde | Nº |
|---|---|---|---|
| Unit + propiedades | política de IP, URL, nombres de fichero, calidades, clasificador de errores, conversión de info dicts, progreso, casos de uso | `backend/tests/unit/` | 171 |
| Integración | proxy de salida (SSRF, pinning, presupuesto, auth), worker real en subproceso, yt-dlp + FFmpeg descargando **por el proxy** desde un origen local, API completa con lifespan | `backend/tests/integration/` | 48 |
| Frontend unit/componentes | formato, estados del formulario, escape de títulos, errores, flujo de descarga con SSE simulado | `frontend/tests/unit/` | 10 |
| E2E full-stack | backend real (FastAPI, SSE, CSP con hashes) + build real; solo el motor de medios es falso; axe WCAG 2.2 AA; escritorio y móvil | `frontend/tests/e2e/` | 6 × 2 proyectos |
| Live (opt-in) | inspección real contra YouTube/Vimeo con worker y proxy reales | `backend/tests/live/` | 2 |

## Property-based y fuzzing

Hypothesis genera URLs arbitrarias (`validate_url` nunca falla de forma inesperada, salida
idempotente y sin caracteres peligrosos), IPs (IPv4-mapped/NAT64 coherentes con IPv4),
títulos (nombres de fichero siempre seguros, cabeceras sin CR/LF) y listas de formatos
(opciones únicas, ids existentes, re-resolubles). Ya encontró dos defectos reales (6to4
envolviendo IPv4 pública; id `v0` no re-resoluble).

Fuzzing con cobertura (atheris) no se incluye: los parsers propios son pequeños y están
cubiertos por propiedades; el parser grande (yt-dlp) se aísla en un proceso. Ver P2 en
[audit.md](audit.md).

## Comandos

```bash
cd backend
uv run pytest -q                  # todo lo determinista (~7 s)
uv run pytest -q -m "not slow"    # sin subprocesos/FFmpeg (pre-push)
uv run pytest -m live -v          # plataformas reales (requiere Internet sin bloqueos)

cd frontend
pnpm test
pnpm build && pnpm test:e2e       # PLAYWRIGHT_CHROMIUM_PATH=… para usar un Chromium local
```

## Seguridad: casos cubiertos

SSRF (loopback, RFC1918, CGNAT, link-local/metadatos, NAT64, IPv4-mapped, 6to4, Teredo,
multicast, respuestas DNS mixtas, puertos no permitidos, NXDOMAIN, HTTP plano a metadatos),
autenticación/revocación del proxy, presupuesto de bytes, cabeceras gigantes, URLs
malformadas y ofuscadas, userinfo, traversal (estáticos y almacenamiento con symlinks),
inyección en ids de formato/opción, cuerpos grandes (declarados y *chunked*), rate limit,
no filtración de detalles internos, XSS en títulos, CSP sin violaciones en navegador real.
