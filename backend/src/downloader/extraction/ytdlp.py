"""yt-dlp adapter. The only module that imports `yt_dlp`.

Safety-relevant parameters (verified against yt-dlp 2026.8.19 source):
- `allowed_extractors`: exact (fullmatch, case-insensitive) allowlist; Generic is never enabled.
- `external_downloader={'default': 'native'}` + live rejection: FFmpeg never fetches
  network resources; it only remuxes local files.
- `proxy`: every request goes through the egress proxy (SSRF policy + byte quota).
- `geo_bypass=False`: do not forge X-Forwarded-For to dodge geo-restrictions.
- No cookies, no netrc, no config files, no plugins dirs, no remote JS components.
"""

from __future__ import annotations

import datetime as dt
import shutil
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Final, cast

import yt_dlp
from yt_dlp.networking import Request

from downloader.domain.errors import AppError, ErrorCode
from downloader.domain.models import MediaFormat, MediaInfo, OptionKind, StreamKind, Thumbnail
from downloader.domain.providers import PROVIDERS, ProviderRegistry
from downloader.domain.quality import Limits, resolve_option
from downloader.extraction.base import (
    DownloadedFile,
    ExtractionContext,
    InfoCallback,
    ProgressCallback,
)
from downloader.extraction.ytdlp_errors import classify
from downloader.security.url import validate_url
from downloader.worker.protocol import Phase, ProgressEvent

type InfoDict = dict[str, Any]

# Single-item extractors per provider. Cross-embeds (e.g. a Reddit post embedding a
# YouTube video) work because the allowlist is the union of all enabled providers.
EXTRACTORS: Final[Mapping[str, tuple[str, ...]]] = {
    "youtube": ("youtube", "youtube:clip"),
    "x": ("twitter",),
    "instagram": ("instagram",),
    "tiktok": ("tiktok", "vm.tiktok"),
    "facebook": ("facebook", "facebook:reel"),
    "reddit": ("reddit",),
    "twitch": ("twitch:clips", "twitch:vod"),
    "vimeo": ("vimeo",),
    "soundcloud": ("soundcloud",),
    "bluesky": ("bluesky",),
    "dailymotion": ("dailymotion",),
    "streamable": ("streamable",),
}
# Short-link hosts only the Generic extractor understands; resolved via the proxy instead.
SHORTLINK_HOSTS: Final = frozenset({"fb.watch", "on.soundcloud.com", "v.redd.it"})
MAX_SHORTLINK_HOPS: Final = 3

ALLOWED_PROTOCOLS: Final = frozenset({"http", "https", "m3u8", "m3u8_native", "http_dash_segments"})
_MAX_TITLE: Final = 300
_MAX_UPLOADER: Final = 120
_PROGRESS_INTERVAL_S: Final = 0.25


class _StderrLogger:
    """Route yt-dlp output away from the stdout protocol channel; keep it short."""

    def __init__(self, sink: Callable[[str], None]) -> None:
        self._sink = sink

    def _emit(self, level: str, msg: str) -> None:
        self._sink(f"[yt-dlp:{level}] {msg[:500]}")

    def debug(self, msg: str) -> None:
        if not msg.startswith("[debug] "):
            self._emit("info", msg)

    def info(self, msg: str) -> None:
        self._emit("info", msg)

    def warning(self, msg: str) -> None:
        self._emit("warning", msg)

    def error(self, msg: str) -> None:
        self._emit("error", msg)


def _str(value: object, limit: int) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()[:limit]


def _int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
        return None
    return int(value)


def _float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
        return None
    return float(value)


