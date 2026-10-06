# ADR 0001 — Stack: FastAPI + Astro/Svelte

- Estado: aceptado (2026-10-06)

## Contexto

El coste dominante del sistema es ancho de banda y FFmpeg, no el control-plane HTTP. El motor de
extracción más completo (yt-dlp) es una librería Python con API estructurada. La interfaz es una
sola pantalla interactiva más unas pocas páginas estáticas.

## Decisión

- Backend: Python 3.13, FastAPI 0.142 (OpenAPI + SSE nativos), Pydantic 2, uvicorn.
- Frontend: Astro 7 en salida estática + una isla Svelte 5. TypeScript fijado a 6.x porque
  `@astrojs/check`/`svelte-check` no aceptan TS 7 (peerDependencies observadas en npm).
- Contratos: el backend publica OpenAPI; el frontend genera tipos con `openapi-typescript`.
  CI falla si el esquema commiteado no coincide con el generado.
- Tooling: uv, ruff (lint+format), mypy `--strict`, pytest + hypothesis; pnpm, Biome, Vitest,
  Playwright + axe; lefthook.

## Alternativas descartadas

Ver `docs/plan.md` §2. Go/Rust se descartan para v1 porque obligan a usar el CLI de yt-dlp y a
clasificar errores parseando texto; se reservan para un control-plane futuro si la escala lo pide.
SvelteKit 3 se reevaluará cuando madure (3.0.1 salió el 2026-10-06).

## Consecuencias

Un único contenedor sirve API y estáticos. El frontend puede moverse a una CDN sin cambios porque
es estático y consume la API por rutas relativas configurables.
