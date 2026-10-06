"""Production entrypoint: ``python -m downloader`` (or the ``downloader`` script)."""

from __future__ import annotations

import os

import uvicorn

from downloader.config import Settings
from downloader.observability import configure_logging


def main() -> None:
    settings = Settings()
    configure_logging(settings.log_level)
    uvicorn.run(
        "downloader.api.app:create_app",
        factory=True,
        host=os.environ.get("DL_HOST", "0.0.0.0"),  # noqa: S104 - container network namespace
        port=int(os.environ.get("DL_PORT", "8000")),
        # Only trust X-Forwarded-For from the reverse proxy you deploy in front of the app.
        proxy_headers=True,
        forwarded_allow_ips=os.environ.get("DL_FORWARDED_ALLOW_IPS", "127.0.0.1"),
        server_header=False,
        timeout_keep_alive=5,
        # Bounds open connections (SSE streams included) before file descriptors run out.
        limit_concurrency=int(os.environ.get("DL_LIMIT_CONCURRENCY", "2048")),
        timeout_graceful_shutdown=20,
        h11_max_incomplete_event_size=16 * 1024,
        log_config=None,
        access_log=False,
    )


if __name__ == "__main__":
    main()
