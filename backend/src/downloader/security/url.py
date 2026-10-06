"""User URL validation and normalisation.

This is the *first* SSRF barrier (fast feedback, rejects obvious abuse). The
authoritative barrier is the egress proxy, which re-checks every connection the
worker makes, including redirects and CDN hosts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final
from urllib.parse import quote, urlsplit, urlunsplit

from downloader.domain.errors import AppError, ErrorCode
from downloader.security.netpolicy import IPAddress, is_public_ip, parse_ip

MAX_URL_LENGTH: Final = 2048
ALLOWED_SCHEMES: Final = frozenset({"http", "https"})
ALLOWED_PORTS: Final = frozenset({80, 443})

_LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")
_SCHEME_PREFIX = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")
_FORBIDDEN_CHARS = re.compile(r"[\x00-\x20\x7f\\]")
_RESERVED_SUFFIXES: Final = (
    ".localhost",
    ".local",
    ".internal",
    ".intranet",
    ".lan",
    ".home.arpa",
    ".corp",
    ".arpa",
)
_PATH_SAFE: Final = "/%:@!$&'()*+,;=-._~"
_QUERY_SAFE: Final = _PATH_SAFE + "?"


@dataclass(frozen=True, slots=True)
class ValidatedUrl:
    url: str
    scheme: str
    host: str
    port: int | None
    ip: IPAddress | None


def _invalid(detail: str) -> AppError:
    return AppError(ErrorCode.INVALID_URL, detail=detail)


def _normalize_host(raw: str) -> str:
    host = raw.lower().removesuffix(".")
    if not host:
        raise _invalid("empty host")
    if not host.isascii():
        try:
            host = host.encode("idna").decode("ascii")
        except UnicodeError as exc:
            raise _invalid("bad IDN host") from exc
    if len(host) > 253:
        raise _invalid("host too long")
    return host


def _validate_host(hostname: str) -> tuple[str, str, IPAddress | None]:
    """Return (host, host as written in netloc, ip literal or None)."""
    ip = parse_ip(hostname)
    if ip is not None:
        if not is_public_ip(ip):
            raise AppError(ErrorCode.URL_NOT_ALLOWED, detail="non-public IP literal")
        host = ip.compressed
        return host, (f"[{host}]" if ip.version == 6 else host), ip

    host = _normalize_host(hostname)
    labels = host.split(".")
    if not all(_LABEL.match(label) for label in labels):
        raise _invalid("bad hostname")
    # Reject numeric-looking hosts that resolvers may interpret as IPv4 (e.g. "2130706433").
    if labels[-1].isdigit():
        raise _invalid("numeric TLD")
    if len(labels) < 2 or host == "localhost" or host.endswith(_RESERVED_SUFFIXES):
        raise AppError(ErrorCode.URL_NOT_ALLOWED, detail="internal hostname")
    return host, host, None


def validate_url(raw: str) -> ValidatedUrl:
    """Validate and normalise a user-supplied URL or raise `AppError`."""
    candidate = raw.strip()
    if not candidate:
        raise _invalid("empty")
    if len(candidate) > MAX_URL_LENGTH:
        raise _invalid("too long")
    if _FORBIDDEN_CHARS.search(candidate):
        raise _invalid("control, space or backslash characters")
    if not _SCHEME_PREFIX.match(candidate) or candidate.lower().startswith(("localhost:",)):
        # Friendly: accept "youtube.com/watch?v=…" pasted without a scheme.
        candidate = "https://" + candidate.removeprefix("//")

    try:
        parts = urlsplit(candidate)
        port = parts.port
    except ValueError as exc:
        raise _invalid("unparseable") from exc

    scheme = parts.scheme.lower()
    if scheme not in ALLOWED_SCHEMES:
        raise _invalid(f"scheme {scheme!r} not allowed")
    if "@" in parts.netloc:
        # userinfo enables parser-confusion tricks (http://good.com@evil) and leaks credentials.
        raise _invalid("credentials in URL")
    if parts.hostname is None:
        raise _invalid("missing host")
    if port is not None and port not in ALLOWED_PORTS:
        raise AppError(ErrorCode.URL_NOT_ALLOWED, detail=f"port {port}")

    host, netloc_host, ip = _validate_host(parts.hostname)
    netloc = netloc_host if port is None else f"{netloc_host}:{port}"
    path = quote(parts.path or "/", safe=_PATH_SAFE)
    query = quote(parts.query, safe=_QUERY_SAFE)
    url = urlunsplit((scheme, netloc, path, query, ""))
    return ValidatedUrl(url=url, scheme=scheme, host=host, port=port, ip=ip)
