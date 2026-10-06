# syntax=docker/dockerfile:1.7
# Multi-stage build: static frontend → Python venv → slim non-root runtime.

ARG PYTHON_IMAGE=python:3.13-slim
ARG NODE_IMAGE=node:22-slim
ARG UV_VERSION=0.11.32

# --- 1. Frontend ---------------------------------------------------------------
FROM ${NODE_IMAGE} AS frontend
ENV ASTRO_TELEMETRY_DISABLED=1 PNPM_HOME=/pnpm
WORKDIR /src/frontend
RUN corepack enable
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN --mount=type=cache,target=/pnpm/store pnpm install --frozen-lockfile
COPY backend/openapi.json /src/backend/openapi.json
COPY frontend/ ./
RUN pnpm build

# --- 2. Python dependencies ----------------------------------------------------
FROM ${PYTHON_IMAGE} AS backend
ARG UV_VERSION
RUN pip install --no-cache-dir "uv==${UV_VERSION}"
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /src/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-install-project
COPY backend/src ./src
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-editable

# --- 3. Runtime ----------------------------------------------------------------
FROM ${PYTHON_IMAGE} AS runtime
# ffmpeg: remux/merge/extract-audio of local files only. tini: PID 1 that reaps
# grandchildren (ffmpeg/deno) if a worker dies.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg tini ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --system --uid 10001 --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin app \
 && install -d -o app -g app -m 0700 /data
COPY --from=backend /app/.venv /app/.venv
COPY --from=frontend /src/frontend/dist /app/static
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DL_STATIC_DIR=/app/static \
    DL_DATA_DIR=/data \
    DL_HOST=0.0.0.0 \
    DL_PORT=8000
USER app
WORKDIR /data
EXPOSE 8000
STOPSIGNAL SIGTERM
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=2).status != 200)"]
ENTRYPOINT ["tini", "--"]
CMD ["downloader"]
