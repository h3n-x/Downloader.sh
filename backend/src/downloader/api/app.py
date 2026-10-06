"""Application factory: wires settings, infrastructure and routes."""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import json
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

from downloader import __version__
from downloader.api import errors
from downloader.api.middleware import RequestContextMiddleware, build_csp
from downloader.api.ratelimit import TokenBuckets
from downloader.api.routes import Services, router
from downloader.app.inspect import InspectService
from downloader.app.jobs import Job, JobLimits, JobManager
from downloader.app.ports import MediaBackend
from downloader.config import Settings
from downloader.domain.errors import AppError, ErrorCode
from downloader.domain.providers import PROVIDERS, ProviderRegistry
from downloader.domain.quality import Limits
from downloader.infra.egress_proxy import EgressProxy
from downloader.infra.storage import JobStorage
from downloader.infra.worker_launcher import WorkerRunner
from downloader.observability import Metrics
from downloader.worker.protocol import Phase, WorkerLimits


class CachedStaticFiles(StaticFiles):
    """Serves Astro's ``format: "file"`` output (``/terminos`` → ``terminos.html``).

    Hashed build assets are immutable; HTML must always revalidate. ``api/`` paths are
    never served from here so unknown API routes keep the JSON error envelope.
    """

    async def get_response(self, path: str, scope: Scope) -> Response:
        if path == "api" or path.startswith("api/"):
            raise StarletteHTTPException(404)
        response = await self._lookup(path, scope)
        if response is None and path and "." not in path.rsplit("/", 1)[-1]:
            response = await self._lookup(f"{path}.html", scope)
        if response is None:
            response = await super().get_response(path, scope)  # 404.html or HTTP 404
        if path.startswith("_astro/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            response.headers.setdefault("Cache-Control", "no-cache")
        return response

    async def _lookup(self, path: str, scope: Scope) -> Response | None:
        """Return the file response, or None when the path does not exist."""
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404:
                raise
            return None
        return None if response.status_code == 404 else response


def _job_metrics(metrics: Metrics) -> Callable[[Job], None]:
    def record(job: Job) -> None:
        outcome = job.error_code.value if job.error_code else job.phase.value
        metrics.downloads.labels(job.provider, outcome).inc()
        if job.phase is Phase.READY:
            if job.duration is not None:
                metrics.download_seconds.labels(job.provider).observe(job.duration)
            if job.file is not None:
                metrics.download_bytes.inc(job.file.size)

    return record


def _csp(static_dir: Path | None) -> str:
    """Include hashes of the inline blocks the frontend build emitted (see csp-hashes.mjs)."""
    if static_dir is None or not (static_dir / "csp-hashes.json").is_file():
        return build_csp()
    data = json.loads((static_dir / "csp-hashes.json").read_text(encoding="utf-8"))
    return build_csp(tuple(data.get("script", ())), tuple(data.get("style", ())))


def create_app(settings: Settings | None = None, backend: MediaBackend | None = None) -> FastAPI:
    settings = settings or Settings()
    metrics = Metrics()
    proxy: EgressProxy | None = None
    if backend is None:
        proxy = EgressProxy(on_denial=lambda d: metrics.egress_denied.labels(d.value).inc())
        backend = WorkerRunner(
            proxy,
            providers=tuple(sorted(settings.providers)),
            limits=WorkerLimits(
                max_filesize=settings.max_filesize, max_duration=settings.max_duration
            ),
            scratch_dir=settings.data_dir / "scratch",
            cpu_seconds=settings.worker_cpu_seconds,
            log_stderr=settings.log_worker_stderr,
        )
    storage = JobStorage(settings.jobs_dir)
    inspector = InspectService(
        backend,
        ProviderRegistry(PROVIDERS, settings.providers),
        limits=Limits(settings.max_filesize, settings.max_duration),
        time_limit=settings.inspect_timeout,
        max_concurrent=settings.max_concurrent_inspects,
        cache_ttl=settings.inspect_cache_ttl,
    )
    jobs = JobManager(
        backend,
        inspector,
        storage,
        JobLimits(
            max_concurrent=settings.max_concurrent_downloads,
            max_queued=settings.max_queued_downloads,
            max_per_client=settings.max_active_downloads_per_client,
            disk_quota=settings.disk_quota,
            time_limit=settings.download_timeout,
            ttl=settings.download_ttl,
        ),
        on_finish=_job_metrics(metrics),
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        storage.prepare()
        (settings.data_dir / "scratch").mkdir(mode=0o700, parents=True, exist_ok=True)
        storage.sweep(set(), max_age=0)  # nothing from a previous process is reachable
        if proxy is not None:
            await proxy.start()
        reaper = asyncio.create_task(jobs.run_reaper(), name="reaper")
        try:
            yield
        finally:
            reaper.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await reaper
            await jobs.shutdown()
            if proxy is not None:
                await proxy.close()

    app = FastAPI(
        title="Downloader.sh API",
        version=__version__,
        lifespan=lifespan,
        docs_url=None if settings.is_production else "/api/docs",
        redoc_url=None,
        openapi_url="/api/v1/openapi.json",
    )
    app.state.services = Services(
        settings=settings,
        inspector=inspector,
        jobs=jobs,
        metrics=metrics,
        proxy=proxy,
        inspect_limiter=TokenBuckets("inspect", settings.inspect_per_minute),
        download_limiter=TokenBuckets("downloads", settings.downloads_per_minute),
    )
    errors.install(app)
    app.include_router(router)

    if settings.metrics_enabled:

        @app.get("/metrics", include_in_schema=False)
        async def prometheus(request: Request) -> Response:
            token = settings.metrics_token
            if token is not None:
                given = request.headers.get("authorization", "")
                if not hmac.compare_digest(given, f"Bearer {token.get_secret_value()}"):
                    raise AppError(ErrorCode.NOT_FOUND)
            for phase, count in jobs.counts_by_phase().items():
                metrics.jobs.labels(phase.value).set(count)
            return Response(generate_latest(metrics.registry), media_type=CONTENT_TYPE_LATEST)

    static_dir: Path | None = settings.static_dir
    if static_dir is not None and static_dir.is_dir():
        app.mount("/", CachedStaticFiles(directory=static_dir, html=True), name="static")

    app.add_middleware(
        RequestContextMiddleware, metrics=metrics, hsts=settings.hsts, csp=_csp(static_dir)
    )
    return app
