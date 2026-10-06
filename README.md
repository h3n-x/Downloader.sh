# downloader.sh

Pega el enlace de una publicación pública (YouTube, X, Instagram, TikTok, Facebook, Reddit,
Twitch, Vimeo, SoundCloud, Bluesky, Dailymotion, Streamable), elige una calidad **real** y
descárgala. Sin cuentas, sin cookies de terceros, sin rastreadores.

> **Responsabilidad.** Descarga solo contenido propio, con licencia o con permiso. El
> servicio no elude DRM, muros de pago, inicios de sesión ni medidas anti-bot.

## Arquitectura en una imagen

```text
Navegador ── Astro (estático) + isla Svelte
   │  HTTP JSON + SSE (mismo origen, CSP estricta)
   ▼
FastAPI ── InspectService / JobManager (memoria, cola acotada, TTL)
   │  JSONL por stdin/stdout, un subproceso por trabajo (rlimits, sesión propia)
   ▼
Worker ── yt-dlp (allowlist de extractores) ── FFmpeg (solo ficheros locales)
   │  todo el tráfico
   ▼
Proxy de salida (token por trabajo, IP pública fijada, puertos 80/443, presupuesto de bytes)
```

Detalles: [docs/architecture.md](docs/architecture.md) · seguridad:
[docs/security.md](docs/security.md) · decisiones: [docs/adr/](docs/adr/) · plan e
investigación: [docs/plan.md](docs/plan.md) · auditoría y roadmap: [docs/audit.md](docs/audit.md).

## Inicio rápido (desarrollo)

Requisitos: Python 3.13 + [uv](https://docs.astral.sh/uv/), Node 22.12+ + pnpm 10, FFmpeg.

```bash
# Backend (http://127.0.0.1:8000)
cd backend
uv sync
DL_ENVIRONMENT=development uv run python -m downloader

# Frontend (http://127.0.0.1:4321, proxifica /api al backend)
cd frontend
pnpm install
pnpm dev
```

Deno (runtime JS que yt-dlp necesita para YouTube) se instala como dependencia Python.

## Producción

```bash
cp .env.example .env    # ajusta límites y secretos
docker compose up -d --build
```

Pon un proxy inverso con TLS delante (ver [docs/deployment.md](docs/deployment.md)).

## Calidad

| Comando | Qué hace |
|---|---|
| `cd backend && uv run pytest -q` | 219 tests unitarios/integración/propiedades (sin red) |
| `uv run ruff check . && uv run mypy src tests` | lint + tipos estrictos |
| `cd frontend && pnpm check && pnpm test` | `astro check` (TS strictest) + Vitest |
| `pnpm build && pnpm test:e2e` | E2E full-stack (backend real + build) con axe |
| `uv run pytest -m live` | comprobaciones contra plataformas reales (opt-in) |

Más en [docs/development.md](docs/development.md) y [docs/testing.md](docs/testing.md).

## Licencia

Pendiente de decisión por el titular del repositorio (ver [docs/audit.md](docs/audit.md), P0).
