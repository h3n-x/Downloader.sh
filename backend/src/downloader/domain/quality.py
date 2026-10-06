"""Pure quality-selection logic: real formats in, user-facing options out.

Rules (documented in docs/architecture.md):
- Resolution class uses the *short side*, so 1080x1920 vertical video is "1080p".
- Within a class, prefer the most compatible codec (H.264 > AV1/VP9 > HEVC > other),
  then the highest bitrate. Never transcode video: pairing picks containers that remux.
- Audio for a video-only stream prefers the same container family (mp4↔m4a, webm↔webm).
- Only classes that actually exist are offered. Option ids are deterministic so the
  worker can recompute them on fresh formats at download time.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Final

from downloader.domain.errors import AppError, ErrorCode
from downloader.domain.models import MediaFormat, OptionKind, QualityOption, StreamKind

LADDER: Final = (2160, 1440, 1080, 720, 480, 360, 240, 144)
DEFAULT_MAX_HEIGHT: Final = 1080
FORMAT_ID_RE: Final = re.compile(r"^[A-Za-z0-9._=-]{1,64}$")
OPTION_ID_RE: Final = re.compile(r"^(?:v\d{3,4}|video|audio|f:[A-Za-z0-9._=-]{1,64})$")

_MP4_FAMILY: Final = frozenset({"mp4", "m4a", "mov"})
_LABEL_SUFFIX: Final = {2160: " (4K)", 1440: " (2K)"}
_AUDIO_EXT_BY_CODEC: Final = {
    "mp4a": "m4a",
    "aac": "m4a",
    "opus": "opus",
    "mp3": "mp3",
    "vorbis": "ogg",
}


def codec_family(codec: str | None) -> str | None:
    if not codec or codec == "none":
        return None
    return codec.split(".", 1)[0].lower()


def _video_compat(fmt: MediaFormat) -> int:
    return {"avc1": 4, "h264": 4, "av01": 3, "vp09": 2, "vp9": 2, "hev1": 1, "hvc1": 1}.get(
        codec_family(fmt.vcodec) or "", 0
    )


def resolution_class(fmt: MediaFormat) -> int | None:
    sides = [s for s in (fmt.width, fmt.height) if s]
    if not sides:
        return None
    short = min(sides)
    return next((rung for rung in LADDER if short >= rung * 0.9), None)


def estimated_bytes(fmt: MediaFormat, duration: float | None) -> tuple[int | None, bool]:
    if fmt.filesize:
        return fmt.filesize, fmt.filesize_is_estimate
    if fmt.tbr and duration:
        return int(fmt.tbr * 1000 / 8 * duration), True
    return None, True


def _sum_sizes(
    parts: Iterable[MediaFormat | None], duration: float | None
) -> tuple[int | None, bool]:
    total, estimate = 0, False
    for fmt in parts:
        if fmt is None:
            continue
        size, est = estimated_bytes(fmt, duration)
        if size is None:
            return None, True
        total += size
        estimate = estimate or est
    return total, estimate


def _best_audio(audios: Sequence[MediaFormat], prefer_ext: str | None) -> MediaFormat | None:
    def key(f: MediaFormat) -> tuple[int, int, float]:
        same_family = prefer_ext is not None and (
            (f.ext in _MP4_FAMILY) == (prefer_ext in _MP4_FAMILY)
        )
        return (int(same_family), int(f.ext == "m4a"), f.abr or f.tbr or 0.0)

    return max(audios, key=key, default=None)


def _merged_ext(video: MediaFormat, audio: MediaFormat | None) -> str:
    if audio is None:
        return video.ext
    if video.ext in _MP4_FAMILY and audio.ext in _MP4_FAMILY:
        return "mp4"
    if video.ext == "webm" and audio.ext == "webm":
        return "webm"
    return "mkv"


def _audio_ext(fmt: MediaFormat) -> str:
    if fmt.kind is StreamKind.AUDIO_ONLY and fmt.ext in {"m4a", "mp3", "opus", "ogg"}:
        return fmt.ext
    return _AUDIO_EXT_BY_CODEC.get(codec_family(fmt.acodec) or "", "mka")


@dataclass(frozen=True, slots=True)
class Limits:
    max_filesize: int | None = None
    max_duration: float | None = None

    def exceeded(self, size: int | None, duration: float | None) -> bool:
        too_big = bool(self.max_filesize and size and size > self.max_filesize)
        too_long = bool(self.max_duration and duration and duration > self.max_duration)
        return too_big or too_long


def _video_option(
    option_id: str,
    label: str,
    video: MediaFormat,
    *,
    audios: Sequence[MediaFormat],
    duration: float | None,
    limits: Limits,
) -> QualityOption:
    audio = None if video.kind is StreamKind.AUDIO_VIDEO else _best_audio(audios, video.ext)
    size, est = _sum_sizes((video, audio), duration)
    return QualityOption(
        id=option_id,
        kind=OptionKind.VIDEO,
        label=label,
        height=resolution_class(video),
        fps=video.fps,
        ext=_merged_ext(video, audio),
        vcodec=codec_family(video.vcodec),
        acodec=codec_family((audio or video).acodec),
        video_format_id=video.format_id,
        audio_format_id=audio.format_id if audio else None,
        estimated_size=size,
        size_is_estimate=est,
        exceeds_limit=limits.exceeded(size, duration),
    )


def _audio_option(
    option_id: str, label: str, source: MediaFormat, duration: float | None, limits: Limits
) -> QualityOption:
    size, est = estimated_bytes(source, duration)
    if source.kind is not StreamKind.AUDIO_ONLY:
        # Extracting from a muxed stream still downloads the video track.
        est = True
    return QualityOption(
        id=option_id,
        kind=OptionKind.AUDIO,
        label=label,
        ext=_audio_ext(source),
        acodec=codec_family(source.acodec),
        audio_format_id=source.format_id,
        extract_audio=True,
        estimated_size=size,
        size_is_estimate=est,
        exceeds_limit=limits.exceeded(size, duration),
    )


def usable_formats(formats: Iterable[MediaFormat]) -> list[MediaFormat]:
    return [f for f in formats if FORMAT_ID_RE.match(f.format_id)]


def _split(formats: Sequence[MediaFormat]) -> tuple[list[MediaFormat], list[MediaFormat]]:
    videos = [f for f in formats if f.kind is not StreamKind.AUDIO_ONLY and f.vcodec != "none"]
    audios = [f for f in formats if f.kind is StreamKind.AUDIO_ONLY]
    return videos, audios


def _video_rank(f: MediaFormat) -> tuple[int, int, float, float]:
    has_audio = int(f.kind is StreamKind.AUDIO_VIDEO)
    return (_video_compat(f), has_audio, f.fps or 0.0, f.tbr or 0.0)


def build_options(
    formats: Sequence[MediaFormat], duration: float | None, limits: Limits | None = None
) -> list[QualityOption]:
    """Standard options: one per available resolution class, plus audio."""
    limits = limits or Limits()
    videos, audios = _split(usable_formats(formats))
    by_class: dict[int, list[MediaFormat]] = {}
    for f in videos:
        rc = resolution_class(f)
        if rc is not None:
            by_class.setdefault(rc, []).append(f)
    # A video-only stream with no audio anywhere would produce a silent file; prefer muxed ones.
    options: list[QualityOption] = []
    for rc in sorted(by_class, reverse=True):
        candidates = by_class[rc]
        if not audios:
            candidates = [f for f in candidates if f.kind is StreamKind.AUDIO_VIDEO] or candidates
        best = max(candidates, key=_video_rank)
        label = f"{rc}p{_LABEL_SUFFIX.get(rc, '')}"
        options.append(
            _video_option(f"v{rc}", label, best, audios=audios, duration=duration, limits=limits)
        )
    if not options and videos:  # no dimensions reported (common on some platforms)
        best = max(videos, key=_video_rank)
        options.append(
            _video_option("video", "Video", best, audios=audios, duration=duration, limits=limits)
        )

    audio_source = _best_audio(audios, None) or next(
        (o for o in sorted(videos, key=lambda f: f.tbr or 0.0) if o.kind is StreamKind.AUDIO_VIDEO),
        None,
    )
    if audio_source is not None:
        options.append(_audio_option("audio", "Audio", audio_source, duration, limits))
    return _mark_default(options)


def _mark_default(options: list[QualityOption]) -> list[QualityOption]:
    eligible = [
        o
        for o in options
        if o.kind is OptionKind.VIDEO
        and not o.exceeds_limit
        and (o.height or 0) <= DEFAULT_MAX_HEIGHT
    ] or [o for o in options if not o.exceeds_limit]
    if not eligible:
        return options
    default_id = eligible[0].id
    return [o.model_copy(update={"is_default": o.id == default_id}) for o in options]


def resolve_option(
    option_id: str,
    formats: Sequence[MediaFormat],
    duration: float | None,
    limits: Limits | None = None,
) -> QualityOption:
    """Map an option id (standard or ``f:<format_id>``) to concrete formats."""
    if not OPTION_ID_RE.match(option_id):
        raise AppError(ErrorCode.VALIDATION_ERROR, detail="bad option id")
    limits = limits or Limits()
    if option_id.startswith("f:"):
        fmt_id = option_id[2:]
        usable = usable_formats(formats)
        fmt = next((f for f in usable if f.format_id == fmt_id), None)
        if fmt is None:
            raise AppError(ErrorCode.FORMAT_UNAVAILABLE, detail="format id not found")
        if fmt.kind is StreamKind.AUDIO_ONLY:
            return _audio_option(option_id, fmt.format_id, fmt, duration, limits)
        _, audios = _split(usable)
        return _video_option(
            option_id, fmt.format_id, fmt, audios=audios, duration=duration, limits=limits
        )
    option = next((o for o in build_options(formats, duration, limits) if o.id == option_id), None)
    if option is None:
        raise AppError(ErrorCode.FORMAT_UNAVAILABLE, detail="option not available")
    return option
