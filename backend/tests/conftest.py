import ipaddress
import shutil
from pathlib import Path

import pytest

from downloader.security.netpolicy import IPAddress

HAS_FFMPEG = shutil.which("ffmpeg") is not None
requires_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")


class FakeDNS:  # shared with tests/integration
    """Deterministic resolver for proxy tests; records every lookup."""

    def __init__(self, table: dict[str, list[str]]) -> None:
        self.table = table
        self.calls: list[str] = []

    async def __call__(self, host: str, port: int) -> list[IPAddress]:
        self.calls.append(host)
        if host not in self.table:
            raise OSError("NXDOMAIN")
        return [ipaddress.ip_address(a) for a in self.table[host]]


@pytest.fixture
def scratch(tmp_path: Path) -> Path:
    path = tmp_path / "scratch"
    path.mkdir()
    return path
