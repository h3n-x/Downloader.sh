"""Worker process entrypoint: ``python -m downloader.worker``.

Hardening applied before any third-party code runs:
- protocol on a private dup of stdout; fd 1 is redirected to stderr;
- kernel resource limits (file size, CPU time, open files, no core dumps);
- parent-death signal so a crashed API never leaves orphan workers.
Memory and process-count limits belong to the container/cgroup (RLIMIT_AS breaks V8/Deno).
"""

from __future__ import annotations

import ctypes
import os
import resource
import signal
import sys
from pathlib import Path
from typing import TextIO

from pydantic import BaseModel, ValidationError

from downloader.domain.errors import AppError, ErrorCode
from downloader.worker.protocol import (
    MAX_REQUEST_BYTES,
    REQUEST_ADAPTER,
    DoneEvent,
    DownloadRequest,
    ErrorEvent,
    InfoEvent,
    InspectRequest,
    WorkerLimits,
)

_PR_SET_PDEATHSIG = 1
CPU_SECONDS = int(os.environ.get("WORKER_CPU_SECONDS", "900"))


def _set_parent_death_signal() -> None:
    if sys.platform != "linux":
        return
    libc = ctypes.CDLL(None, use_errno=True)
    libc.prctl(_PR_SET_PDEATHSIG, signal.SIGKILL, 0, 0, 0)


def apply_rlimits(limits: WorkerLimits) -> None:
    # Merged output ≈ sum of inputs; allow headroom for container overhead.
    fsize = int(limits.max_filesize * 1.25) + 16 * 1024 * 1024
    for res, value in (
        (resource.RLIMIT_CORE, 0),
        (resource.RLIMIT_FSIZE, fsize),
        (resource.RLIMIT_CPU, CPU_SECONDS),
        (resource.RLIMIT_NOFILE, 256),
    ):
        _soft, hard = resource.getrlimit(res)
        capped = value if hard == resource.RLIM_INFINITY else min(value, hard)
        resource.setrlimit(res, (capped, capped))


class Channel:
    def __init__(self, stream: TextIO) -> None:
        self._stream = stream

    def send(self, event: BaseModel) -> None:
        self._stream.write(event.model_dump_json() + "\n")
        self._stream.flush()


def _log(msg: str) -> None:
    print(msg.replace("\n", " "), file=sys.stderr, flush=True)


def run(request: InspectRequest | DownloadRequest, channel: Channel) -> None:
    from downloader.extraction.base import ExtractionContext  # noqa: PLC0415
    from downloader.extraction.ytdlp import YtDlpExtractor  # noqa: PLC0415

    ctx = ExtractionContext(
        proxy_url=request.proxy_url, providers=request.providers, limits=request.limits
    )
    extractor = YtDlpExtractor(log=_log)
    if isinstance(request, InspectRequest):
        channel.send(InfoEvent(info=extractor.inspect(request.url, ctx)))
        return
    workdir = Path(request.workdir)
    os.chdir(workdir)
    result = extractor.download(
        request.url,
        request.option_id,
        workdir,
        ctx,
        on_info=lambda info: channel.send(InfoEvent(info=info)),
        on_progress=channel.send,
    )
    channel.send(
        DoneEvent(filename=result.path.name, ext=result.ext, size=result.size, title=result.title)
    )


def main() -> int:
    channel = Channel(os.fdopen(os.dup(1), "w", encoding="utf-8"))
    os.dup2(2, 1)
    _set_parent_death_signal()
    try:
        request = REQUEST_ADAPTER.validate_json(sys.stdin.buffer.read(MAX_REQUEST_BYTES))
    except ValidationError:
        channel.send(ErrorEvent(code=ErrorCode.INTERNAL_ERROR, detail="bad worker request"))
        return 2
    apply_rlimits(request.limits)
    try:
        run(request, channel)
    except AppError as exc:
        channel.send(ErrorEvent(code=exc.code, detail=exc.detail or ""))
        return 1
    except Exception as exc:  # noqa: BLE001 - last-resort boundary of an isolated process
        channel.send(ErrorEvent(code=ErrorCode.INTERNAL_ERROR, detail=type(exc).__name__))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
