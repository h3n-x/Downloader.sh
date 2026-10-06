"""Egress proxy: the authoritative SSRF barrier for worker traffic.

Every outbound connection of a worker (page fetches, API calls, redirects, HLS/DASH
fragments, CDN downloads) is forced through this proxy via yt-dlp's ``proxy`` option.

Per connection it:
1. authenticates the job lease (random token, revoked when the job ends);
2. allows only configured ports (80/443);
3. resolves DNS *once* and refuses if *any* answer is non-public;
4. connects to the already-validated IP (no second resolution ⇒ no DNS rebinding);
5. counts downstream bytes and cuts the lease off above its byte budget.

CONNECT tunnels keep TLS end-to-end (certificate validation stays in the client).
Plain-HTTP absolute-form requests are rewritten to origin-form and forwarded.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import contextlib
import logging
import secrets
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final
from urllib.parse import urlsplit

from downloader.security.netpolicy import IPAddress, is_public_ip, parse_ip

log = logging.getLogger(__name__)

type Resolver = Callable[[str, int], Awaitable[list[IPAddress]]]
type IPPolicy = Callable[[IPAddress], bool]

_MAX_HEAD: Final = 16 * 1024
_CHUNK: Final = 64 * 1024
_HOP_HEADERS: Final = frozenset(
    {"proxy-authorization", "proxy-connection", "connection", "keep-alive", "te", "upgrade"}
)


class Denial(StrEnum):
    BLOCKED_DESTINATION = "blocked_destination"
    BLOCKED_PORT = "blocked_port"
    BAD_REQUEST = "bad_request"
    DNS_FAILURE = "dns_failure"
    CONNECT_FAILURE = "connect_failure"


class _QuotaExceededError(Exception):
    pass


@dataclass(eq=False)
class Lease:
    token: str
    byte_limit: int
    max_connections: int
    bytes_in: int = 0
    exceeded: bool = False
    denials: list[Denial] = field(default_factory=list)
    writers: set[asyncio.StreamWriter] = field(default_factory=set)

    @property
    def blocked(self) -> bool:
        return any(
            d in {Denial.BLOCKED_DESTINATION, Denial.BLOCKED_PORT, Denial.BAD_REQUEST}
            for d in self.denials
        )

    def count(self, n: int) -> None:
        self.bytes_in += n
        if self.bytes_in > self.byte_limit:
            self.exceeded = True
            raise _QuotaExceededError


async def system_resolver(host: str, port: int) -> list[IPAddress]:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    out: list[IPAddress] = []
    for _family, _type, _proto, _canon, sockaddr in infos:
        ip = parse_ip(str(sockaddr[0]))
        if ip is not None and ip not in out:
            out.append(ip)
    return out


class _RequestError(Exception):
    def __init__(self, status: int, reason: str, denial: Denial | None = None) -> None:
        super().__init__(reason)
        self.status = status
        self.reason = reason
        self.denial = denial


@dataclass(frozen=True, slots=True)
class _Head:
    method: str
    target: str
    version: str
    headers: list[tuple[str, str]]


def _parse_head(raw: bytes) -> _Head:
    try:
        text = raw.decode("latin-1")
        request_line, *header_lines = text.split("\r\n")
        method, target, version = request_line.split(" ")
    except ValueError as exc:
        raise _RequestError(400, "Bad Request", Denial.BAD_REQUEST) from exc
    if not version.startswith("HTTP/1."):
        raise _RequestError(400, "Bad Request", Denial.BAD_REQUEST)
    headers: list[tuple[str, str]] = []
    for line in header_lines:
        if not line:
            continue
        name, sep, value = line.partition(":")
        if not sep or not name or name != name.strip():
            raise _RequestError(400, "Bad Request", Denial.BAD_REQUEST)
        headers.append((name, value.strip()))
    return _Head(method.upper(), target, version, headers)


async def _reject(writer: asyncio.StreamWriter, exc: _RequestError) -> None:
    with contextlib.suppress(ConnectionError):
        writer.write(f"HTTP/1.1 {exc.status} {exc.reason}\r\nContent-Length: 0\r\n".encode())
        if exc.status == 407:
            writer.write(b'Proxy-Authenticate: Basic realm="egress"\r\n')
        writer.write(b"Connection: close\r\n\r\n")
        await writer.drain()


@dataclass(eq=False)
class _Conn:
    """Sockets of one proxied connection, registered on the lease for revocation."""

    client: asyncio.StreamWriter
    lease: Lease | None = None
    upstream: asyncio.StreamWriter | None = None

    def attach(self, lease: Lease) -> Lease:
        if len(lease.writers) >= lease.max_connections:
            raise _RequestError(429, "Too Many Connections")
        self.lease = lease
        lease.writers.add(self.client)
        return lease

    def attach_upstream(self, upstream: asyncio.StreamWriter) -> None:
        self.upstream = upstream
        if self.lease is not None:
            self.lease.writers.add(upstream)

    def close(self) -> None:
        for w in (self.client, self.upstream):
            if w is None:
                continue
            if self.lease is not None:
                self.lease.writers.discard(w)
            w.close()


class EgressProxy:
    def __init__(
        self,
        *,
        allowed_ports: frozenset[int] = frozenset({80, 443}),
        resolver: Resolver = system_resolver,
        policy: IPPolicy = is_public_ip,
        connect_timeout: float = 10.0,
        idle_timeout: float = 60.0,
        on_denial: Callable[[Denial], None] | None = None,
    ) -> None:
        self._allowed_ports = allowed_ports
        self._resolve = resolver
        self._policy = policy
        self._connect_timeout = connect_timeout
        self._idle_timeout = idle_timeout
        self._on_denial = on_denial
        self._leases: dict[str, Lease] = {}
        self._server: asyncio.Server | None = None
        self._port = 0

    async def start(self, host: str = "127.0.0.1", port: int = 0) -> None:
        self._server = await asyncio.start_server(self._handle, host, port, limit=_MAX_HEAD)
        self._port = self._server.sockets[0].getsockname()[1]

    @property
    def running(self) -> bool:
        return self._server is not None and self._server.is_serving()

    async def close(self) -> None:
        for lease in list(self._leases.values()):
            self.revoke(lease)
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    def issue(self, byte_limit: int, max_connections: int = 32) -> Lease:
        lease = Lease(secrets.token_urlsafe(32), byte_limit, max_connections)
        self._leases[lease.token] = lease
        return lease

    def url_for(self, lease: Lease) -> str:
        return f"http://job:{lease.token}@127.0.0.1:{self._port}"

    def revoke(self, lease: Lease) -> None:
        self._leases.pop(lease.token, None)
        for writer in list(lease.writers):
            writer.close()

    # --- connection handling -------------------------------------------------

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        conn = _Conn(writer)
        try:
            await self._serve(reader, conn)
        except _RequestError as exc:
            self._record(conn.lease, exc)
            await _reject(writer, exc)
        except (
            ConnectionError,
            TimeoutError,
            asyncio.IncompleteReadError,
            asyncio.LimitOverrunError,
        ):
            pass
        finally:
            conn.close()

    async def _serve(self, reader: asyncio.StreamReader, conn: _Conn) -> None:
        raw = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), self._connect_timeout)
        head = _parse_head(raw[:-4])
        lease = conn.attach(self._authenticate(head))
        host, port, forward = self._target(head)
        up_reader, upstream = await self._connect(host, port)
        conn.attach_upstream(upstream)
        if forward is None:
            conn.client.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            await conn.client.drain()
        else:
            upstream.write(forward)
            await upstream.drain()
        await self._splice(reader, conn.client, up_reader, upstream, lease)

    def _record(self, lease: Lease | None, exc: _RequestError) -> None:
        if exc.denial is None:
            return
        if lease is not None:
            lease.denials.append(exc.denial)
        if self._on_denial is not None:
            self._on_denial(exc.denial)
        log.info("egress denied", extra={"reason": exc.denial.value})

    def _authenticate(self, head: _Head) -> Lease:
        value = next((v for k, v in head.headers if k.lower() == "proxy-authorization"), "")
        scheme, _, encoded = value.partition(" ")
        if scheme.lower() == "basic":
            try:
                _user, _, token = base64.b64decode(encoded, validate=True).decode().partition(":")
            except (binascii.Error, UnicodeDecodeError):
                token = ""
            lease = self._leases.get(token)
            if lease is not None and secrets.compare_digest(lease.token, token):
                return lease
        raise _RequestError(407, "Proxy Authentication Required")

    def _target(self, head: _Head) -> tuple[str, int, bytes | None]:
        """Return (host, port, bytes to forward or None for CONNECT)."""
        if head.method == "CONNECT":
            host, sep, port_s = head.target.rpartition(":")
            if not sep or not port_s.isdigit():
                raise _RequestError(400, "Bad Request", Denial.BAD_REQUEST)
            return self._check_port(host.strip("[]"), int(port_s)), int(port_s), None
        try:
            parts = urlsplit(head.target)
            port = parts.port or 80
        except ValueError as exc:
            raise _RequestError(400, "Bad Request", Denial.BAD_REQUEST) from exc
        if parts.scheme != "http" or not parts.hostname or parts.username or parts.password:
            raise _RequestError(400, "Bad Request", Denial.BAD_REQUEST)
        host = self._check_port(parts.hostname, port)
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query
        lines = [f"{head.method} {path} {head.version}"]
        lines += [f"{k}: {v}" for k, v in head.headers if k.lower() not in _HOP_HEADERS]
        lines.append("Connection: close")
        return host, port, ("\r\n".join(lines) + "\r\n\r\n").encode("latin-1")

    def _check_port(self, host: str, port: int) -> str:
        if not host:
            raise _RequestError(400, "Bad Request", Denial.BAD_REQUEST)
        if port not in self._allowed_ports:
            raise _RequestError(403, "Forbidden", Denial.BLOCKED_PORT)
        return host

    async def _connect(
        self, host: str, port: int
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        literal = parse_ip(host)
        if literal is not None:
            addresses = [literal]
        else:
            try:
                addresses = await asyncio.wait_for(self._resolve(host, port), self._connect_timeout)
            except (OSError, TimeoutError) as exc:
                raise _RequestError(502, "Bad Gateway", Denial.DNS_FAILURE) from exc
        # Strict: one non-public answer poisons the whole name (mixed-record tricks).
        if not addresses or not all(self._policy(ip) for ip in addresses):
            raise _RequestError(403, "Forbidden", Denial.BLOCKED_DESTINATION)
        last: Exception | None = None
        for ip in addresses:
            try:
                return await asyncio.wait_for(
                    asyncio.open_connection(str(ip), port, limit=_CHUNK), self._connect_timeout
                )
            except (OSError, TimeoutError) as exc:
                last = exc
        raise _RequestError(502, "Bad Gateway", Denial.CONNECT_FAILURE) from last

    async def _splice(
        self,
        client_r: asyncio.StreamReader,
        client_w: asyncio.StreamWriter,
        up_r: asyncio.StreamReader,
        up_w: asyncio.StreamWriter,
        lease: Lease,
    ) -> None:
        async def pump(src: asyncio.StreamReader, dst: asyncio.StreamWriter, counted: bool) -> None:
            while data := await asyncio.wait_for(src.read(_CHUNK), self._idle_timeout):
                if counted:
                    lease.count(len(data))
                dst.write(data)
                await dst.drain()

        tasks = [
            asyncio.create_task(pump(client_r, up_w, counted=False)),
            asyncio.create_task(pump(up_r, client_w, counted=True)),
        ]
        try:
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for t in pending:
                t.cancel()
            for t in tasks:
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await t
            for t in done:
                if not t.cancelled() and isinstance(t.exception(), _QuotaExceededError):
                    log.info("egress byte budget exceeded")
        finally:
            for t in tasks:
                t.cancel()
