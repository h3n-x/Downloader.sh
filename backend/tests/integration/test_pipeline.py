"""Worker process + egress proxy + yt-dlp + FFmpeg, fully offline."""

import asyncio
import ipaddress
import subprocess
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from downloader.domain.errors import AppError, ErrorCode
from downloader.domain.models import MediaInfo
from downloader.extraction import ytdlp as adapter
from downloader.extraction.base import ExtractionContext
from downloader.infra.egress_proxy import EgressProxy
from downloader.infra.worker_launcher import WorkerRunner
from downloader.security import url as url_mod
from downloader.security.netpolicy import is_public_ip
from downloader.worker.protocol import Phase, ProgressEvent, WorkerLimits
from tests.conftest import FakeDNS, requires_ffmpeg

LIMITS = WorkerLimits(max_filesize=50_000_000, max_duration=3600)
pytestmark = pytest.mark.slow


@pytest.fixture
async def blocked_runner(scratch: Path) -> AsyncIterator[WorkerRunner]:
    dns = FakeDNS({"www.youtube.com": ["10.0.0.1"], "youtube.com": ["10.0.0.1"]})
    proxy = EgressProxy(resolver=dns)
    await proxy.start()
    yield WorkerRunner(proxy, providers=("youtube",), limits=LIMITS, scratch_dir=scratch)
    await proxy.close()


async def test_worker_traffic_is_forced_through_proxy(blocked_runner: WorkerRunner) -> None:
    with pytest.raises(AppError) as exc:
        await blocked_runner.inspect("https://www.youtube.com/watch?v=dQw4w9WgXcQ", time_limit=60)
    assert exc.value.code is ErrorCode.URL_NOT_ALLOWED


async def test_worker_timeout_kills_process(blocked_runner: WorkerRunner) -> None:
    with pytest.raises(AppError) as exc:
        await blocked_runner.inspect("https://www.youtube.com/watch?v=dQw4w9WgXcQ", time_limit=0.2)
    assert exc.value.code is ErrorCode.TIMEOUT


# --- real download through the proxy using a local origin -----------------------------


@pytest.fixture(scope="module")
def sample_mp4(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("media") / "sample.mp4"
    subprocess.run(
        [
            "ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i",
            "testsrc=duration=2:size=320x240:rate=15", "-f", "lavfi", "-i",
            "sine=frequency=440:duration=2", "-c:v", "libx264", "-preset", "ultrafast",
            "-c:a", "aac", "-shortest", "-movflags", "+faststart", str(out),
        ],
        check=True,
    )  # fmt: skip
    return out


@pytest.fixture
async def origin(sample_mp4: Path) -> AsyncIterator[int]:
    body = sample_mp4.read_bytes()

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            head = await reader.readuntil(b"\r\n\r\n")
            writer.write(
                b"HTTP/1.1 200 OK\r\nContent-Type: video/mp4\r\nContent-Length: %d\r\n"
                b"Connection: close\r\n\r\n" % len(body)
            )
            if not head.startswith(b"HEAD"):
                writer.write(body)
            await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    yield server.sockets[0].getsockname()[1]
    server.close()
    await server.wait_closed()


@pytest.fixture
async def local_proxy(origin: int) -> AsyncIterator[EgressProxy]:
    loopback = ipaddress.IPv4Address("127.0.0.1")
    proxy = EgressProxy(
        allowed_ports=frozenset({origin}),
        resolver=FakeDNS({"media.test": ["127.0.0.1"]}),
        policy=lambda ip: ip == loopback or is_public_ip(ip),
    )
    await proxy.start()
    yield proxy
    await proxy.close()


@requires_ffmpeg
@pytest.mark.parametrize(("option_id", "ext"), [("video", "mp4"), ("audio", "m4a")])
async def test_download_through_proxy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    origin: int,
    local_proxy: EgressProxy,
    sample_mp4: Path,
    option_id: str,
    ext: str,
) -> None:
    # Test-only: allow the Generic extractor and the origin's ephemeral port.
    monkeypatch.setitem(adapter.EXTRACTORS, "streamable", ("generic",))
    monkeypatch.setattr(url_mod, "ALLOWED_PORTS", frozenset({80, 443, origin}))
    lease = local_proxy.issue(10_000_000)
    ctx = ExtractionContext(local_proxy.url_for(lease), ("streamable",), LIMITS)
    infos: list[MediaInfo] = []
    progress: list[ProgressEvent] = []
    extractor = adapter.YtDlpExtractor(log=lambda _msg: None)

    result = await asyncio.to_thread(
        extractor.download,
        f"http://media.test:{origin}/sample.mp4",
        option_id,
        tmp_path,
        ctx,
        on_info=infos.append,
        on_progress=progress.append,
    )

    assert result.path.parent == tmp_path
    assert result.path.name == f"media.{ext}"
    assert result.ext == ext
    assert result.size > 1000
    assert infos
    assert infos[0].formats
    assert any(p.phase is Phase.DOWNLOADING for p in progress)
    assert lease.bytes_in >= sample_mp4.stat().st_size
    if option_id == "audio":
        assert any(p.phase is Phase.PROCESSING for p in progress)
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,codec_name",
             "-of", "csv=p=0", str(result.path)],
            check=True, capture_output=True, text=True,
        )  # fmt: skip
        assert probe.stdout.strip() == "aac,audio"  # copied, not transcoded


@requires_ffmpeg
async def test_download_respects_byte_budget(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, origin: int, local_proxy: EgressProxy
) -> None:
    monkeypatch.setitem(adapter.EXTRACTORS, "streamable", ("generic",))
    monkeypatch.setattr(url_mod, "ALLOWED_PORTS", frozenset({80, 443, origin}))
    lease = local_proxy.issue(byte_limit=5_000)
    ctx = ExtractionContext(local_proxy.url_for(lease), ("streamable",), LIMITS)
    extractor = adapter.YtDlpExtractor(log=lambda _msg: None)
    with pytest.raises(AppError):
        await asyncio.to_thread(
            extractor.download,
            f"http://media.test:{origin}/sample.mp4",
            "video",
            tmp_path,
            ctx,
            on_info=lambda _i: None,
            on_progress=lambda _p: None,
        )
    assert lease.exceeded
