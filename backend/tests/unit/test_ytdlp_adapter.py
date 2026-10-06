import sys
from typing import Any

import pytest
from yt_dlp.utils import DownloadError, ExtractorError, GeoRestrictedError, UnsupportedError

from downloader.domain.errors import AppError, ErrorCode
from downloader.domain.models import StreamKind
from downloader.extraction.ytdlp import _ProgressTracker, convert_format, to_media_info
from downloader.extraction.ytdlp_errors import classify
from downloader.worker.protocol import ProgressEvent

# Messages as emitted by yt-dlp 2026.x extractors.
MESSAGES = [
    ("Sign in to confirm you're not a bot. Use --cookies-from-browser", ErrorCode.PLATFORM_BLOCKED),
    ("Requested content is not available, rate-limit reached or login required", ErrorCode.PLATFORM_BLOCKED),
    ("HTTP Error 429: Too Many Requests", ErrorCode.PLATFORM_BLOCKED),
    ("Private video. Sign in if you've been granted access to this video", ErrorCode.CONTENT_PRIVATE),
    ("This tweet is from a protected account", ErrorCode.CONTENT_PRIVATE),
    ("Sign in to confirm your age. This video may be inappropriate for some users.", ErrorCode.LOGIN_REQUIRED),
    ("This content is only available to members", ErrorCode.LOGIN_REQUIRED),
    ("Video unavailable. This video has been removed by the uploader", ErrorCode.CONTENT_NOT_FOUND),
    ("Video not available, status code 10204", ErrorCode.CONTENT_NOT_FOUND),
    ("Unable to download webpage: HTTP Error 404: Not Found", ErrorCode.CONTENT_NOT_FOUND),
    ("No video could be found in this tweet", ErrorCode.NO_MEDIA_FOUND),
    ("This video is DRM protected", ErrorCode.DRM_PROTECTED),
    ("This live event will begin in 3 hours", ErrorCode.LIVE_NOT_SUPPORTED),
    ("Requested format is not available. Use --list-formats", ErrorCode.FORMAT_UNAVAILABLE),
    ("Unable to download webpage: HTTP Error 503: Service Unavailable", ErrorCode.UPSTREAM_UNAVAILABLE),
    ("Unable to download webpage: Tunnel connection failed: 403 Forbidden", ErrorCode.UPSTREAM_UNAVAILABLE),
    ("Read timed out.", ErrorCode.TIMEOUT),
    ("Unable to extract video data; please report this issue on https://github.com/yt-dlp/yt-dlp/issues?q= . Confirm you are on the latest version using yt-dlp -U", ErrorCode.EXTRACTOR_FAILED),
]  # fmt: skip


def _wrapped(exc: BaseException) -> DownloadError:
    try:
        raise exc
    except BaseException:  # noqa: BLE001
        return DownloadError(f"ERROR: {exc}", sys.exc_info())


@pytest.mark.parametrize(("message", "code"), MESSAGES)
def test_classify_messages(message: str, code: ErrorCode) -> None:
    assert classify(_wrapped(ExtractorError(message, expected=True))) is code


def test_classify_typed_exceptions() -> None:
    assert classify(_wrapped(GeoRestrictedError("nope"))) is ErrorCode.GEO_RESTRICTED
    assert classify(_wrapped(UnsupportedError("https://x"))) is ErrorCode.UNSUPPORTED_CONTENT
    assert classify(ConnectionResetError("boom")) is ErrorCode.UPSTREAM_UNAVAILABLE
    assert classify(ValueError("boom")) is ErrorCode.INTERNAL_ERROR


def yt_format(**kw: Any) -> dict[str, Any]:
    return {"protocol": "https", "ext": "mp4", **kw}


