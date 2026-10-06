"""Outbound destination policy shared by URL validation and the egress proxy.

`ipaddress.is_global` alone is not sufficient (verified on CPython 3.13):
``64:ff9b::7f00:1`` (NAT64 → 127.0.0.1) and ``ff02::1`` (multicast) both report
``is_global=True``. We therefore unwrap IPv4 addresses embedded in IPv6
(IPv4-mapped, NAT64, 6to4, Teredo) and reject multicast explicitly.
"""

from __future__ import annotations

import ipaddress
from typing import Final

type IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address

_NAT64_WKP: Final = ipaddress.IPv6Network("64:ff9b::/96")
_NAT64_LOCAL: Final = ipaddress.IPv6Network("64:ff9b:1::/48")
_SIX_TO_FOUR: Final = ipaddress.IPv6Network("2002::/16")
_TEREDO: Final = ipaddress.IPv6Network("2001::/32")
_TUNNELS: Final = (_NAT64_LOCAL, _SIX_TO_FOUR, _TEREDO)

# Ranges that `is_global` treats as global but must never be reachable from a worker.
_EXTRA_BLOCKED: Final[tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]] = (
    ipaddress.IPv4Network("192.0.0.0/24"),  # IETF protocol assignments (incl. 192.0.0.9/10)
    ipaddress.IPv4Network("192.88.99.0/24"),  # deprecated 6to4 relay anycast
)


def embedded_ipv4(ip: ipaddress.IPv6Address) -> ipaddress.IPv4Address | None:
    """Return the IPv4 address tunnelled inside an IPv6 address, if any."""
    if ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    if ip in _NAT64_WKP:
        return ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    return None


def is_public_ip(ip: IPAddress) -> bool:
    """True only for unicast, globally routable destinations."""
    if isinstance(ip, ipaddress.IPv6Address):
        # Transition mechanisms (6to4, Teredo: deprecated by RFC 7526) and local-use NAT64
        # are never legitimate worker destinations; refuse them outright.
        if ip.scope_id is not None or any(ip in net for net in _TUNNELS):
            return False
        inner = embedded_ipv4(ip)
        if inner is not None:
            return is_public_ip(inner)
    if ip.is_multicast or not ip.is_global:
        return False
    return not any(ip in net for net in _EXTRA_BLOCKED if net.version == ip.version)


def parse_ip(host: str) -> IPAddress | None:
    """Parse a bare or bracketed IP literal; return None for hostnames."""
    candidate = host[1:-1] if host.startswith("[") and host.endswith("]") else host
    try:
        return ipaddress.ip_address(candidate)
    except ValueError:
        return None
