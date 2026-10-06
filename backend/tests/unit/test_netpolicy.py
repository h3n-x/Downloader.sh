import ipaddress

import pytest
from hypothesis import given
from hypothesis import strategies as st

from downloader.security.netpolicy import is_public_ip, parse_ip

BLOCKED = [
    "127.0.0.1",
    "127.255.255.254",
    "0.0.0.0",
    "10.0.0.1",
    "172.16.0.1",
    "172.31.255.255",
    "192.168.1.1",
    "169.254.169.254",  # cloud metadata
    "100.64.0.1",  # CGNAT
    "100.100.100.200",  # Alibaba metadata (CGNAT range)
    "192.0.0.9",
    "192.0.2.1",
    "198.18.0.1",
    "198.51.100.1",
    "203.0.113.1",
    "224.0.0.1",
    "239.255.255.250",
    "240.0.0.1",
    "255.255.255.255",
    "192.88.99.1",
    "::",
    "::1",
    "fe80::1",
    "fc00::1",
    "fd00:ec2::254",  # AWS IPv6 metadata
    "ff02::1",
    "ff0e::1",  # multicast (is_global=True on CPython!)
    "::ffff:127.0.0.1",
    "::ffff:10.0.0.1",
    "::ffff:169.254.169.254",
    "64:ff9b::7f00:1",  # NAT64 → 127.0.0.1 (is_global=True on CPython!)
    "64:ff9b::a9fe:a9fe",  # NAT64 → 169.254.169.254
    "64:ff9b:1::1",
    "2002:7f00:1::",
    "2002:c0a8:101::",  # 6to4 wrapping private v4
    "2001:0:4136:e378:8000:63bf:3fff:fdd2",  # Teredo
    "2001:db8::1",
]

ALLOWED = [
    "8.8.8.8",
    "1.1.1.1",
    "142.250.0.1",
    "2606:4700::1111",
    "2a00:1450:4001::200e",
    "::ffff:8.8.8.8",
]


@pytest.mark.parametrize("addr", BLOCKED)
def test_blocks_non_public(addr: str) -> None:
    assert not is_public_ip(ipaddress.ip_address(addr))


@pytest.mark.parametrize("addr", ALLOWED)
def test_allows_public(addr: str) -> None:
    assert is_public_ip(ipaddress.ip_address(addr))


def test_scoped_ipv6_is_blocked() -> None:
    assert not is_public_ip(ipaddress.IPv6Address("fe80::1%eth0"))


def test_parse_ip_handles_brackets_and_hostnames() -> None:
    assert parse_ip("[::1]") == ipaddress.IPv6Address("::1")
    assert parse_ip("10.0.0.1") == ipaddress.IPv4Address("10.0.0.1")
    assert parse_ip("example.com") is None


@given(st.ip_addresses(v=4))
def test_mapped_v4_has_same_verdict_as_v4(ip: ipaddress.IPv4Address) -> None:
    mapped = ipaddress.IPv6Address(f"::ffff:{ip}")
    nat64 = ipaddress.IPv6Address(int(ipaddress.IPv6Address("64:ff9b::")) | int(ip))
    assert is_public_ip(mapped) == is_public_ip(ip)
    assert is_public_ip(nat64) == is_public_ip(ip)


@given(st.ip_addresses())
def test_public_implies_global_unicast(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
    if is_public_ip(ip):
        assert not ip.is_multicast
        assert not ip.is_loopback
        assert not ip.is_private
        assert not ip.is_link_local