def test_convert_format_kinds_and_filters() -> None:
    video = convert_format(yt_format(format_id="137", vcodec="avc1", acodec="none", height=1080))
    audio = convert_format(yt_format(format_id="140", ext="m4a", vcodec="none", acodec="mp4a"))
    muxed = convert_format(yt_format(format_id="http-720", width=1280, height=720))
    unknown_audio = convert_format(yt_format(format_id="mp3", ext="mp3"))
    assert video is not None
    assert video.kind is StreamKind.VIDEO_ONLY
    assert audio is not None
    assert audio.kind is StreamKind.AUDIO_ONLY
    assert muxed is not None
    assert muxed.kind is StreamKind.AUDIO_VIDEO
    assert unknown_audio is not None
    assert unknown_audio.kind is StreamKind.AUDIO_ONLY
    # Storyboards, DRM and protocols that would make FFmpeg fetch from the network are dropped.
    assert (
        convert_format(yt_format(format_id="sb0", ext="mhtml", vcodec="none", acodec="none"))
        is None
    )
    assert convert_format(yt_format(format_id="d", has_drm=True, vcodec="avc1")) is None
    assert convert_format(yt_format(format_id="r", protocol="rtmp", vcodec="avc1")) is None
    assert (
        convert_format(yt_format(format_id="m", protocol="m3u8_native", vcodec="avc1")) is not None
    )


def test_filesize_approx_is_flagged() -> None:
    f = convert_format(yt_format(format_id="a", vcodec="avc1", acodec="aac", filesize_approx=1000))
    assert f is not None
    assert (f.filesize, f.filesize_is_estimate) == (1000, True)


BASE_INFO: dict[str, Any] = {
    "id": "abc",
    "title": "  A title  ",
    "uploader": "Someone",
    "duration": 61.5,
    "upload_date": "20260102",
    "webpage_url": "https://www.youtube.com/watch?v=abc",
    "thumbnails": [
        {"url": "http://insecure/thumb.jpg", "width": 1280, "preference": 1},
        {"url": "https://i.ytimg.com/vi/abc/hq.jpg", "width": 480, "height": 360},
    ],
    "formats": [yt_format(format_id="18", vcodec="avc1", acodec="mp4a", height=360)],
}


def test_to_media_info() -> None:
    info = to_media_info(BASE_INFO, "youtube")
    assert info.title == "A title"
    assert info.upload_date is not None
    assert info.upload_date.isoformat() == "2026-01-02"
    assert info.thumbnail is not None
    assert info.thumbnail.url.startswith("https://")  # http thumbnail skipped (mixed content)
    assert len(info.formats) == 1


@pytest.mark.parametrize(
    ("patch", "code"),
    [
        ({"is_live": True}, ErrorCode.LIVE_NOT_SUPPORTED),
        ({"live_status": "is_upcoming"}, ErrorCode.LIVE_NOT_SUPPORTED),
        ({"formats": []}, ErrorCode.NO_MEDIA_FOUND),
        ({"formats": [yt_format(format_id="x", has_drm=True)]}, ErrorCode.DRM_PROTECTED),
    ],
)
def test_to_media_info_rejections(patch: dict[str, Any], code: ErrorCode) -> None:
    with pytest.raises(AppError) as exc:
        to_media_info({**BASE_INFO, **patch}, "youtube")
    assert exc.value.code is code


def test_progress_aggregates_video_and_audio() -> None:
    events: list[ProgressEvent] = []
    tracker = _ProgressTracker(events.append, {"137": 1000, "140": 200})
    tracker.hook({"status": "downloading", "downloaded_bytes": 500, "total_bytes": 1000,
                  "info_dict": {"format_id": "137"}})  # fmt: skip
    tracker.hook({"status": "finished", "downloaded_bytes": 1000, "total_bytes": 1000,
                  "info_dict": {"format_id": "137"}})  # fmt: skip
    assert events[0].downloaded == 500
    assert events[0].total == 1200
    assert events[0].total_is_estimate  # audio size not confirmed by the server yet
    assert events[-1].downloaded == 1000


def test_progress_unknown_total_is_indeterminate() -> None:
    events: list[ProgressEvent] = []
    tracker = _ProgressTracker(events.append, {"hls": None})
    tracker.hook(
        {"status": "downloading", "downloaded_bytes": 10, "info_dict": {"format_id": "hls"}}
    )
    assert events[0].total is None
    assert events[0].downloaded == 10


def test_progress_never_exceeds_total() -> None:
    events: list[ProgressEvent] = []
    tracker = _ProgressTracker(events.append, {"x": 100})
    tracker.hook({"status": "downloading", "downloaded_bytes": 150,
                  "total_bytes_estimate": 100, "info_dict": {"format_id": "x"}})  # fmt: skip
    assert events[0].total is None
