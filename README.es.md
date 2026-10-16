<h3 align="center">
  <img src="https://raw.githubusercontent.com/catppuccin/catppuccin/main/assets/misc/transparent.png" height="30" width="0"/>
  downloader.sh
  <img src="https://raw.githubusercontent.com/catppuccin/catppuccin/main/assets/misc/transparent.png" height="30" width="0"/>
  <br/>
  <a href="https://github.com/h3n-x/Downloader.sh">Pega un enlace público, elige una calidad real y descárgalo: sin cuentas, sin cookies de terceros, sin rastreadores</a>
  <br/><br/>
  <p>
    🌐 <a href="README.md">English</a> · <strong>Español</strong>
  </p>
</h3>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.13-74c7ec?style=for-the-badge&logo=python&logoColor=d9e0ee&labelColor=363a4f" alt="Python"/>
  <img src="https://img.shields.io/badge/FastAPI-SSE-94e2d5?style=for-the-badge&logo=fastapi&logoColor=d9e0ee&labelColor=363a4f" alt="FastAPI"/>
  <img src="https://img.shields.io/badge/Astro-7-fab387?style=for-the-badge&logo=astro&logoColor=d9e0ee&labelColor=363a4f" alt="Astro"/>
  <img src="https://img.shields.io/badge/Svelte-5-f38ba8?style=for-the-badge&logo=svelte&logoColor=d9e0ee&labelColor=363a4f" alt="Svelte"/>
  <img src="https://img.shields.io/badge/yt--dlp-allowlisted-cba6f7?style=for-the-badge&labelColor=363a4f" alt="yt-dlp"/>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/tests-219_backend-a6e3a1?style=for-the-badge&logo=pytest&logoColor=d9e0ee&labelColor=363a4f" alt="tests"/>
  <img src="https://img.shields.io/badge/E2E-axe-a6e3a1?style=for-the-badge&labelColor=363a4f" alt="E2E"/>
  <img src="https://img.shields.io/badge/license-pending-f9e2af?style=for-the-badge&labelColor=363a4f" alt="license"/>
</p>

<p align="center">
  <a href="docs/architecture.md">Arquitectura</a>
  ·
  <a href="docs/security.md">Seguridad</a>
  ·
  <a href="#-inicio-rápido">Inicio rápido</a>
  ·
  <a href="docs/audit.md">Auditoría y roadmap</a>
</p>

&nbsp;

## 🪄 Acerca de

Pega el enlace de una publicación pública (YouTube, X, Instagram, TikTok, Facebook, Reddit, Twitch, Vimeo, SoundCloud, Bluesky,
Dailymotion, Streamable), elige una calidad **real** y descárgala. Sin cuentas, sin cookies de terceros, sin rastreadores.

> [!IMPORTANT]
> **Responsabilidad.** Descarga solo contenido propio, con licencia o con permiso. El servicio no elude DRM, muros de pago,
> inicios de sesión ni medidas anti-bot.

&nbsp;

## 🏛️ Arquitectura

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

| | |
|---|---|
| 🧱 **Workers aislados** | Cada descarga corre en su propio subproceso con límites de recursos y sesión propia, hablando JSONL por stdin/stdout. |
| 🌐 **Barrera SSRF** | Todo el tráfico del worker pasa por un proxy de salida: un token por trabajo, IP pública fijada, solo puertos 80/443 y un presupuesto de bytes. |
| ✅ **Extractores en allowlist** | yt-dlp solo usa los extractores de las plataformas soportadas; FFmpeg solo toca ficheros locales. |
| ⚡ **Progreso en vivo** | Server-Sent Events de FastAPI a una isla Svelte dentro de un sitio Astro estático, con CSP estricta. |

Detalles: [arquitectura](docs/architecture.md) · [seguridad](docs/security.md) · [decisiones (ADR)](docs/adr/) ·
[plan e investigación](docs/plan.md) · [auditoría y roadmap](docs/audit.md).

&nbsp;

## 🚀 Inicio rápido

**Requisitos:** Python 3.13 + [uv](https://docs.astral.sh/uv/), Node 22.12+ + pnpm 10, FFmpeg. Deno (el runtime JS que yt-dlp
necesita para YouTube) se instala como dependencia de Python.

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

**Producción:**

```bash
cp .env.example .env    # ajusta límites y secretos
docker compose up -d --build
```

> [!TIP]
> Pon un proxy inverso con TLS delante: ver [docs/deployment.md](docs/deployment.md).

&nbsp;

## 🧪 Calidad

| Comando | Qué hace |
|---|---|
| `cd backend && uv run pytest -q` | 219 tests unitarios, de integración y de propiedades (sin red) |
| `uv run ruff check . && uv run mypy src tests` | Lint y tipos estrictos |
| `cd frontend && pnpm check && pnpm test` | `astro check` (TS strictest) y Vitest |
| `pnpm build && pnpm test:e2e` | E2E full-stack (backend real y build) con axe |
| `uv run pytest -m live` | Comprobaciones contra las plataformas reales (opcional) |

Más en [docs/development.md](docs/development.md) y [docs/testing.md](docs/testing.md).

&nbsp;

## 📄 Licencia

Pendiente de decisión por el titular del repositorio (ver [docs/audit.md](docs/audit.md), P0).

&nbsp;

<p align="center">
  <img src="https://raw.githubusercontent.com/catppuccin/catppuccin/main/assets/footers/gray0_ctp_on_line.svg?sanitize=true" alt=""/>
</p>

<p align="center">
  Copyright © 2026 <a href="https://github.com/h3n-x">h3n-x</a>
</p>
