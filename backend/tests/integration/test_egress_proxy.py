"""Egress proxy security tests against a local upstream (no Internet)."""

import asyncio
import base64
import ipaddress
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import pytest

from downloader.infra.egress_proxy import Denial, EgressProxy, Lease
from tests.conftest import FakeDNS

LOOPBACK = ipaddress.IPv4Address("127.0.0.1")


@dataclass
class Upstream:
    port: int
    requests: list[bytes] = field(default_factory=list)
    body: bytes = b"hello"


@pytest.fixture
async def upstream() -> AsyncIterator[Upstream]:
    state = Upstream(port=0)

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            head = await reader.readuntil(b"\r\n\r\n")
            state.requests.append(head)
            writer.write(
                b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\nConnection: close\r\n\r\n"
                % len(state.body)
                + state.body
            )
            await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    state.port = server.sockets[0].getsockname()[1]
    yield state
    server.close()
    await server.wait_closed()


async def make_proxy(
    dns: FakeDNS, *, ports: frozenset[int], allow_loopback: bool = False
) -> EgressProxy:
    from downloader.security.netpolicy import is_public_ip

    policy = (lambda ip: ip == LOOPBACK or is_public_ip(ip)) if allow_loopback else is_public_ip
    proxy = EgressProxy(allowed_ports=ports, resolver=dns, policy=policy, connect_timeout=2)
    await proxy.start()
    return proxy


def auth(lease: Lease) -> str:
    return "Basic " + base64.b64encode(f"job:{lease.token}".encode()).decode()


async def send(proxy: EgressProxy, request: str) -> bytes:
    port = int(proxy.url_for(proxy.issue(1)).rsplit(":", 1)[1])
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(request.encode())
    await writer.drain()
    data = await asyncio.wait_for(reader.read(), 5)
    writer.close()
    return data


async def test_requires_authentication() -> None:
    proxy = await make_proxy(FakeDNS({}), ports=frozenset({443}))
    try:
        resp = await send(proxy, "CONNECT example.com:443 HTTP/1.1\r\n\r\n")
        assert resp.startswith(b"HTTP/1.1 407")
        bogus = base64.b64encode(b"job:nope").decode()
        resp = await send(
            proxy, f"CONNECT example.com:443 HTTP/1.1\r\nProxy-Authorization: Basic {bogus}\r\n\r\n"
        )
        assert resp.startswith(b"HTTP/1.1 407")
    finally:
        await proxy.close()


@pytest.mark.parametrize(
    ("target", "dns", "denial"),
    [
        ("127.0.0.1:443", {}, Denial.BLOCKED_DESTINATION),
        ("[::1]:443", {}, Denial.BLOCKED_DESTINATION),
        ("169.254.169.254:80", {}, Denial.BLOCKED_DESTINATION),
        ("internal.test:443", {"internal.test": ["10.0.0.5"]}, Denial.BLOCKED_DESTINATION),
        ("mixed.test:443", {"mixed.test": ["8.8.8.8", "127.0.0.1"]}, Denial.BLOCKED_DESTINATION),
        ("nat64.test:443", {"nat64.test": ["64:ff9b::a9fe:a9fe"]}, Denial.BLOCKED_DESTINATION),
        ("example.com:22", {"example.com": ["8.8.8.8"]}, Denial.BLOCKED_PORT),
        ("example.com:6379", {"example.com": ["8.8.8.8"]}, Denial.BLOCKED_PORT),
        ("nxdomain.test:443", {}, Denial.DNS_FAILURE),
    ],
)
async def test_connect_denials(target: str, dns: dict[str, list[str]], denial: Denial) -> None:
    proxy = await make_proxy(FakeDNS(dns), ports=frozenset({80, 443}))
    lease = proxy.issue(10_000)
    try:
        port = int(proxy.url_for(lease).rsplit(":", 1)[1])
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(
            f"CONNECT {target} HTTP/1.1\r\nProxy-Authorization: {auth(lease)}\r\n\r\n".encode()
        )
        resp = await asyncio.wait_for(reader.read(), 5)
        writer.close()
        assert resp.split(b" ")[1] in {b"403", b"502"}
        assert lease.denials == [denial]
        assert lease.blocked is (denial in {Denial.BLOCKED_DESTINATION, Denial.BLOCKED_PORT})
    finally:
        await proxy.close()


async def test_plain_http_to_private_ip_is_denied() -> None:
    proxy = await make_proxy(FakeDNS({}), ports=frozenset({80}))
    lease = proxy.issue(10_000)
    try:
        port = int(proxy.url_for(lease).rsplit(":", 1)[1])
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(
            "GET http://169.254.169.254/latest/meta-data/ HTTP/1.1\r\n"
            f"Host: 169.254.169.254\r\nProxy-Authorization: {auth(lease)}\r\n\r\n".encode()
        )
        resp = await asyncio.wait_for(reader.read(), 5)
        writer.close()
        assert resp.startswith(b"HTTP/1.1 403")
        assert lease.blocked
    finally:
        await proxy.close()


