"""Error taxonomy shared by every layer.

Each code maps to one HTTP status and tells the client whether retrying can help.
User-facing wording lives in the frontend (i18n); `default_message` is an English
fallback for API consumers and must never contain internal details.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ErrorCode(StrEnum):
    # Input
    INVALID_URL = "INVALID_URL"
    URL_NOT_ALLOWED = "URL_NOT_ALLOWED"
    UNSUPPORTED_SITE = "UNSUPPORTED_SITE"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    # Content
    CONTENT_NOT_FOUND = "CONTENT_NOT_FOUND"
    CONTENT_PRIVATE = "CONTENT_PRIVATE"
    LOGIN_REQUIRED = "LOGIN_REQUIRED"
    GEO_RESTRICTED = "GEO_RESTRICTED"
    DRM_PROTECTED = "DRM_PROTECTED"
    LIVE_NOT_SUPPORTED = "LIVE_NOT_SUPPORTED"
    NO_MEDIA_FOUND = "NO_MEDIA_FOUND"
    FORMAT_UNAVAILABLE = "FORMAT_UNAVAILABLE"
    TOO_LARGE = "TOO_LARGE"
    TOO_LONG = "TOO_LONG"
    # Upstream
    PLATFORM_BLOCKED = "PLATFORM_BLOCKED"
    UPSTREAM_UNAVAILABLE = "UPSTREAM_UNAVAILABLE"
    EXTRACTOR_FAILED = "EXTRACTOR_FAILED"
    TIMEOUT = "TIMEOUT"
    # Service
    RATE_LIMITED = "RATE_LIMITED"
    SERVER_BUSY = "SERVER_BUSY"
    JOB_NOT_FOUND = "JOB_NOT_FOUND"
    JOB_NOT_READY = "JOB_NOT_READY"
    JOB_EXPIRED = "JOB_EXPIRED"
    NOT_FOUND = "NOT_FOUND"
    INTERNAL_ERROR = "INTERNAL_ERROR"


@dataclass(frozen=True, slots=True)
class ErrorSpec:
    status: int
    retryable: bool
    default_message: str


def _spec(status: int, message: str, *, retry: bool = False) -> ErrorSpec:
    return ErrorSpec(status=status, retryable=retry, default_message=message)


ERROR_SPECS: dict[ErrorCode, ErrorSpec] = {
    ErrorCode.INVALID_URL: _spec(400, "The URL is not valid."),
    ErrorCode.URL_NOT_ALLOWED: _spec(400, "This address is not allowed."),
    ErrorCode.UNSUPPORTED_SITE: _spec(422, "This website is not supported."),
    ErrorCode.VALIDATION_ERROR: _spec(422, "The request is not valid."),
    ErrorCode.CONTENT_NOT_FOUND: _spec(404, "The content does not exist or was removed."),
    ErrorCode.CONTENT_PRIVATE: _spec(403, "The content is private."),
    ErrorCode.LOGIN_REQUIRED: _spec(403, "The platform requires signing in."),
    ErrorCode.GEO_RESTRICTED: _spec(451, "The content is not available in our region."),
    ErrorCode.DRM_PROTECTED: _spec(422, "The content is DRM-protected."),
    ErrorCode.LIVE_NOT_SUPPORTED: _spec(422, "Live streams are not supported."),
    ErrorCode.NO_MEDIA_FOUND: _spec(422, "No downloadable media was found."),
    ErrorCode.FORMAT_UNAVAILABLE: _spec(
        409, "The selected quality is no longer available.", retry=True
    ),
    ErrorCode.TOO_LARGE: _spec(413, "The file exceeds the size limit."),
    ErrorCode.TOO_LONG: _spec(422, "The media exceeds the duration limit."),
    ErrorCode.PLATFORM_BLOCKED: _spec(
        503, "The platform temporarily refused the request.", retry=True
    ),
    ErrorCode.UPSTREAM_UNAVAILABLE: _spec(502, "The platform is not responding.", retry=True),
    ErrorCode.EXTRACTOR_FAILED: _spec(502, "Could not read this content right now.", retry=True),
    ErrorCode.TIMEOUT: _spec(504, "The operation took too long.", retry=True),
    ErrorCode.RATE_LIMITED: _spec(429, "Too many requests. Try again shortly.", retry=True),
    ErrorCode.SERVER_BUSY: _spec(503, "The service is busy. Try again shortly.", retry=True),
    ErrorCode.JOB_NOT_FOUND: _spec(404, "Download not found."),
    ErrorCode.JOB_NOT_READY: _spec(409, "The download is not ready yet.", retry=True),
    ErrorCode.JOB_EXPIRED: _spec(410, "The download has expired."),
    ErrorCode.NOT_FOUND: _spec(404, "Not found."),
    ErrorCode.INTERNAL_ERROR: _spec(500, "Unexpected error.", retry=True),
}


class AppError(Exception):
    """An expected, classified failure. `detail` is for logs only, never for clients."""

    def __init__(
        self,
        code: ErrorCode,
        *,
        detail: str | None = None,
        retry_after: int | None = None,
    ) -> None:
        super().__init__(code.value if detail is None else f"{code.value}: {detail}")
        self.code = code
        self.detail = detail
        self.retry_after = retry_after

    @property
    def spec(self) -> ErrorSpec:
        return ERROR_SPECS[self.code]
