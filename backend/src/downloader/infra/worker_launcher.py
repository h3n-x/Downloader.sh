"""Spawn isolated worker processes and translate their JSONL events.

No shell is ever involved: ``create_subprocess_exec`` with a fixed argv. The child
gets a minimal environment (no API secrets), its own session (so the whole process
group — including FFmpeg/Deno children — can be killed) and a per-job proxy lease.

Classification precedence on failure (most authoritative first):
proxy denial → proxy byte budget → kernel signal (SIGXFSZ/SIGXCPU) → worker error event.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import shutil
import signal
import sys
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Final

from pydantic import ValidationError

from downloader.domain.errors import AppError, ErrorCode
from downloader.domain.models import MediaInfo
from downloader.infra.egress_proxy import EgressProxy, Lease
from downloader.worker.protocol import (
    EVENT_ADAPTER,
    DoneEvent,
    DownloadRequest,
    ErrorEvent,
    InfoEvent,
    InspectRequest,
    WorkerEvent,
    WorkerLimits,
)

log = logging.getLogger(__name__)

_STDOUT_LIMIT: Final = 8 * 1024 * 1024  # a MediaInfo line with many formats can be large
_STDERR_TAIL: Final = 40
_TERM_GRACE_S: Final = 3.0
INSPECT_BYTE_BUDGET: Final = 64 * 1024 * 1024
# Manifests, pages and container overhead on top of the media itself.
_DOWNLOAD_OVERHEAD: Final = 64 * 1024 * 1024

type EventSink = Callable[[WorkerEvent], None]


def _child_env(home: Path, cpu_seconds: int) -> dict[str, str]:
    bin_dir = str(Path(sys.executable).parent)
    return {
        "PATH": os.pathsep.join([bin_dir, "/usr/local/bin", "/usr/bin", "/bin"]),
        "HOME": str(home),
        "TMPDIR": str(home),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "NO_COLOR": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
        "WORKER_CPU_SECONDS": str(cpu_seconds),
    }


class WorkerRunner:
    def __init__(
        self,
        proxy: EgressProxy,
        *,
        providers: tuple[str, ...],
        limits: WorkerLimits,
        scratch_dir: Path,
        cpu_seconds: int = 900,
        log_stderr: bool = False,
    ) -> None:
        self._proxy = proxy
        self._providers = providers
        self._limits = limits
        self._scratch = scratch_dir
        self._cpu_seconds = cpu_seconds
        self._log_stderr = log_stderr

    async def inspect(self, url: str, time_limit: float) -> MediaInfo:
        lease = self._proxy.issue(INSPECT_BYTE_BUDGET)
        request = InspectRequest(
            url=url,
            providers=self._providers,
            proxy_url=self._proxy.url_for(lease),
            limits=self._limits,
        )
        result: list[MediaInfo] = []

        def sink(event: WorkerEvent) -> None:
            if isinstance(event, InfoEvent):
                result.append(event.info)

        home = self._scratch / f"inspect-{lease.token[:12]}"
        home.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            await self._run(request, lease, sink, time_limit, cwd=home)
        finally:
            shutil.rmtree(home, ignore_errors=True)
        if not result:
            raise AppError(ErrorCode.INTERNAL_ERROR, detail="worker produced no info")
        return result[0]

    async def download(
        self, url: str, option_id: str, workdir: Path, sink: EventSink, time_limit: float
    ) -> DoneEvent:
        lease = self._proxy.issue(int(self._limits.max_filesize * 1.25) + _DOWNLOAD_OVERHEAD)
        request = DownloadRequest(
            url=url,
            option_id=option_id,
            workdir=str(workdir),
            providers=self._providers,
            proxy_url=self._proxy.url_for(lease),
            limits=self._limits,
        )
        done: list[DoneEvent] = []

        def wrapped(event: WorkerEvent) -> None:
            if isinstance(event, DoneEvent):
                done.append(event)
            sink(event)

        await self._run(request, lease, wrapped, time_limit, cwd=workdir)
        if not done:
            raise AppError(ErrorCode.INTERNAL_ERROR, detail="worker produced no file")
        return done[0]

    async def _run(
        self,
        request: InspectRequest | DownloadRequest,
        lease: Lease,
        sink: EventSink,
        time_limit: float,
        *,
        cwd: Path,
    ) -> None:
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-I",
            "-m",
            "downloader.worker",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=_child_env(cwd, self._cpu_seconds),
            start_new_session=True,
            limit=_STDOUT_LIMIT,
        )
        assert proc.stdin is not None  # noqa: S101 - guaranteed by PIPE
        assert proc.stdout is not None  # noqa: S101
        assert proc.stderr is not None  # noqa: S101
        stderr_tail: deque[str] = deque(maxlen=_STDERR_TAIL)
        error: list[ErrorEvent] = []

        async def read_stdout(stream: asyncio.StreamReader) -> None:
            async for line in stream:
                try:
                    event = EVENT_ADAPTER.validate_json(line)
                except ValidationError:
                    log.warning("worker emitted an invalid protocol line")
                    continue
                if isinstance(event, ErrorEvent):
                    error.append(event)
                else:
                    sink(event)

        async def read_stderr(stream: asyncio.StreamReader) -> None:
            async for line in stream:
                stderr_tail.append(line.decode("utf-8", "replace").rstrip()[:500])

        try:
            proc.stdin.write(request.model_dump_json().encode())
            await proc.stdin.drain()
            proc.stdin.close()
            async with asyncio.timeout(time_limit):
                await asyncio.gather(read_stdout(proc.stdout), read_stderr(proc.stderr))
                returncode = await proc.wait()
        except TimeoutError:
            await self._kill(proc)
            raise AppError(ErrorCode.TIMEOUT, detail="worker timeout") from None
        except BaseException:
            await self._kill(proc)
            raise
        finally:
            self._proxy.revoke(lease)

        failure = self._classify(lease, returncode, error)
        if failure is not None:
            if self._log_stderr and failure.code in {
                ErrorCode.INTERNAL_ERROR,
                ErrorCode.EXTRACTOR_FAILED,
            }:
                log.warning("worker failed", extra={"stderr_tail": list(stderr_tail)})
            raise failure

    @staticmethod
    def _classify(  # noqa: PLR0911 - ordered precedence table, see module docstring
        lease: Lease, returncode: int, error: list[ErrorEvent]
    ) -> AppError | None:
        if returncode == 0 and not error:
            return None
        if lease.blocked:
            return AppError(ErrorCode.URL_NOT_ALLOWED, detail="egress denied by policy")
        if lease.exceeded or returncode == -signal.SIGXFSZ:
            return AppError(ErrorCode.TOO_LARGE, detail="byte budget exceeded")
        if returncode == -signal.SIGXCPU:
            return AppError(ErrorCode.TIMEOUT, detail="worker CPU limit")
        if returncode == -signal.SIGKILL:  # usually the cgroup OOM killer
            return AppError(ErrorCode.INTERNAL_ERROR, detail="worker killed (memory limit?)")
        if error:
            return AppError(error[0].code, detail=error[0].detail or None)
        return AppError(ErrorCode.INTERNAL_ERROR, detail=f"worker exited {returncode}")

    @staticmethod
    async def _kill(proc: asyncio.subprocess.Process) -> None:
        if proc.returncode is not None:
            return
        with contextlib.suppress(ProcessLookupError):
            os.killpg(proc.pid, signal.SIGTERM)
        try:
            await asyncio.wait_for(proc.wait(), _TERM_GRACE_S)
        except TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(proc.pid, signal.SIGKILL)
            await proc.wait()
