"""In-memory token-bucket rate limiting keyed by an anonymised client key.

The key is an HMAC of the client address (IPv6 collapsed to its /64, because a
single subscriber usually controls a whole /64). Raw IPs are never stored.
For multi-replica deployments swap `TokenBuckets` for a shared store (see docs).
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import math
import time
from collections.abc import Callable
from dataclasses import dataclass

from downloader.domain.errors import AppError, ErrorCode


def client_key(address: str | None, secret: bytes) -> str:
    if not address:
        normalized = "unknown"
    else:
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            normalized = address
        else:
            if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is None:
                normalized = str(ipaddress.IPv6Network(f"{ip}/64", strict=False).network_address)
            else:
                normalized = (
                    str(ip.ipv4_mapped or ip) if isinstance(ip, ipaddress.IPv6Address) else str(ip)
                )
    return hmac.new(secret, normalized.encode(), hashlib.sha256).hexdigest()[:24]


@dataclass(slots=True)
class _Bucket:
    tokens: float
    updated: float


class TokenBuckets:
    def __init__(
        self,
        name: str,
        per_minute: int,
        *,
        max_keys: int = 100_000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.name = name
        self._capacity = float(per_minute)
        self._rate = per_minute / 60.0
        self._buckets: dict[str, _Bucket] = {}
        self._max_keys = max_keys
        self._clock = clock

    def hit(self, key: str, cost: float = 1.0) -> None:
        now = self._clock()
        bucket = self._buckets.get(key)
        if bucket is None:
            if len(self._buckets) >= self._max_keys:
                self._prune(now)
            bucket = _Bucket(self._capacity, now)
            self._buckets[key] = bucket
        bucket.tokens = min(self._capacity, bucket.tokens + (now - bucket.updated) * self._rate)
        bucket.updated = now
        if bucket.tokens < cost:
            retry = math.ceil((cost - bucket.tokens) / self._rate)
            raise AppError(ErrorCode.RATE_LIMITED, detail=self.name, retry_after=max(retry, 1))
        bucket.tokens -= cost

    def _prune(self, now: float) -> None:
        full_after = self._capacity / self._rate
        stale = [k for k, b in self._buckets.items() if now - b.updated >= full_after]
        for k in stale:
            del self._buckets[k]
        if len(self._buckets) >= self._max_keys:  # under attack: drop the oldest half
            for k in sorted(self._buckets, key=lambda k: self._buckets[k].updated)[
                : self._max_keys // 2
            ]:
                del self._buckets[k]
