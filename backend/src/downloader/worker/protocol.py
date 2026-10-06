"""JSONL protocol between the API process and an isolated worker process.

stdin:  exactly one `WorkerRequest` JSON document.
stdout: one `WorkerEvent` per line. Anything else the worker prints goes to stderr.
The same protocol can later run over a queue or a container boundary.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from downloader.domain.errors import ErrorCode
from downloader.domain.models import MediaInfo

MAX_REQUEST_BYTES = 64 * 1024


class _Msg(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class WorkerLimits(_Msg):
    max_filesize: int = Field(gt=0)
    max_duration: int = Field(gt=0)


class _BaseRequest(_Msg):
    url: str
    providers: tuple[str, ...]
    proxy_url: str
    limits: WorkerLimits


class InspectRequest(_BaseRequest):
    op: Literal["inspect"] = "inspect"


class DownloadRequest(_BaseRequest):
    op: Literal["download"] = "download"
    option_id: str
    workdir: str


type WorkerRequest = Annotated[InspectRequest | DownloadRequest, Field(discriminator="op")]
REQUEST_ADAPTER: TypeAdapter[WorkerRequest] = TypeAdapter(WorkerRequest)


class Phase(StrEnum):
    QUEUED = "queued"
    PREPARING = "preparing"
    DOWNLOADING = "downloading"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class ProgressEvent(_Msg):
    type: Literal["progress"] = "progress"
    phase: Phase
    downloaded: int | None = None
    total: int | None = None
    total_is_estimate: bool = False
    speed: float | None = None
    eta: float | None = None


class InfoEvent(_Msg):
    type: Literal["info"] = "info"
    info: MediaInfo


class DoneEvent(_Msg):
    type: Literal["done"] = "done"
    filename: str
    ext: str
    size: int
    title: str


class ErrorEvent(_Msg):
    type: Literal["error"] = "error"
    code: ErrorCode
    detail: str = ""


type WorkerEvent = Annotated[
    ProgressEvent | InfoEvent | DoneEvent | ErrorEvent, Field(discriminator="type")
]
EVENT_ADAPTER: TypeAdapter[WorkerEvent] = TypeAdapter(WorkerEvent)
