import asyncio
from pathlib import Path

import pytest

from downloader.app.inspect import InspectService
from downloader.app.jobs import JobLimits, JobManager
from downloader.domain.errors import AppError, ErrorCode
from downloader.domain.providers import PROVIDERS, ProviderRegistry
from downloader.domain.quality import Limits
from downloader.infra.storage import JobStorage
from downloader.worker.protocol import Phase
from tests.fakes import FakeBackend

URL = "https://www.youtube.com/watch?v=abc123"


def make_inspector(
    backend: FakeBackend, *, max_concurrent: int = 4, ttl: float = 60
) -> InspectService:
    return InspectService(
        backend,
        ProviderRegistry(PROVIDERS),
        limits=Limits(max_filesize=10**9, max_duration=3600),
        time_limit=10,
        max_concurrent=max_concurrent,
        cache_ttl=ttl,
    )


class Clock:
    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now


def make_manager(
    backend: FakeBackend, root: Path, *, clock: Clock | None = None, **limits: float
) -> tuple[JobManager, JobStorage]:
    storage = JobStorage(root / "jobs")
    storage.prepare()
    defaults: dict[str, float] = {
        "max_concurrent": 2, "max_queued": 2, "max_per_client": 2,
        "disk_quota": 10**9, "time_limit": 30, "ttl": 60,
    }  # fmt: skip
    defaults.update(limits)
    manager = JobManager(
        backend,
        make_inspector(backend),
        storage,
        JobLimits(**{k: int(v) for k, v in defaults.items()}),
        clock=clock or Clock(),
    )
    return manager, storage


async def settle(manager: JobManager, job_id: str) -> Phase:
    job = manager.get(job_id)
    assert job.task is not None
    await asyncio.wait_for(asyncio.shield(job.task), 5)
    return job.phase


# --- inspect -----------------------------------------------------------------


async def test_inspect_returns_options() -> None:
    result = await make_inspector(FakeBackend()).inspect(URL)
    assert result.provider.slug == "youtube"
    assert [o.id for o in result.options] == ["v1080", "v720", "audio"]


@pytest.mark.parametrize(
    ("url", "code"),
    [
        ("https://example.org/video", ErrorCode.UNSUPPORTED_SITE),
        ("http://127.0.0.1/", ErrorCode.URL_NOT_ALLOWED),
        ("javascript:alert(1)", ErrorCode.INVALID_URL),
    ],
)
async def test_inspect_rejects_before_spawning(url: str, code: ErrorCode) -> None:
    backend = FakeBackend()
    with pytest.raises(AppError) as exc:
        await make_inspector(backend).inspect(url)
    assert exc.value.code is code
    assert backend.inspect_calls == 0


async def test_inspect_cache_and_single_flight() -> None:
    backend = FakeBackend()
    backend.inspect_gate = asyncio.Event()
    service = make_inspector(backend)
    first = asyncio.create_task(service.inspect(URL))
    second = asyncio.create_task(service.inspect(URL + "#fragment"))  # same normalized URL
    await asyncio.sleep(0)
    backend.inspect_gate.set()
    await asyncio.gather(first, second)
    await service.inspect(URL)
    assert backend.inspect_calls == 1


async def test_inspect_errors_are_not_cached() -> None:
    backend = FakeBackend()
    backend.inspect_error = AppError(ErrorCode.PLATFORM_BLOCKED)
    service = make_inspector(backend)
    for _ in range(2):
        with pytest.raises(AppError):
            await service.inspect(URL)
    assert backend.inspect_calls == 2


async def test_inspect_backpressure() -> None:
    backend = FakeBackend()
    backend.inspect_gate = asyncio.Event()
    service = make_inspector(backend, max_concurrent=1, ttl=0)
    tasks = [asyncio.create_task(service.inspect(f"{URL}{i}")) for i in range(3)]
    await asyncio.sleep(0.01)
    with pytest.raises(AppError) as exc:
        await service.inspect(URL + "x")
    assert exc.value.code is ErrorCode.SERVER_BUSY
    backend.inspect_gate.set()
    await asyncio.gather(*tasks)


# --- jobs --------------------------------------------------------------------


