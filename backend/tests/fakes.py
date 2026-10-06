"""In-memory MediaBackend for app/API tests (no processes, no network)."""

import asyncio
from collections.abc import Callable
from pathlib import Path

from downloader.domain.errors import AppError, ErrorCode
from downloader.domain.models import MediaFormat, MediaInfo, StreamKind, Thumbnail
from downloader.worker.protocol import DoneEvent, InfoEvent, Phase, ProgressEvent, WorkerEvent

SAMPLE_INFO = MediaInfo(
    id="abc123",
    provider="youtube",
    title="Sample <b>title</b>",
    uploader="Uploader",
    duration=120,
    thumbnail=Thumbnail(url="https://i.ytimg.com/vi/abc123/hq.jpg", width=480, height=360),
    webpage_url="https://www.youtube.com/watch?v=abc123",
    formats=(
        MediaFormat(format_id="140", ext="m4a", kind=StreamKind.AUDIO_ONLY, acodec="mp4a.40.2",
                    abr=128, filesize=2_000_000),
        MediaFormat(format_id="137", ext="mp4", kind=StreamKind.VIDEO_ONLY, vcodec="avc1.640028",
                    width=1920, height=1080, fps=30, tbr=4000, filesize=60_000_000),
        MediaFormat(format_id="136", ext="mp4", kind=StreamKind.VIDEO_ONLY, vcodec="avc1.4d401f",
                    width=1280, height=720, fps=30, tbr=2000, filesize=30_000_000),
    ),
)  # fmt: skip


class FakeBackend:
    def __init__(self) -> None:
        self.inspect_calls = 0
        self.inspect_error: AppError | None = None
        self.inspect_gate: asyncio.Event | None = None
        self.download_error: AppError | None = None
        self.download_gate: asyncio.Event | None = None
        self.payload = b"\x00\x00\x00\x18ftypmp42" + b"x" * 1000

    async def inspect(self, url: str, time_limit: float) -> MediaInfo:
        self.inspect_calls += 1
        if self.inspect_gate is not None:
            await self.inspect_gate.wait()
        if self.inspect_error is not None:
            raise self.inspect_error
        return SAMPLE_INFO

    async def download(
        self,
        url: str,
        option_id: str,
        workdir: Path,
        sink: Callable[[WorkerEvent], None],
        time_limit: float,
    ) -> DoneEvent:
        sink(InfoEvent(info=SAMPLE_INFO))
        sink(ProgressEvent(phase=Phase.DOWNLOADING, downloaded=10, total=100))
        if self.download_gate is not None:
            await self.download_gate.wait()
        if self.download_error is not None:
            raise self.download_error
        if option_id == "v4320":
            raise AppError(ErrorCode.FORMAT_UNAVAILABLE)
        sink(ProgressEvent(phase=Phase.PROCESSING))
        (workdir / "media.mp4").write_bytes(self.payload)
        return DoneEvent(
            filename="media.mp4", ext="mp4", size=len(self.payload), title=SAMPLE_INFO.title
        )
