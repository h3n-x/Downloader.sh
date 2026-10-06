"""Map yt-dlp failures to the domain error taxonomy.

yt-dlp exposes a few typed exceptions (GeoRestrictedError, UnsupportedError…) but
most platform conditions only surface as message text. All heuristics live here,
in priority order, with fixtures in tests/unit/test_ytdlp_errors.py.
"""

from __future__ import annotations

import re
from typing import Final

from yt_dlp.utils import (
    DownloadError,
    ExtractorError,
    GeoRestrictedError,
    UnsupportedError,
    UserNotLive,
)

from downloader.domain.errors import ErrorCode

# Order matters: the first match wins (bot checks mention "sign in" too).
_PATTERNS: Final[tuple[tuple[ErrorCode, tuple[str, ...]], ...]] = (
    (ErrorCode.PLATFORM_BLOCKED, (
        r"not a bot", r"confirm you.re not", r"captcha", r"http error 429",
        r"too many requests", r"rate.?limit",
    )),
    (ErrorCode.DRM_PROTECTED, (r"\bdrm\b",)),
    (ErrorCode.LIVE_NOT_SUPPORTED, (
        r"live event will begin", r"premieres in", r"is a live", r"currently live",
    )),
    (ErrorCode.GEO_RESTRICTED, (
        r"not available in your (country|region)", r"geo.?restrict", r"blocked it in your country",
    )),
    (ErrorCode.CONTENT_PRIVATE, (
        r"\bprivate (video|account|post|tweet)", r"video is private", r"is private\b",
        r"protected tweet", r"protected account",
    )),
    (ErrorCode.LOGIN_REQUIRED, (
        r"\bsign.?in\b", r"\blog.?in\b", r"authenticat", r"--cookies", r"age.?restrict",
        r"confirm your age", r"inappropriate for some users", r"members.only",
        r"available to members",
    )),
    (ErrorCode.TOO_LARGE, (r"larger than max-filesize",)),
    (ErrorCode.FORMAT_UNAVAILABLE, (r"requested format is not available",)),
    (ErrorCode.CONTENT_NOT_FOUND, (
        r"video unavailable", r"not available", r"has been removed", r"been deleted",
        r"does not exist", r"doesn.t exist", r"not found", r"http error 40[34]",
        r"http error 410", r"terminated", r"copyright claim",
    )),
    (ErrorCode.NO_MEDIA_FOUND, (
        r"no video formats", r"no video could be found", r"there.s no video", r"no media found",
        r"no formats? found",
    )),
    (ErrorCode.TIMEOUT, (r"timed out", r"timeout")),
    (ErrorCode.UPSTREAM_UNAVAILABLE, (
        r"http error 5\d\d", r"connection (reset|refused|aborted)", r"unable to connect",
        r"network is unreachable", r"tunnel connection failed", r"temporary failure",
        r"name resolution", r"\bssl\b",
    )),
)  # fmt: skip
_RULES: Final = tuple((code, re.compile("|".join(alts), re.IGNORECASE)) for code, alts in _PATTERNS)
_TYPED: Final[tuple[tuple[type[BaseException], ErrorCode], ...]] = (
    (GeoRestrictedError, ErrorCode.GEO_RESTRICTED),
    (UnsupportedError, ErrorCode.UNSUPPORTED_CONTENT),
    (UserNotLive, ErrorCode.CONTENT_NOT_FOUND),
)


def _root(exc: BaseException) -> BaseException:
    if isinstance(exc, DownloadError) and exc.exc_info:
        inner = exc.exc_info[1]
        if isinstance(inner, BaseException):
            return inner
    return exc


def classify(exc: BaseException) -> ErrorCode:
    root = _root(exc)
    typed = next((code for cls, code in _TYPED if isinstance(root, cls)), None)
    if typed is not None:
        return typed
    message = f"{exc} {root}"
    matched = next((code for code, pattern in _RULES if pattern.search(message)), None)
    if matched is not None:
        return matched
    if isinstance(root, ExtractorError):
        return ErrorCode.EXTRACTOR_FAILED
    return ErrorCode.UPSTREAM_UNAVAILABLE if isinstance(root, OSError) else ErrorCode.INTERNAL_ERROR
