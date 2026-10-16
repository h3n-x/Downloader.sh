<h3 align="center">
  <img src="https://raw.githubusercontent.com/catppuccin/catppuccin/main/assets/misc/transparent.png" height="30" width="0"/>
  downloader.sh
  <img src="https://raw.githubusercontent.com/catppuccin/catppuccin/main/assets/misc/transparent.png" height="30" width="0"/>
  <br/>
  <a href="https://github.com/h3n-x/Downloader.sh">Paste a public link, pick a real quality, download it: no accounts, no third-party cookies, no trackers</a>
  <br/><br/>
  <p>
    🌐 <strong>English</strong> · <a href="README.es.md">Español</a>
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
  <a href="docs/architecture.md">Architecture</a>
  ·
  <a href="docs/security.md">Security</a>
  ·
  <a href="#-quick-start">Quick start</a>
  ·
  <a href="docs/audit.md">Audit & roadmap</a>
</p>

&nbsp;

## 🪄 About

Paste the link of a public post (YouTube, X, Instagram, TikTok, Facebook, Reddit, Twitch, Vimeo, SoundCloud, Bluesky,
Dailymotion, Streamable), pick a **real** quality and download it. No accounts, no third-party cookies, no trackers.

> [!IMPORTANT]
> **Responsibility.** Download only your own content, licensed content or content you have permission for. The service does
> not bypass DRM, paywalls, logins or anti-bot measures.

&nbsp;

## 🏛️ Architecture

```text
Browser ── Astro (static) + Svelte island
   │  HTTP JSON + SSE (same origin, strict CSP)
   ▼
FastAPI ── InspectService / JobManager (in memory, bounded queue, TTL)
   │  JSONL over stdin/stdout, one subprocess per job (rlimits, own session)
   ▼
Worker ── yt-dlp (extractor allowlist) ── FFmpeg (local files only)
   │  all traffic
   ▼
Egress proxy (per-job token, pinned public IP, ports 80/443, byte budget)
```

| | |
|---|---|
| 🧱 **Isolated workers** | Every download runs in its own subprocess with resource limits and its own session, talking JSONL over stdin/stdout. |
| 🌐 **SSRF barrier** | All worker traffic goes through an egress proxy: a token per job, a pinned public IP, only ports 80/443 and a byte budget. |
| ✅ **Allowlisted extractors** | yt-dlp only runs the extractors of the supported platforms; FFmpeg only touches local files. |
| ⚡ **Live progress** | Server-Sent Events from FastAPI to a Svelte island inside a static Astro site, under a strict CSP. |

Details: [architecture](docs/architecture.md) · [security](docs/security.md) · [decisions (ADRs)](docs/adr/) ·
[plan and research](docs/plan.md) · [audit and roadmap](docs/audit.md).

&nbsp;

## 🚀 Quick start

**Requirements:** Python 3.13 + [uv](https://docs.astral.sh/uv/), Node 22.12+ + pnpm 10, FFmpeg. Deno (the JS runtime yt-dlp
needs for YouTube) is installed as a Python dependency.

```bash
# Backend (http://127.0.0.1:8000)
cd backend
uv sync
DL_ENVIRONMENT=development uv run python -m downloader

# Frontend (http://127.0.0.1:4321, proxies /api to the backend)
cd frontend
pnpm install
pnpm dev
```

**Production:**

```bash
cp .env.example .env    # adjust limits and secrets
docker compose up -d --build
```

> [!TIP]
> Put a reverse proxy with TLS in front of it: see [docs/deployment.md](docs/deployment.md).

&nbsp;

## 🧪 Quality

| Command | What it does |
|---|---|
| `cd backend && uv run pytest -q` | 219 unit, integration and property tests (no network) |
| `uv run ruff check . && uv run mypy src tests` | Lint and strict typing |
| `cd frontend && pnpm check && pnpm test` | `astro check` (strictest TS) and Vitest |
| `pnpm build && pnpm test:e2e` | Full-stack E2E (real backend and build) with axe |
| `uv run pytest -m live` | Checks against the real platforms (opt-in) |

More in [docs/development.md](docs/development.md) and [docs/testing.md](docs/testing.md).

&nbsp;

## 📄 License

Pending a decision by the repository owner (see [docs/audit.md](docs/audit.md), P0).

&nbsp;

<p align="center">
  <img src="https://raw.githubusercontent.com/catppuccin/catppuccin/main/assets/footers/gray0_ctp_on_line.svg?sanitize=true" alt=""/>
</p>

<p align="center">
  Copyright © 2026 <a href="https://github.com/h3n-x">h3n-x</a>
</p>
