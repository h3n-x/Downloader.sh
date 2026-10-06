"""HTTP routes (`/api/v1`)."""

from __future__ import annotations

import shutil
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated, Final

from fastapi import APIRouter, Depends, Path, Request, Response
from fastapi.responses import FileResponse
from fastapi.sse import EventSourceResponse, ServerSentEvent

from downloader import __version__
from downloader.api.ratelimit import TokenBuckets, client_key
from downloader.api.schemas import (
    DownloadBody,
    ErrorOut,
    HealthOut,
    InspectBody,
    InspectOut,
    JobOut,
    LimitsOut,
    MediaOut,
    MetaOut,
    ProviderOut,
    ReadyOut,
)
from downloader.app.inspect import InspectService
from downloader.app.jobs import Job, JobManager, JobView
from downloader.config import Settings
from downloader.domain.errors import AppError
from downloader.infra.egress_proxy import EgressProxy
from downloader.observability import Metrics
from downloader.security.filenames import content_disposition, safe_extension

JOB_ID_PATTERN: Final = r"^[A-Za-z0-9_-]{22}$"
_MEDIA_TYPES: Final = {
    "mp4": "video/mp4",
    "webm": "video/webm",
    "mkv": "video/x-matroska",
    "mov": "video/quicktime",
    "m4a": "audio/mp4",
    "mp3": "audio/mpeg",
    "opus": "audio/ogg",
    "ogg": "audio/ogg",
    "aac": "audio/aac",
    "flac": "audio/flac",
    "wav": "audio/wav",
}
_ERRORS: Final = {
    code: {"model": ErrorOut}
    for code in (400, 404, 409, 410, 413, 422, 429, 451, 500, 502, 503, 504)
}


@dataclass(frozen=True, slots=True)
class Services:
    settings: Settings
    inspector: InspectService
    jobs: JobManager
    metrics: Metrics
    proxy: EgressProxy | None
    inspect_limiter: TokenBuckets
    download_limiter: TokenBuckets


def get_services(request: Request) -> Services:
    services: Services = request.app.state.services
    return services


Svc = Annotated[Services, Depends(get_services)]
JobId = Annotated[str, Path(pattern=JOB_ID_PATTERN)]

router = APIRouter(prefix="/api/v1", responses=_ERRORS)  # type: ignore[arg-type]


def _client(request: Request, svc: Services) -> str:
    host = request.client.host if request.client else None
    return client_key(host, svc.settings.client_key_secret.get_secret_value().encode())


def _limit(bucket: TokenBuckets, key: str, svc: Services) -> None:
    try:
        bucket.hit(key)
    except AppError:
        svc.metrics.rate_limited.labels(bucket.name).inc()
        raise


def _job_out(view: JobView) -> JobOut:
    base = f"/api/v1/downloads/{view.id}"
    return JobOut(
        **view.model_dump(),
        events_url=f"{base}/events",
        file_url=f"{base}/file" if view.phase == "ready" else None,
    )


def _limits(settings: Settings) -> LimitsOut:
    return LimitsOut(max_filesize=settings.max_filesize, max_duration=settings.max_duration)


@router.get("/meta")
async def meta(svc: Svc) -> MetaOut:
    return MetaOut(
        version=__version__,
        providers=[ProviderOut(slug=p.slug, name=p.name) for p in svc.inspector.registry.providers],
        limits=_limits(svc.settings),
    )


@router.post("/inspect")
async def inspect(body: InspectBody, request: Request, svc: Svc) -> InspectOut:
    _limit(svc.inspect_limiter, _client(request, svc), svc)
    try:
        result = await svc.inspector.inspect(body.url)
    except AppError as exc:
        svc.metrics.inspections.labels("-", exc.code.value).inc()
        raise
    svc.metrics.inspections.labels(result.provider.slug, "ok").inc()
    media = result.media
    return InspectOut(
        media=MediaOut(
            id=media.id,
            title=media.title,
            uploader=media.uploader,
            duration=media.duration,
            upload_date=media.upload_date,
            thumbnail=media.thumbnail,
            webpage_url=media.webpage_url,
            provider=ProviderOut(slug=result.provider.slug, name=result.provider.name),
        ),
        options=result.options,
        formats=list(media.formats),
        limits=_limits(svc.settings),
    )


@router.post("/downloads", status_code=202)
async def create_download(
    body: DownloadBody, request: Request, response: Response, svc: Svc
) -> JobOut:
    key = _client(request, svc)
    _limit(svc.download_limiter, key, svc)
    job = svc.jobs.submit(body.url, body.option_id, key)
    response.headers["Location"] = f"/api/v1/downloads/{job.id}"
    return _job_out(job.view())


def existing_job(job_id: JobId, svc: Svc) -> Job:
    """Resolved before any SSE bytes are sent, so unknown ids still get a 404."""
    return svc.jobs.get(job_id)


@router.get("/downloads/{job_id}")
async def get_download(job: Annotated[Job, Depends(existing_job)]) -> JobOut:
    return _job_out(job.view())


@router.get("/downloads/{job_id}/events", response_class=EventSourceResponse)
async def download_events(
    job: Annotated[Job, Depends(existing_job)], svc: Svc
) -> AsyncIterator[ServerSentEvent]:
    async for view in svc.jobs.watch(job.id):
        if view is not None:
            yield ServerSentEvent(
                event="job", data=_job_out(view).model_dump(mode="json"), id=str(view.version)
            )


@router.get(
    "/downloads/{job_id}/file",
    response_class=FileResponse,
    responses={200: {"content": {"application/octet-stream": {}}}},
)
async def download_file(job_id: JobId, svc: Svc) -> FileResponse:
    job, path = svc.jobs.ready_file(job_id)
    ext = safe_extension(path.suffix) or "bin"
    return FileResponse(
        path,
        media_type=_MEDIA_TYPES.get(ext, "application/octet-stream"),
        headers={
            "Content-Disposition": content_disposition(job.title or "download", ext),
            "Cache-Control": "private, no-store",
        },
    )


@router.delete("/downloads/{job_id}", status_code=204)
async def delete_download(job_id: JobId, svc: Svc) -> Response:
    svc.jobs.cancel(job_id)
    return Response(status_code=204)


@router.get("/health")
async def health() -> HealthOut:
    return HealthOut(version=__version__)


@router.get("/ready")
async def ready(svc: Svc, response: Response) -> ReadyOut:
    data_dir = svc.settings.data_dir
    checks = {
        "ffmpeg": shutil.which("ffmpeg") is not None,
        "deno": shutil.which("deno") is not None,
        "egress_proxy": svc.proxy is None or svc.proxy.running,
        "storage": data_dir.is_dir() and shutil.disk_usage(data_dir).free > 1024**3,
    }
    ok = all(checks.values())
    response.status_code = 200 if ok else 503
    return ReadyOut(status="ready" if ok else "degraded", checks=checks)
