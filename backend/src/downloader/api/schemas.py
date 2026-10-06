"""HTTP contracts (source of the OpenAPI schema consumed by the frontend)."""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from downloader.app.jobs import JobView
from downloader.domain.errors import ErrorCode
from downloader.domain.models import MediaFormat, QualityOption, Thumbnail
from downloader.domain.quality import OPTION_ID_RE

MAX_URL_FIELD = 4096


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class InspectBody(_In):
    url: str = Field(min_length=1, max_length=MAX_URL_FIELD)


class DownloadBody(_In):
    url: str = Field(min_length=1, max_length=MAX_URL_FIELD)
    option_id: str = Field(pattern=OPTION_ID_RE.pattern, max_length=80)


class ProviderOut(BaseModel):
    slug: str
    name: str


class LimitsOut(BaseModel):
    max_filesize: int
    max_duration: int


class MediaOut(BaseModel):
    id: str
    title: str
    uploader: str | None
    duration: float | None
    upload_date: dt.date | None
    thumbnail: Thumbnail | None
    webpage_url: str
    provider: ProviderOut


class InspectOut(BaseModel):
    media: MediaOut
    options: list[QualityOption]
    formats: list[MediaFormat]
    limits: LimitsOut


class JobOut(JobView):
    events_url: str
    file_url: str | None


class MetaOut(BaseModel):
    version: str
    providers: list[ProviderOut]
    limits: LimitsOut


class HealthOut(BaseModel):
    status: Literal["ok"] = "ok"
    version: str


class ReadyOut(BaseModel):
    status: Literal["ready", "degraded"]
    checks: dict[str, bool]


class ErrorBody(BaseModel):
    code: ErrorCode
    message: str
    retryable: bool
    request_id: str | None = None
    retry_after: int | None = None
    fields: list[str] | None = None


class ErrorOut(BaseModel):
    error: ErrorBody
