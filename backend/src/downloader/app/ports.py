"""Application ports. The API layer depends on these, never on infrastructure."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from downloader.domain.models import MediaInfo
from downloader.worker.protocol import DoneEvent, WorkerEvent


class MediaBackend(Protocol):
    async def inspect(self, url: str, time_limit: float) -> MediaInfo: ...

    async def download(
        self,
        url: str,
        option_id: str,
        workdir: Path,
        sink: Callable[[WorkerEvent], None],
        time_limit: float,
    ) -> DoneEvent: ...
