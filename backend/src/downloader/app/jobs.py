"""Download jobs: bounded queue, per-client limits, progress fan-out, TTL cleanup.

State is in memory (single node, see ADR 0003). A job id is a 128-bit random token
and acts as a capability: knowing it is the only way to read progress or the file.
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import logging
import secrets
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from pydantic import BaseModel, ConfigDict

from downloader.app.inspect import InspectService, url_fingerprint
from downloader.app.ports import MediaBackend
from downloader.domain.errors import AppError, ErrorCode
from downloader.domain.quality import OPTION_ID_RE
from downloader.infra.storage import JobStorage
from downloader.worker.protocol import DoneEvent, InfoEvent, Phase, ProgressEvent, WorkerEvent

log = logging.getLogger(__name__)

TERMINAL: Final = frozenset({Phase.FAILED, Phase.CANCELLED, Phase.EXPIRED})
ACTIVE: Final = frozenset({Phase.QUEUED, Phase.PREPARING, Phase.DOWNLOADING, Phase.PROCESSING})
_RETENTION_AFTER_END_S: Final = 10 * 60


class ProgressView(BaseModel):
    model_config = ConfigDict(frozen=True)

    downloaded: int | None = None
    total: int | None = None
    total_is_estimate: bool = False
    speed: float | None = None
    eta: float | None = None


class JobView(BaseModel):
    """Public snapshot of a job (safe to send to its owner)."""

    model_config = ConfigDict(frozen=True)

    id: str
    phase: Phase
    provider: str
    title: str | None = None
    progress: ProgressView | None = None
    error_code: ErrorCode | None = None
    file_ext: str | None = None
    file_size: int | None = None
    expires_at: dt.datetime | None = None
    version: int


@dataclass(eq=False)
class Job:
    id: str
    client_key: str
    url: str
    provider: str
    option_id: str
    phase: Phase = Phase.QUEUED
    title: str | None = None
    progress: ProgressView | None = None
    error_code: ErrorCode | None = None
    workdir: Path | None = None
    file: DoneEvent | None = None
    expires_at: float | None = None  # wall clock (time.time)
    ended_at: float | None = None
    duration: float | None = None
    version: int = 0
    task: asyncio.Task[None] | None = None
    _changed: asyncio.Event = field(default_factory=asyncio.Event)

    def bump(self) -> None:
        self.version += 1
        self._changed.set()
        self._changed = asyncio.Event()

    async def wait_changed(self, since: int, max_wait: float) -> None:
        if self.version != since:
            return
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._changed.wait(), max_wait)

    def view(self) -> JobView:
        return JobView(
            id=self.id,
            phase=self.phase,
            provider=self.provider,
            title=self.title,
            progress=self.progress,
            error_code=self.error_code,
            file_ext=self.file.ext if self.file else None,
            file_size=self.file.size if self.file else None,
            expires_at=(
                dt.datetime.fromtimestamp(self.expires_at, tz=dt.UTC) if self.expires_at else None
            ),
            version=self.version,
        )


@dataclass(frozen=True, slots=True)
class JobLimits:
    max_concurrent: int
    max_queued: int
    max_per_client: int
    disk_quota: int
    time_limit: float
    ttl: float


class JobManager:
    def __init__(
        self,
        backend: MediaBackend,
        inspector: InspectService,
        storage: JobStorage,
        limits: JobLimits,
        *,
        on_finish: Callable[[Job], None] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._backend = backend
        self._inspector = inspector
        self._storage = storage
        self._limits = limits
        self._sem = asyncio.Semaphore(limits.max_concurrent)
        self._jobs: dict[str, Job] = {}
        self._on_finish = on_finish
        self._clock = clock

    # --- queries -------------------------------------------------------------

    def get(self, job_id: str) -> Job:
        job = self._jobs.get(job_id)
        if job is None:
            raise AppError(ErrorCode.JOB_NOT_FOUND)
        return job

    def count(self, phases: frozenset[Phase]) -> int:
        return sum(1 for j in self._jobs.values() if j.phase in phases)

    def counts_by_phase(self) -> dict[Phase, int]:
        out = dict.fromkeys(Phase, 0)
        for j in self._jobs.values():
            out[j.phase] += 1
        return out

    def ready_file(self, job_id: str) -> tuple[Job, Path]:
        job = self.get(job_id)
        if job.phase is Phase.EXPIRED:
            raise AppError(ErrorCode.JOB_EXPIRED)
        if job.phase is not Phase.READY or job.file is None or job.workdir is None:
            raise AppError(ErrorCode.JOB_NOT_READY)
        path = job.workdir / job.file.filename
        if path.is_symlink() or not path.is_file():
            raise AppError(ErrorCode.JOB_EXPIRED)
        return job, path

    # --- commands ------------------------------------------------------------

    def submit(self, raw_url: str, option_id: str, client_key: str) -> Job:
        if not OPTION_ID_RE.match(option_id):
            raise AppError(ErrorCode.VALIDATION_ERROR, detail="bad option id")
        url, provider = self._inspector.resolve_provider(raw_url)
        active = [j for j in self._jobs.values() if j.phase in ACTIVE]
        if sum(1 for j in active if j.client_key == client_key) >= self._limits.max_per_client:
            raise AppError(ErrorCode.RATE_LIMITED, detail="per-client active jobs", retry_after=30)
        if len(active) >= self._limits.max_concurrent + self._limits.max_queued:
            raise AppError(ErrorCode.SERVER_BUSY, retry_after=30)
        if self._storage.usage_bytes() >= self._limits.disk_quota:
            raise AppError(ErrorCode.SERVER_BUSY, detail="disk quota", retry_after=60)
        job = Job(
            id=secrets.token_urlsafe(16),
            client_key=client_key,
            url=url,
            provider=provider.slug,
            option_id=option_id,
        )
        self._jobs[job.id] = job
        job.task = asyncio.create_task(self._run(job), name=f"job-{job.id[:6]}")
        return job

    def cancel(self, job_id: str) -> None:
        job = self.get(job_id)
        if job.task is not None and not job.task.done():
            job.task.cancel()
        elif job.phase is Phase.READY:
            self._expire(job)

    async def watch(self, job_id: str, heartbeat: float = 15.0) -> AsyncIterator[JobView | None]:
        """Yield a snapshot on every change; ``None`` as a keep-alive tick."""
        job = self.get(job_id)
        seen = -1
        while True:
            if job.version != seen:
                seen = job.version
                yield job.view()
                if job.phase in TERMINAL or job.phase is Phase.READY:
                    return
            else:
                yield None
            await job.wait_changed(seen, heartbeat)

    # --- lifecycle -----------------------------------------------------------

    async def _run(self, job: Job) -> None:
        started = time.monotonic()
        try:
            async with self._sem:
                self._set(job, Phase.PREPARING)
                job.workdir = self._storage.create(job.id[:8])
                done = await self._backend.download(
                    job.url,
                    job.option_id,
                    job.workdir,
                    lambda event: self._on_event(job, event),
                    self._limits.time_limit,
                )
            job.file = done
            job.title = job.title or done.title
            job.expires_at = self._clock() + self._limits.ttl
            self._set(job, Phase.READY)
        except asyncio.CancelledError:
            self._fail(job, Phase.CANCELLED, None)
        except AppError as exc:
            log.info(
                "download failed",
                extra={
                    "code": exc.code.value,
                    "provider": job.provider,
                    "url_fp": url_fingerprint(job.url),
                },
            )
            self._fail(job, Phase.FAILED, exc.code)
        except Exception:
            log.exception("download crashed", extra={"provider": job.provider})
            self._fail(job, Phase.FAILED, ErrorCode.INTERNAL_ERROR)
        finally:
            job.duration = time.monotonic() - started
            if self._on_finish is not None:
                self._on_finish(job)

    def _on_event(self, job: Job, event: WorkerEvent) -> None:
        if isinstance(event, InfoEvent):
            job.title = event.info.title
            job.bump()
        elif isinstance(event, ProgressEvent):
            if event.phase is Phase.DOWNLOADING:
                job.progress = ProgressView(
                    downloaded=event.downloaded,
                    total=event.total,
                    total_is_estimate=event.total_is_estimate,
                    speed=event.speed,
                    eta=event.eta,
                )
            self._set(job, event.phase)

    def _set(self, job: Job, phase: Phase) -> None:
        job.phase = phase
        job.bump()

    def _fail(self, job: Job, phase: Phase, code: ErrorCode | None) -> None:
        job.error_code = code
        job.ended_at = self._clock()
        if job.workdir is not None:
            self._storage.remove(job.workdir)
        self._set(job, phase)

    def _expire(self, job: Job) -> None:
        if job.workdir is not None:
            self._storage.remove(job.workdir)
        job.ended_at = self._clock()
        self._set(job, Phase.EXPIRED)

    def reap(self) -> None:
        """Expire ready files past TTL, forget old jobs, sweep orphan directories."""
        now = self._clock()
        for job in list(self._jobs.values()):
            if job.phase is Phase.READY and job.expires_at is not None and now >= job.expires_at:
                self._expire(job)
            if job.ended_at is not None and now - job.ended_at > _RETENTION_AFTER_END_S:
                del self._jobs[job.id]
        active_dirs = {
            j.workdir for j in self._jobs.values() if j.workdir and j.phase not in TERMINAL
        }
        self._storage.sweep(active_dirs, max_age=self._limits.time_limit + self._limits.ttl)

    async def run_reaper(self, interval: float = 30.0) -> None:
        while True:
            await asyncio.sleep(interval)
            try:
                self.reap()
            except Exception:
                log.exception("reaper failed")

    async def shutdown(self) -> None:
        tasks = [j.task for j in self._jobs.values() if j.task and not j.task.done()]
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for job in self._jobs.values():
            if job.workdir is not None:
                self._storage.remove(job.workdir)
