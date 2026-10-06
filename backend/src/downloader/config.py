"""Runtime configuration (environment variables prefixed with ``DL_``)."""

from __future__ import annotations

import secrets
from pathlib import Path
from typing import Annotated

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from downloader.domain.providers import PROVIDERS

GiB = 1024**3


def _split_csv(value: object) -> object:
    if isinstance(value, str):
        return frozenset(v.strip() for v in value.split(",") if v.strip())
    return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DL_", env_file=".env", extra="ignore")

    environment: str = Field(default="production", pattern=r"^(production|development|test)$")
    data_dir: Path = Path("/tmp/downloader")  # noqa: S108 - per-job dirs are created with mkdtemp 0700
    static_dir: Path | None = None
    providers: Annotated[frozenset[str], NoDecode] = frozenset(p.slug for p in PROVIDERS)

    # Per-job limits
    max_filesize: int = Field(default=2 * GiB, gt=0)
    max_duration: int = Field(default=3 * 3600, gt=0, description="seconds")
    inspect_timeout: float = Field(default=60, gt=0)
    download_timeout: float = Field(default=30 * 60, gt=0)
    worker_cpu_seconds: int = Field(default=900, gt=0)

    # Capacity / backpressure
    max_concurrent_downloads: int = Field(default=4, gt=0)
    max_queued_downloads: int = Field(default=16, ge=0)
    max_concurrent_inspects: int = Field(default=8, gt=0)
    max_active_downloads_per_client: int = Field(default=2, gt=0)
    disk_quota: int = Field(default=20 * GiB, gt=0)

    # Rate limits (token bucket: burst = per-minute value)
    inspect_per_minute: int = Field(default=20, gt=0)
    downloads_per_minute: int = Field(default=6, gt=0)

    # Lifecycle
    download_ttl: int = Field(default=15 * 60, gt=0, description="seconds a ready file is kept")
    inspect_cache_ttl: int = Field(default=5 * 60, ge=0)

    # Security / observability
    client_key_secret: SecretStr = Field(default_factory=lambda: SecretStr(secrets.token_hex(32)))
    hsts: bool = False
    metrics_enabled: bool = True
    metrics_token: SecretStr | None = None
    log_level: str = "INFO"
    log_worker_stderr: bool = False

    def model_post_init(self, _context: object) -> None:
        unknown = self.providers - {p.slug for p in PROVIDERS}
        if unknown:
            raise ValueError(f"unknown providers: {sorted(unknown)}")

    @field_validator("providers", mode="before")
    @classmethod
    def _split_providers(cls, value: object) -> object:
        return _split_csv(value)

    @property
    def jobs_dir(self) -> Path:
        return self.data_dir / "jobs"

    @property
    def is_production(self) -> bool:
        return self.environment == "production"
