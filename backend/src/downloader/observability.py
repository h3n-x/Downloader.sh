"""Structured logging, request ids and Prometheus metrics.

Privacy: logs never contain raw media URLs, titles, client IPs or job ids.
Use `url_fingerprint` for correlation and route *templates* for paths.
"""

from __future__ import annotations

import contextvars
import datetime as dt
import json
import logging
import sys
from typing import Any, Final

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)

_STD_ATTRS: Final = frozenset(
    vars(logging.LogRecord("", 0, "", 0, "", None, None)).keys()
    | {"message", "asctime", "taskName", "color_message"}
)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": dt.datetime.fromtimestamp(record.created, tz=dt.UTC).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": record.getMessage().replace("\n", " ").replace("\r", " "),
        }
        if (rid := request_id_var.get()) is not None:
            payload["request_id"] = rid
        for key, value in vars(record).items():
            if key not in _STD_ATTRS and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    # uvicorn's access log prints raw paths (job ids are capabilities) and client IPs.
    logging.getLogger("uvicorn.access").disabled = True
    for name in ("uvicorn", "uvicorn.error"):
        logging.getLogger(name).handlers[:] = []
        logging.getLogger(name).propagate = True


class Metrics:
    def __init__(self) -> None:
        self.registry = CollectorRegistry(auto_describe=True)
        self.http_requests = Counter(
            "dl_http_requests",
            "HTTP requests",
            ["route", "method", "status"],
            registry=self.registry,
        )
        self.http_latency = Histogram(
            "dl_http_request_seconds",
            "HTTP latency (excluding streams)",
            ["route"],
            buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60),
            registry=self.registry,
        )
        self.inspections = Counter(
            "dl_inspections", "Inspect outcomes", ["provider", "outcome"], registry=self.registry
        )
        self.downloads = Counter(
            "dl_downloads", "Download outcomes", ["provider", "outcome"], registry=self.registry
        )
        self.download_seconds = Histogram(
            "dl_download_seconds",
            "Download job duration",
            ["provider"],
            buckets=(1, 5, 10, 30, 60, 120, 300, 600, 1800),
            registry=self.registry,
        )
        self.download_bytes = Counter("dl_download_bytes", "Bytes produced", registry=self.registry)
        self.egress_denied = Counter(
            "dl_egress_denied", "Egress proxy denials", ["reason"], registry=self.registry
        )
        self.jobs = Gauge("dl_jobs", "Jobs by phase", ["phase"], registry=self.registry)
        self.rate_limited = Counter(
            "dl_rate_limited",
            "Requests rejected by rate limiting",
            ["bucket"],
            registry=self.registry,
        )
