"""Inspect use case: validate → detect provider → (cache | single-flight) → options."""

from __future__ import annotations

import asyncio
import hashlib
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass

from downloader.app.ports import MediaBackend
from downloader.domain.errors import AppError, ErrorCode
from downloader.domain.models import MediaInfo, QualityOption
from downloader.domain.providers import Provider, ProviderRegistry
from downloader.domain.quality import Limits, build_options
from downloader.security.url import validate_url


@dataclass(frozen=True, slots=True)
class InspectResult:
    provider: Provider
    media: MediaInfo
    options: list[QualityOption]


def url_fingerprint(url: str) -> str:
    """Stable, non-reversible identifier for logs and cache keys (never log raw URLs)."""
    return hashlib.sha256(url.encode()).hexdigest()[:16]


class InspectService:
    def __init__(
        self,
        backend: MediaBackend,
        registry: ProviderRegistry,
        *,
        limits: Limits,
        time_limit: float,
        max_concurrent: int,
        cache_ttl: float,
        cache_size: int = 256,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._backend = backend
        self._registry = registry
        self._limits = limits
        self._time_limit = time_limit
        self._sem = asyncio.Semaphore(max_concurrent)
        self._max_waiting = max_concurrent * 2
        self._waiting = 0
        self._cache_ttl = cache_ttl
        self._cache_size = cache_size
        self._cache: OrderedDict[str, tuple[float, MediaInfo]] = OrderedDict()
        self._inflight: dict[str, asyncio.Future[MediaInfo]] = {}
        self._clock = clock

    @property
    def registry(self) -> ProviderRegistry:
        return self._registry

    def resolve_provider(self, raw_url: str) -> tuple[str, Provider]:
        validated = validate_url(raw_url)
        provider = self._registry.detect(validated.host)
        if provider is None:
            raise AppError(ErrorCode.UNSUPPORTED_SITE)
        return validated.url, provider

    async def inspect(self, raw_url: str) -> InspectResult:
        url, provider = self.resolve_provider(raw_url)
        media = await self._media(url)
        options = build_options(media.formats, media.duration, self._limits)
        if not options:
            raise AppError(ErrorCode.NO_MEDIA_FOUND)
        return InspectResult(provider=provider, media=media, options=options)

    async def _media(self, url: str) -> MediaInfo:
        key = url_fingerprint(url)
        hit = self._cache.get(key)
        if hit is not None and self._clock() - hit[0] < self._cache_ttl:
            self._cache.move_to_end(key)
            return hit[1]
        if (pending := self._inflight.get(key)) is not None:
            try:
                return await asyncio.shield(pending)
            except asyncio.CancelledError:
                task = asyncio.current_task()
                if pending.cancelled() and task is not None and not task.cancelling():
                    return await self._media(url)  # the leader was cancelled, not us: retry
                raise
        future: asyncio.Future[MediaInfo] = asyncio.get_running_loop().create_future()
        self._inflight[key] = future
        try:
            media = await self._run(url)
        except asyncio.CancelledError:
            future.cancel()
            raise
        except Exception as exc:
            future.set_exception(exc)
            future.exception()  # mark retrieved for callers that never await it
            raise
        else:
            future.set_result(media)
            self._store(key, media)
            return media
        finally:
            del self._inflight[key]

    async def _run(self, url: str) -> MediaInfo:
        if self._sem.locked() and self._waiting >= self._max_waiting:
            raise AppError(ErrorCode.SERVER_BUSY, retry_after=10)
        self._waiting += 1
        try:
            await self._sem.acquire()
        finally:
            self._waiting -= 1
        try:
            return await self._backend.inspect(url, self._time_limit)
        finally:
            self._sem.release()

    def _store(self, key: str, media: MediaInfo) -> None:
        if self._cache_ttl <= 0:
            return
        self._cache[key] = (self._clock(), media)
        self._cache.move_to_end(key)
        while len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)
