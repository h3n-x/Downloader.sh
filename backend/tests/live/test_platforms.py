"""Live checks against real platforms. Opt-in: ``uv run pytest -m live``.

Never part of the default suite: platforms change, rate-limit and geo-block, and a
failure here signals "update yt-dlp / adjust mapping", not a regression in our code.
Uses the real worker + egress proxy, exactly like production.
"""

from pathlib import Path

import pytest

from downloader.infra.egress_proxy import EgressProxy
from downloader.infra.worker_launcher import WorkerRunner
from downloader.worker.protocol import WorkerLimits

pytestmark = pytest.mark.live

# Long-lived, public, uploader-published items. Replace if they disappear.
CASES = [
    ("youtube", "https://www.youtube.com/watch?v=jNQXAC9IVRw"),  # "Me at the zoo"
    ("vimeo", "https://vimeo.com/76979871"),  # Vimeo staff demo
]


@pytest.mark.parametrize(("provider", "url"), CASES)
async def test_inspect_real_platform(provider: str, url: str, tmp_path: Path) -> None:
    proxy = EgressProxy()
    await proxy.start()
    try:
        runner = WorkerRunner(
            proxy,
            providers=(provider,),
            limits=WorkerLimits(max_filesize=500_000_000, max_duration=3600),
            scratch_dir=tmp_path,
        )
        info = await runner.inspect(url, time_limit=90)
    finally:
        await proxy.close()
    assert info.title
    assert info.formats
