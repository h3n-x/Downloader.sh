"""Extraction port. Runs inside the worker process (synchronous by design)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from downloader.domain.models import MediaInfo
from downloader.worker.protocol import ProgressEvent, WorkerLimits


@dataclass(frozen=True, slots=True)
class ExtractionContext:
    proxy_url: str
    providers: tuple[str, ...]
    limits: WorkerLimits


@dataclass(frozen=True, slots=True)
class DownloadedFile:
    path: Path
    ext: str
    size: int
    title: str


type ProgressCallback = Callable[[ProgressEvent], None]
type InfoCallback = Callable[[MediaInfo], None]


class MediaExtractor(Protocol):
    def inspect(self, url: str, ctx: ExtractionContext) -> MediaInfo: ...

    def download(
        self,
        url: str,
        option_id: str,
        workdir: Path,
        ctx: ExtractionContext,
        *,
        on_info: InfoCallback,
        on_progress: ProgressCallback,
    ) -> DownloadedFile: ...