def _codec(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _kind(f: InfoDict) -> StreamKind | None:
    vcodec, acodec = _codec(f.get("vcodec")), _codec(f.get("acodec"))
    has_video = vcodec != "none" and (vcodec is not None or bool(f.get("height") or f.get("width")))
    has_audio = acodec != "none"
    if vcodec == "none" and acodec == "none":
        return None  # storyboards, images
    if vcodec is None and acodec is None and not has_video:
        # Unknown codecs and no dimensions: decide by extension.
        ext = str(f.get("ext") or "")
        return (
            StreamKind.AUDIO_ONLY
            if ext in {"m4a", "mp3", "opus", "ogg", "aac"}
            else StreamKind.AUDIO_VIDEO
        )
    if has_video and has_audio:
        return StreamKind.AUDIO_VIDEO
    return StreamKind.VIDEO_ONLY if has_video else StreamKind.AUDIO_ONLY


def convert_format(f: InfoDict) -> MediaFormat | None:
    if f.get("has_drm") or f.get("protocol") not in ALLOWED_PROTOCOLS:
        return None
    kind = _kind(f)
    fmt_id, ext = f.get("format_id"), f.get("ext")
    if kind is None or not isinstance(fmt_id, str) or not isinstance(ext, str):
        return None
    size = _int(f.get("filesize"))
    approx = _int(f.get("filesize_approx"))
    return MediaFormat(
        format_id=fmt_id,
        ext=ext,
        kind=kind,
        width=_int(f.get("width")),
        height=_int(f.get("height")),
        fps=_float(f.get("fps")),
        vcodec=_codec(f.get("vcodec")),
        acodec=_codec(f.get("acodec")),
        abr=_float(f.get("abr")),
        tbr=_float(f.get("tbr")),
        filesize=size or approx,
        filesize_is_estimate=size is None,
        language=_str(f.get("language"), 16),
        note=_str(f.get("format_note"), 64),
    )


def _thumbnail(info: InfoDict) -> Thumbnail | None:
    candidates = [t for t in info.get("thumbnails") or [] if isinstance(t, dict)]
    candidates.sort(key=lambda t: (t.get("preference") or 0, _int(t.get("width")) or 0))
    for t in reversed(candidates):
        url = t.get("url")
        if isinstance(url, str) and url.startswith("https://") and len(url) <= 2048:
            return Thumbnail(url=url, width=_int(t.get("width")), height=_int(t.get("height")))
    url = info.get("thumbnail")
    if isinstance(url, str) and url.startswith("https://") and len(url) <= 2048:
        return Thumbnail(url=url)
    return None


def _upload_date(info: InfoDict) -> dt.date | None:
    raw = info.get("upload_date")
    if isinstance(raw, str) and len(raw) == 8 and raw.isdigit():
        try:
            return dt.date(int(raw[:4]), int(raw[4:6]), int(raw[6:]))
        except ValueError:
            return None
    ts = info.get("timestamp")
    if isinstance(ts, int | float) and ts > 0:
        return dt.datetime.fromtimestamp(ts, tz=dt.UTC).date()
    return None


def _pick_entry(info: InfoDict) -> InfoDict:
    """Multi-item posts (e.g. a tweet with several videos) come back as playlists."""
    if info.get("_type") not in {"playlist", "multi_video"}:
        return info
    for entry in info.get("entries") or []:
        if isinstance(entry, dict) and entry.get("formats"):
            return entry
    raise AppError(ErrorCode.UNSUPPORTED_CONTENT, detail="playlist or collection")


def to_media_info(info: InfoDict, provider: str) -> MediaInfo:
    if info.get("is_live") or info.get("live_status") in {"is_live", "is_upcoming"}:
        raise AppError(ErrorCode.LIVE_NOT_SUPPORTED)
    raw_formats = [f for f in info.get("formats") or [] if isinstance(f, dict)]
    formats = tuple(f for f in map(convert_format, raw_formats) if f is not None)
    if not formats:
        if raw_formats and all(f.get("has_drm") for f in raw_formats):
            raise AppError(ErrorCode.DRM_PROTECTED)
        raise AppError(ErrorCode.NO_MEDIA_FOUND)
    webpage_url = info.get("webpage_url")
    return MediaInfo(
        id=str(info.get("id") or "")[:128],
        provider=provider,
        title=_str(info.get("title"), _MAX_TITLE) or "Untitled",
        uploader=_str(
            info.get("uploader") or info.get("channel") or info.get("creator"), _MAX_UPLOADER
        ),
        duration=_float(info.get("duration")),
        upload_date=_upload_date(info),
        thumbnail=_thumbnail(info),
        webpage_url=webpage_url if isinstance(webpage_url, str) else "",
        formats=formats,
    )


class _ProgressTracker:
    """Aggregates per-file hook data into one monotonic, throttled progress stream."""

    def __init__(self, emit: ProgressCallback, expected: Mapping[str, int | None]) -> None:
        self._emit = emit
        self._expected = dict(expected)
        self._done: dict[str, int] = {}
        self._current: dict[str, tuple[int, int | None, bool]] = {}
        self._last = 0.0

    def hook(self, d: InfoDict) -> None:
        fmt = cast("InfoDict", d.get("info_dict") or {}).get("format_id") or "?"
        downloaded = _int(d.get("downloaded_bytes")) or 0
        total = _int(d.get("total_bytes"))
        estimate = total is None
        total = total or _int(d.get("total_bytes_estimate")) or self._expected.get(fmt)
        if d.get("status") == "finished":
            self._done[fmt] = downloaded or total or 0
            self._current.pop(fmt, None)
            self._send(force=True, speed=None, eta=None)
            return
        self._current[fmt] = (downloaded, total, estimate)
        self._send(force=False, speed=_float(d.get("speed")), eta=_float(d.get("eta")))

    def _send(self, *, force: bool, speed: float | None, eta: float | None) -> None:
        now = time.monotonic()
        if not force and now - self._last < _PROGRESS_INTERVAL_S:
            return
        self._last = now
        downloaded = sum(self._done.values()) + sum(c[0] for c in self._current.values())
        totals: list[int | None] = []
        estimate = False
        for fmt, expected in self._expected.items():
            if fmt in self._done:
                totals.append(self._done[fmt])
            elif fmt in self._current:
                totals.append(self._current[fmt][1])
                estimate = estimate or self._current[fmt][2]
            else:
                totals.append(expected)
                estimate = True
        total = None if any(t is None for t in totals) else sum(t for t in totals if t is not None)
        if total is not None and downloaded > total:
            total = None  # estimates were wrong: show indeterminate rather than >100 %
        self._emit(
            ProgressEvent(
                phase=Phase.DOWNLOADING,
                downloaded=downloaded,
                total=total,
                total_is_estimate=estimate,
                speed=speed,
                eta=eta,
            )
        )


class YtDlpExtractor:
    def __init__(self, *, log: Callable[[str], None], ffmpeg: str | None = None) -> None:
        self._log = log
        self._ffmpeg = ffmpeg or shutil.which("ffmpeg")
        self._deno = shutil.which("deno")

    def _params(self, ctx: ExtractionContext, **extra: Any) -> InfoDict:
        allowed = [name for slug in ctx.providers for name in EXTRACTORS.get(slug, ())]
        params: InfoDict = {
            "quiet": True,
            "no_warnings": False,
            "noprogress": True,
            "color": "no_color",
            "logger": _StderrLogger(self._log),
            "allowed_extractors": allowed or ["^$"],
            "proxy": ctx.proxy_url,
            "socket_timeout": 20,
            "retries": 2,
            "fragment_retries": 3,
            "extractor_retries": 1,
            "noplaylist": True,
            "extract_flat": "in_playlist",
            "external_downloader": {"default": "native"},
            "hls_prefer_native": True,
            "geo_bypass": False,
            "cachedir": False,
            "usenetrc": False,
            "check_formats": False,
            "js_runtimes": {"deno": {"path": self._deno}} if self._deno else {},
            "max_filesize": ctx.limits.max_filesize,
            "concurrent_fragment_downloads": 4,
        }
        if self._ffmpeg:
            params["ffmpeg_location"] = self._ffmpeg
        params.update(extra)
        return params

    @contextmanager
    def _ydl(self, ctx: ExtractionContext, **extra: Any) -> Iterator[yt_dlp.YoutubeDL]:
        with yt_dlp.YoutubeDL(cast("Any", self._params(ctx, **extra))) as ydl:
            yield ydl

    def _resolve_shortlink(
        self, ydl: yt_dlp.YoutubeDL, url: str, registry: ProviderRegistry
    ) -> str:
        for _ in range(MAX_SHORTLINK_HOPS):
            if validate_url(url).host not in SHORTLINK_HOSTS:
                return url
            with ydl.urlopen(Request(url, headers={"Range": "bytes=0-0"})) as resp:
                final = str(resp.url)
            validated = validate_url(final)
            if registry.detect(validated.host) is None:
                raise AppError(ErrorCode.UNSUPPORTED_SITE, detail="short link left supported sites")
            url = validated.url
        raise AppError(ErrorCode.UNSUPPORTED_CONTENT, detail="too many short-link hops")

    def _extract(
        self, ydl: yt_dlp.YoutubeDL, url: str, ctx: ExtractionContext
    ) -> tuple[InfoDict, str]:
        registry = ProviderRegistry(PROVIDERS, frozenset(ctx.providers))
        url = self._resolve_shortlink(ydl, url, registry)
        info = ydl.extract_info(url, download=False)
        if not isinstance(info, dict):
            raise AppError(ErrorCode.NO_MEDIA_FOUND)
        entry = _pick_entry(cast("InfoDict", info))
        host = validate_url(url).host
        provider = registry.detect(host)
        return entry, provider.slug if provider else "unknown"

    def inspect(self, url: str, ctx: ExtractionContext) -> MediaInfo:
        try:
            with self._ydl(ctx) as ydl:
                info, provider = self._extract(ydl, url, ctx)
                return to_media_info(info, provider)
        except AppError:
            raise
        except Exception as exc:
            raise AppError(classify(exc), detail=type(exc).__name__) from exc

    def download(
        self,
        url: str,
        option_id: str,
        workdir: Path,
        ctx: ExtractionContext,
        *,
        on_info: InfoCallback,
        on_progress: ProgressCallback,
    ) -> DownloadedFile:
        try:
            return self._download(
                url, option_id, workdir, ctx, on_info=on_info, on_progress=on_progress
            )
        except AppError:
            raise
        except Exception as exc:
            raise AppError(classify(exc), detail=type(exc).__name__) from exc

    def _download(
        self,
        url: str,
        option_id: str,
        workdir: Path,
        ctx: ExtractionContext,
        *,
        on_info: InfoCallback,
        on_progress: ProgressCallback,
    ) -> DownloadedFile:
        spec: dict[str, str] = {"value": "b/bv*+ba/ba"}

        def selector(sel_ctx: InfoDict) -> Iterator[InfoDict]:
            yield from ydl.build_format_selector(spec["value"])(sel_ctx)

        tracker: _ProgressTracker | None = None

        def progress_hook(d: InfoDict) -> None:
            if tracker is not None:
                tracker.hook(d)

        def pp_hook(d: InfoDict) -> None:
            if d.get("status") == "started":
                on_progress(ProgressEvent(phase=Phase.PROCESSING))

        extra: InfoDict = {
            "format": selector,
            "outtmpl": {"default": "media.%(ext)s"},
            "paths": {"home": str(workdir), "temp": str(workdir)},
            "overwrites": True,
            "restrictfilenames": True,
            "progress_hooks": [progress_hook],
            "postprocessor_hooks": [pp_hook],
            "postprocessor_args": {"ffmpeg_i": ["-protocol_whitelist", "file,pipe"]},
        }
        with self._ydl(ctx, **extra) as ydl:
            info, provider = self._extract(ydl, url, ctx)
            media = to_media_info(info, provider)
            on_info(media)
            limits = Limits(ctx.limits.max_filesize, ctx.limits.max_duration)
            if media.duration and media.duration > ctx.limits.max_duration:
                raise AppError(ErrorCode.TOO_LONG)
            option = resolve_option(option_id, media.formats, media.duration, limits)
            if option.exceeds_limit:
                raise AppError(ErrorCode.TOO_LARGE, detail="estimate above limit")
            ids = [i for i in (option.video_format_id, option.audio_format_id) if i]
            if option.kind is OptionKind.AUDIO:
                ids = [option.audio_format_id or ""]
            spec["value"] = "+".join(ids)
            by_id = {f.format_id: f for f in media.formats}
            tracker = _ProgressTracker(
                on_progress,
                {i: by_id[i].filesize if i in by_id else None for i in ids},
            )
            if option.kind is OptionKind.VIDEO and len(ids) == 2:
                ydl.params["merge_output_format"] = option.ext
            if option.extract_audio:
                ydl.add_post_processor(
                    yt_dlp.postprocessor.FFmpegExtractAudioPP(ydl, preferredcodec="best"),
                    when="post_process",
                )
            on_progress(ProgressEvent(phase=Phase.DOWNLOADING))
            result = ydl.process_ie_result(info, download=True)
        return _final_file(workdir, cast("InfoDict", result), media.title)


def _final_file(workdir: Path, result: InfoDict, title: str) -> DownloadedFile:
    downloads = result.get("requested_downloads") or []
    raw = downloads[0].get("filepath") if downloads and isinstance(downloads[0], dict) else None
    if not raw:
        # yt-dlp skips (without raising) when the size exceeds max_filesize.
        raise AppError(ErrorCode.TOO_LARGE, detail="no output produced")
    path = Path(raw)
    root = workdir.resolve()
    if path.is_symlink() or not path.is_file() or path.resolve().parent != root:
        raise AppError(ErrorCode.INTERNAL_ERROR, detail="unexpected output location")
    return DownloadedFile(
        path=path, ext=path.suffix.lstrip("."), size=path.stat().st_size, title=title
    )
