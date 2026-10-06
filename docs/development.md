# Desarrollo

## Requisitos

Python 3.13 + uv ≥ 0.11, Node ≥ 22.12 + pnpm 10, FFmpeg en el `PATH`. Deno se instala
como dependencia Python (`deno` en PyPI); no hace falta instalarlo aparte.

```bash
cd backend && uv sync                       # crea .venv con dependencias de desarrollo
cd ../frontend && pnpm install
npx lefthook install                        # hooks opcionales (rápidos en commit)
```

## Ejecutar

```bash
# Terminal 1 — API en :8000 (sirve /api/docs en desarrollo)
cd backend && DL_ENVIRONMENT=development uv run python -m downloader
# Terminal 2 — frontend en :4321 con proxy de /api
cd frontend && pnpm dev
```

## Tooling

| Área | Herramienta | Comando |
|---|---|---|
| Python lint/format | ruff 0.16 | `uv run ruff format . && uv run ruff check .` |
| Python tipos | mypy 2.4 `--strict` | `uv run mypy src tests` |
| Python tests | pytest 9 + hypothesis | `uv run pytest -q` |
| Auditoría deps | pip-audit / pnpm audit | `uv run pip-audit --skip-editable`, `pnpm audit` |
| TS/Svelte lint+format | Biome 2.5 | `pnpm lint` / `pnpm exec biome ci .` |
| Tipos frontend | astro check + tsc (TS 6, strictest) | `pnpm check` |
| Tests frontend | Vitest 5 + Testing Library | `pnpm test` |
| E2E | Playwright 1.63 + axe | `pnpm build && pnpm test:e2e` |

TypeScript se fija en 6.x porque `@astrojs/check`, `svelte-check` y `@astrojs/svelte`
declaran `typescript: ^5 || ^6` (TS 7 es `latest` en npm pero aún no compatible).

## Cambiar el contrato de la API

```bash
cd backend && uv run python -m downloader.api.openapi > openapi.json
cd ../frontend && pnpm gen:api && pnpm check
```

CI falla si `openapi.json` o `src/lib/api-types.ts` no están sincronizados. Un `ErrorCode`
nuevo rompe el type-check hasta traducirlo en `src/i18n/es.ts`.

## Añadir un proveedor

1. `backend/src/downloader/domain/providers.py`: `Provider(slug, nombre, dominios)`.
2. `backend/src/downloader/extraction/ytdlp.py::EXTRACTORS`: nombres de extractores de un
   solo elemento (compruébalos con `yt_dlp.extractor.gen_extractor_classes()`).
3. Regenerar el contrato (incluye `x-providers`, usado por la portada).
4. Añadir un caso a `tests/live/test_platforms.py`.

## Hooks

`lefthook.yml`: en commit, ruff y Biome solo sobre ficheros staged (segundos); en push,
mypy + tests rápidos de backend y check + Vitest del frontend.
