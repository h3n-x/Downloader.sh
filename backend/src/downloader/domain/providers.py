"""Supported platforms as data. Adding one = adding an entry (plus its engine mapping)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True, slots=True)
class Provider:
    slug: str
    name: str
    domains: tuple[str, ...]

    def matches(self, host: str) -> bool:
        return any(host == d or host.endswith("." + d) for d in self.domains)


PROVIDERS: Final[tuple[Provider, ...]] = (
    Provider("youtube", "YouTube", ("youtube.com", "youtu.be", "youtube-nocookie.com")),
    Provider("x", "X (Twitter)", ("x.com", "twitter.com")),
    Provider("instagram", "Instagram", ("instagram.com",)),
    Provider("tiktok", "TikTok", ("tiktok.com",)),
    Provider("facebook", "Facebook", ("facebook.com", "fb.watch")),
    Provider("reddit", "Reddit", ("reddit.com", "redd.it")),
    Provider("twitch", "Twitch", ("twitch.tv",)),
    Provider("vimeo", "Vimeo", ("vimeo.com",)),
    Provider("soundcloud", "SoundCloud", ("soundcloud.com",)),
    Provider("bluesky", "Bluesky", ("bsky.app",)),
    Provider("dailymotion", "Dailymotion", ("dailymotion.com", "dai.ly")),
    Provider("streamable", "Streamable", ("streamable.com",)),
)


class ProviderRegistry:
    def __init__(self, providers: tuple[Provider, ...], enabled: frozenset[str] | None = None):
        self._providers = tuple(p for p in providers if enabled is None or p.slug in enabled)

    @property
    def providers(self) -> tuple[Provider, ...]:
        return self._providers

    def detect(self, host: str) -> Provider | None:
        return next((p for p in self._providers if p.matches(host)), None)

    def get(self, slug: str) -> Provider | None:
        return next((p for p in self._providers if p.slug == slug), None)
