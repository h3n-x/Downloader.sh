"""Full-stack E2E server: real FastAPI app + built frontend, fake media engine.

Run: ``uv run python -m tests.e2e_server`` (used by frontend/playwright.config.ts).
"""

import asyncio
import os
from collections.abc import Callable
from pathlib import Path

import uvicorn

from downloader.api.app import create_app
from downloader.config import Settings
from downloader.domain.errors import AppError, ErrorCode
from downloader.domain.models import MediaInfo
from downloader.worker.protocol import DoneEvent, InfoEvent, Phase, ProgressEvent, WorkerEvent
from tests.fakes import SAMPLE_INFO, FakeBackend


class SlowFakeBackend(FakeBackend):
    """Emits realistic progress so the UI states are observable."""

    async def inspect(self, url: str, time_limit: float) -> MediaInfo:
        await asyncio.sleep(0.3)
        if "private" in url:
            raise AppError(ErrorCode.CONTENT_PRIVATE)
        return await super().inspect(url, time_limit)

    async def download(
        self,
        url: str,
        option_id: str,
        workdir: Path,
        sink: Callable[[WorkerEvent], None],
        time_limit: float,
    ) -> DoneEvent:
        sink(InfoEvent(info=SAMPLE_INFO))
        total = 1_000_000
        for step in range(1, 6):
            await asyncio.sleep(0.15)
            sink(ProgressEvent(phase=Phase.DOWNLOADING, downloaded=step * total // 5, total=total))
        sink(ProgressEvent(phase=Phase.PROCESSING))
        await asyncio.sleep(0.2)
        (workdir / "media.mp4").write_bytes(self.payload)
        return DoneEvent(
            filename="media.mp4", ext="mp4", size=len(self.payload), title=SAMPLE_INFO.title
        )


def main() -> None:
    root = Path(os.environ.get("E2E_DATA_DIR", "/tmp/downloader-e2e"))  # noqa: S108
    settings = Settings(
        environment="test",
        data_dir=root,
        static_dir=Path(os.environ["DL_STATIC_DIR"]),
        inspect_per_minute=1000,
        downloads_per_minute=1000,
    )
    app = create_app(settings, SlowFakeBackend())
    uvicorn.run(
        app, host="127.0.0.1", port=int(os.environ.get("E2E_PORT", "8799")), log_level="warning"
    )


if __name__ == "__main__":
    main()