async def test_connect_tunnel_pins_resolved_ip(upstream: Upstream) -> None:
    dns = FakeDNS({"media.test": ["127.0.0.1"]})
    proxy = await make_proxy(dns, ports=frozenset({upstream.port}), allow_loopback=True)
    lease = proxy.issue(10_000)
    try:
        port = int(proxy.url_for(lease).rsplit(":", 1)[1])
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(
            f"CONNECT media.test:{upstream.port} HTTP/1.1\r\n"
            f"Proxy-Authorization: {auth(lease)}\r\n\r\n".encode()
        )
        established = await reader.readuntil(b"\r\n\r\n")
        assert established.startswith(b"HTTP/1.1 200")
        writer.write(b"GET /x HTTP/1.1\r\nHost: media.test\r\n\r\n")
        resp = await asyncio.wait_for(reader.read(), 5)
        assert resp.endswith(b"hello")
        assert dns.calls == ["media.test"]  # resolved exactly once
        assert lease.bytes_in == len(resp)
        writer.close()
    finally:
        await proxy.close()


async def test_plain_http_forward_strips_proxy_credentials(upstream: Upstream) -> None:
    proxy = await make_proxy(
        FakeDNS({"media.test": ["127.0.0.1"]}),
        ports=frozenset({upstream.port}),
        allow_loopback=True,
    )
    lease = proxy.issue(10_000)
    try:
        port = int(proxy.url_for(lease).rsplit(":", 1)[1])
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(
            f"GET http://media.test:{upstream.port}/a?b=1 HTTP/1.1\r\nHost: media.test\r\n"
            f"Proxy-Authorization: {auth(lease)}\r\nProxy-Connection: keep-alive\r\n\r\n".encode()
        )
        resp = await asyncio.wait_for(reader.read(), 5)
        writer.close()
        assert resp.endswith(b"hello")
        seen = upstream.requests[0].decode()
        assert seen.startswith("GET /a?b=1 HTTP/1.1\r\n")
        assert "proxy-authorization" not in seen.lower()
        assert "Connection: close" in seen
    finally:
        await proxy.close()


async def test_byte_budget_cuts_connection(upstream: Upstream) -> None:
    upstream.body = b"x" * 500_000
    proxy = await make_proxy(
        FakeDNS({"media.test": ["127.0.0.1"]}),
        ports=frozenset({upstream.port}),
        allow_loopback=True,
    )
    lease = proxy.issue(byte_limit=50_000)
    try:
        port = int(proxy.url_for(lease).rsplit(":", 1)[1])
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(
            f"GET http://media.test:{upstream.port}/big HTTP/1.1\r\n"
            f"Proxy-Authorization: {auth(lease)}\r\n\r\n".encode()
        )
        received = await asyncio.wait_for(reader.read(), 5)
        writer.close()
        assert len(received) < 200_000
        assert lease.exceeded
    finally:
        await proxy.close()


async def test_revoked_lease_is_rejected() -> None:
    proxy = await make_proxy(FakeDNS({}), ports=frozenset({443}))
    lease = proxy.issue(10_000)
    proxy.revoke(lease)
    try:
        port = int(proxy.url_for(lease).rsplit(":", 1)[1])
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(
            f"CONNECT a.test:443 HTTP/1.1\r\nProxy-Authorization: {auth(lease)}\r\n\r\n".encode()
        )
        resp = await asyncio.wait_for(reader.read(), 5)
        writer.close()
        assert resp.startswith(b"HTTP/1.1 407")
    finally:
        await proxy.close()


async def test_garbage_and_oversized_heads_are_dropped() -> None:
    proxy = await make_proxy(FakeDNS({}), ports=frozenset({443}))
    try:
        assert (await send(proxy, "NOT HTTP\r\n\r\n")).startswith(b"HTTP/1.1 4")
        resp = await send(proxy, "GET / HTTP/1.1\r\nX: " + "a" * 20_000 + "\r\n\r\n")
        assert resp == b""
    finally:
        await proxy.close()


async def test_ytdlp_networking_uses_proxy_with_credentials(upstream: Upstream) -> None:
    """The real yt-dlp HTTP stack must route through the proxy and authenticate."""
    from yt_dlp import YoutubeDL

    dns = FakeDNS({"media.test": ["127.0.0.1"]})
    proxy = await make_proxy(dns, ports=frozenset({upstream.port}), allow_loopback=True)
    lease = proxy.issue(10_000)

    def fetch() -> bytes:
        with YoutubeDL({"proxy": proxy.url_for(lease), "quiet": True}) as ydl:
            return bytes(ydl.urlopen(f"http://media.test:{upstream.port}/probe").read())

    try:
        body = await asyncio.to_thread(fetch)
        assert body == b"hello"
        assert dns.calls == ["media.test"]  # resolution happened in the proxy, not the client
    finally:
        await proxy.close()
