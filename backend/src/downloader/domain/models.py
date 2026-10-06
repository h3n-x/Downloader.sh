"""Engine-agnostic media models. Nothing here knows about yt-dlp.

Direct media/CDN URLs are deliberately absent: they are ephemeral, often bound to
the server's IP, and must never be cached or sent to clients.
"""

from __future__ import annotations

import datetime as dt
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class StreamKind(StrEnum):
    AUDIO_VIDEO = "audio_video"
    VIDEO_ONLY = "video_only"
    AUDIO_ONLY = "audio_only"


class MediaFormat(_Frozen):
    format_id: str
    ext: str
    kind: StreamKind
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    vcodec: str | None = None
    acodec: str | None = None
    abr: float | None = Field(default=None, description="Audio bitrate, kbit/s")
    tbr: float | None = Field(default=None, description="Total bitrate, kbit/s")
    filesize: int | None = None
    filesize_is_estimate: bool = False
    language: str | None = None
    note: str | None = None


class Thumbnail(_Frozen):
    url: str
    width: int | None = None
    height: int | None = None


class MediaInfo(_Frozen):
    id: str
    provider: str
    title: str
    uploader: str | None = None
    duration: float | None = Field(default=None, description="Seconds")
    upload_date: dt.date | None = None
    thumbnail: Thumbnail | None = None
    webpage_url: str
    is_live: bool = False
    formats: tuple[MediaFormat, ...] = ()


class OptionKind(StrEnum):
    VIDEO = "video"
    AUDIO = "audio"


class QualityOption(_Frozen):
    """A user-facing choice resolved to concrete format ids."""

    id: str
    kind: OptionKind
    label: str
    height: int | None = None
    fps: float | None = None
    ext: str
    vcodec: str | None = None
    acodec: str | None = None
    video_format_id: str | None = None
    audio_format_id: str | None = None
    extract_audio: bool = False
    estimated_size: int | None = None
    size_is_estimate: bool = True
    exceeds_limit: bool = False
    is_default: bool = False