async def test_job_happy_path_and_ttl(tmp_path: Path) -> None:
    clock = Clock()
    manager, storage = make_manager(FakeBackend(), tmp_path, clock=clock)
    job = manager.submit(URL, "v1080", "client-a")
    assert await settle(manager, job.id) is Phase.READY
    view = job.view()
    assert view.title == "Sample <b>title</b>"
    assert view.file_ext == "mp4"
    _job, path = manager.ready_file(job.id)
    assert path.read_bytes().startswith(b"\x00\x00\x00\x18ftyp")
    clock.now += 61
    manager.reap()
    assert job.phase is Phase.EXPIRED
    assert not path.exists()
    with pytest.raises(AppError) as exc:
        manager.ready_file(job.id)
    assert exc.value.code is ErrorCode.JOB_EXPIRED
    assert storage.usage_bytes() == 0


async def test_job_failure_cleans_up(tmp_path: Path) -> None:
    backend = FakeBackend()
    backend.download_error = AppError(ErrorCode.CONTENT_PRIVATE)
    manager, storage = make_manager(backend, tmp_path)
    job = manager.submit(URL, "v720", "c")
    assert await settle(manager, job.id) is Phase.FAILED
    assert job.error_code is ErrorCode.CONTENT_PRIVATE
    assert list(storage.root.iterdir()) == []


async def test_cancel_kills_and_cleans(tmp_path: Path) -> None:
    backend = FakeBackend()
    backend.download_gate = asyncio.Event()
    manager, storage = make_manager(backend, tmp_path)
    job = manager.submit(URL, "v720", "c")
    await asyncio.sleep(0.01)
    assert job.phase is Phase.DOWNLOADING
    manager.cancel(job.id)
    assert await settle(manager, job.id) is Phase.CANCELLED
    assert list(storage.root.iterdir()) == []


async def test_per_client_and_global_limits(tmp_path: Path) -> None:
    backend = FakeBackend()
    backend.download_gate = asyncio.Event()
    manager, _ = make_manager(backend, tmp_path, max_concurrent=1, max_queued=1, max_per_client=2)
    manager.submit(URL, "v720", "a")
    manager.submit(URL, "v720", "a")
    with pytest.raises(AppError) as exc:
        manager.submit(URL, "v720", "a")
    assert exc.value.code is ErrorCode.RATE_LIMITED
    with pytest.raises(AppError) as exc:
        manager.submit(URL, "v720", "b")
    assert exc.value.code is ErrorCode.SERVER_BUSY
    backend.download_gate.set()
    await manager.shutdown()


async def test_submit_validates_option_and_url(tmp_path: Path) -> None:
    manager, _ = make_manager(FakeBackend(), tmp_path)
    with pytest.raises(AppError) as exc:
        manager.submit(URL, "1+2", "c")
    assert exc.value.code is ErrorCode.VALIDATION_ERROR
    with pytest.raises(AppError) as exc:
        manager.submit("http://169.254.169.254/", "v720", "c")
    assert exc.value.code is ErrorCode.URL_NOT_ALLOWED


async def test_watch_streams_until_ready(tmp_path: Path) -> None:
    backend = FakeBackend()
    backend.download_gate = asyncio.Event()
    manager, _ = make_manager(backend, tmp_path)
    job = manager.submit(URL, "v720", "c")
    phases: list[Phase] = []

    async def consume() -> None:
        async for view in manager.watch(job.id, heartbeat=0.05):
            if view is not None:
                phases.append(view.phase)

    consumer = asyncio.create_task(consume())
    await asyncio.sleep(0.05)
    backend.download_gate.set()
    await asyncio.wait_for(consumer, 5)
    assert phases[-1] is Phase.READY
    assert Phase.DOWNLOADING in phases


async def test_disk_quota(tmp_path: Path) -> None:
    manager, storage = make_manager(FakeBackend(), tmp_path, disk_quota=10)
    (storage.root / "leftover").mkdir()
    (storage.root / "leftover" / "f").write_bytes(b"x" * 100)
    with pytest.raises(AppError) as exc:
        manager.submit(URL, "v720", "c")
    assert exc.value.code is ErrorCode.SERVER_BUSY


def test_storage_refuses_outside_paths(tmp_path: Path) -> None:
    storage = JobStorage(tmp_path / "jobs")
    storage.prepare()
    victim = tmp_path / "victim"
    victim.mkdir()
    (storage.root / "link").symlink_to(victim)
    storage.remove(storage.root / "link")
    storage.remove(victim)
    assert victim.exists()
