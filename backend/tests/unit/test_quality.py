import pytest
from hypothesis import given
from hypothesis import strategies as st

from downloader.domain.errors import AppError, ErrorCode
from downloader.domain.models import MediaFormat, OptionKind, StreamKind
from downloader.domain.quality import (
    LADDER,
    Limits,
    build_options,
    resolution_class,
    resolve_option,
)

V, A, AV = StreamKind.VIDEO_ONLY, StreamKind.AUDIO_ONLY, StreamKind.AUDIO_VIDEO


def fmt(fid: str, kind: StreamKind, ext: str, **kw: object) -> MediaFormat:
    return MediaFormat.model_validate({"format_id": fid, "kind": kind, "ext": ext, **kw})


YOUTUBE = [
    fmt("140", A, "m4a", acodec="mp4a.40.2", abr=129.5, filesize=3_000_000),
    fmt("251", A, "webm", acodec="opus", abr=160, filesize=3_500_000),
    fmt(
        "137",
        V,
        "mp4",
        vcodec="avc1.640028",
        width=1920,
        height=1080,
        fps=30,
        tbr=4400,
        filesize=90_000_000,
    ),
    fmt(
        "248",
        V,
        "webm",
        vcodec="vp9",
        width=1920,
        height=1080,
        fps=30,
        tbr=2600,
        filesize=60_000_000,
    ),
    fmt(
        "136",
        V,
        "mp4",
        vcodec="avc1.4d401f",
        width=1280,
        height=720,
        fps=30,
        tbr=2000,
        filesize=40_000_000,
    ),
    fmt(
        "313",
        V,
        "webm",
        vcodec="vp9",
        width=3840,
        height=2160,
        fps=30,
        tbr=17000,
        filesize=400_000_000,
    ),
    fmt(
        "271",
        V,
        "webm",
        vcodec="vp9",
        width=2560,
        height=1440,
        fps=30,
        tbr=9000,
        filesize=200_000_000,
    ),
    fmt("18", AV, "mp4", vcodec="avc1.42001E", acodec="mp4a.40.2", width=640, height=360, tbr=500),
]


def test_youtube_ladder_and_pairing() -> None:
    opts = build_options(YOUTUBE, duration=212)
    assert [o.id for o in opts] == ["v2160", "v1440", "v1080", "v720", "v360", "audio"]
    by = {o.id: o for o in opts}
    # 1080p prefers H.264 (mp4) and pairs with m4a → mp4 without transcoding.
    assert (by["v1080"].video_format_id, by["v1080"].audio_format_id) == ("137", "140")
    assert by["v1080"].ext == "mp4"
    assert by["v1080"].estimated_size == 93_000_000
    # 4K only exists as VP9/webm → paired with opus/webm → webm.
    assert (by["v2160"].video_format_id, by["v2160"].audio_format_id) == ("313", "251")
    assert by["v2160"].ext == "webm"
    assert by["v2160"].label == "2160p (4K)"
    # 360p muxed stream needs no separate audio.
    assert by["v360"].audio_format_id is None
    assert by["audio"].audio_format_id == "140"
    assert by["audio"].ext == "m4a"
    assert by["v1080"].is_default
    assert sum(o.is_default for o in opts) == 1


def test_size_limit_marks_options_and_moves_default() -> None:
    opts = build_options(YOUTUBE, duration=212, limits=Limits(max_filesize=50_000_000))
    by = {o.id: o for o in opts}
    assert by["v2160"].exceeds_limit
    assert by["v1080"].exceeds_limit
    assert not by["v720"].exceeds_limit
    assert by["v720"].is_default


def test_vertical_video_uses_short_side() -> None:
    tiktok = [
        fmt("h264_540", AV, "mp4", vcodec="h264", acodec="aac", width=576, height=1024, tbr=900),
        fmt("h264_1080", AV, "mp4", vcodec="h264", acodec="aac", width=1080, height=1920, tbr=2500),
        fmt(
            "bytevc1_1080",
            AV,
            "mp4",
            vcodec="h265",
            acodec="aac",
            width=1080,
            height=1920,
            tbr=1800,
        ),
    ]
    opts = build_options(tiktok, duration=30)
    assert [o.id for o in opts] == ["v1080", "v480", "audio"]
    assert opts[0].video_format_id == "h264_1080"
    # Audio extracted from the smallest muxed stream.
    assert opts[-1].audio_format_id == "h264_540"
    assert opts[-1].extract_audio
    assert opts[-1].ext == "m4a"


def test_audio_only_platform() -> None:
    sc = [
        fmt("hls_mp3_128", A, "mp3", acodec="mp3", abr=128),
        fmt("hls_opus_64", A, "opus", acodec="opus", abr=64),
    ]
    opts = build_options(sc, duration=180)
    assert [o.id for o in opts] == ["audio"]
    assert opts[0].is_default


def test_formats_without_dimensions_still_offer_video() -> None:
    opts = build_options([fmt("http", AV, "mp4", vcodec="h264", acodec="aac")], duration=None)
    assert [o.id for o in opts] == ["video", "audio"]


def test_unsafe_format_ids_are_ignored() -> None:
    opts = build_options([fmt("1+2/[x]", AV, "mp4", vcodec="h264", acodec="aac", height=720)], 10)
    assert opts == []


def test_resolve_standard_and_advanced() -> None:
    assert resolve_option("v720", YOUTUBE, 212).video_format_id == "136"
    adv = resolve_option("f:248", YOUTUBE, 212)
    assert (adv.video_format_id, adv.audio_format_id, adv.ext) == ("248", "251", "webm")
    audio = resolve_option("f:251", YOUTUBE, 212)
    assert audio.kind is OptionKind.AUDIO
    assert audio.ext in {"webm", "opus"}


@pytest.mark.parametrize("option_id", ["v480", "f:999"])
def test_resolve_missing(option_id: str) -> None:
    with pytest.raises(AppError) as exc:
        resolve_option(option_id, YOUTUBE, 212)
    assert exc.value.code is ErrorCode.FORMAT_UNAVAILABLE


@pytest.mark.parametrize("option_id", ["", "best+bad", "f:1/2", "f:a+b", "v1080;rm", "x" * 80])
def test_resolve_rejects_malformed(option_id: str) -> None:
    with pytest.raises(AppError) as exc:
        resolve_option(option_id, YOUTUBE, 212)
    assert exc.value.code is ErrorCode.VALIDATION_ERROR


@given(st.integers(1, 10_000), st.integers(1, 10_000))
def test_resolution_class_is_a_ladder_rung_or_none(w: int, h: int) -> None:
    rc = resolution_class(fmt("x", V, "mp4", width=w, height=h))
    assert rc is None or rc in LADDER
    if rc is not None:
        assert min(w, h) >= rc * 0.9


format_strategy = st.builds(
    fmt,
    st.from_regex(r"[A-Za-z0-9]{1,6}", fullmatch=True),
    st.sampled_from(list(StreamKind)),
    st.sampled_from(["mp4", "webm", "m4a", "mp3"]),
    vcodec=st.sampled_from(["avc1.4d", "vp9", "av01.0", None]),
    acodec=st.sampled_from(["mp4a.40.2", "opus", None]),
    height=st.one_of(st.none(), st.integers(100, 4000)),
    width=st.one_of(st.none(), st.integers(100, 4000)),
    tbr=st.one_of(st.none(), st.floats(1, 50_000)),
)


@given(st.lists(format_strategy, max_size=15), st.one_of(st.none(), st.floats(1, 36_000)))
def test_options_are_consistent(formats: list[MediaFormat], duration: float | None) -> None:
    opts = build_options(formats, duration)
    ids = [o.id for o in opts]
    assert len(ids) == len(set(ids))
    assert sum(o.is_default for o in opts) <= 1
    known = {f.format_id for f in formats}
    for o in opts:
        assert o.video_format_id is None or o.video_format_id in known
        assert o.audio_format_id is None or o.audio_format_id in known
        # Every advertised option is resolvable again (download-time recomputation).
        assert resolve_option(o.id, formats, duration).id == o.id
