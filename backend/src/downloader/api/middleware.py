"""Pure-ASGI middleware (streaming-safe): request id, security headers, access log, metrics."""

from __future__ import annotations

import logging
import re
import time
import uuid
from typing import Final

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from downloader.observability import Metrics, request_id_var

log = logging.getLogger("downloader.access")

_REQUEST_ID_RE: Final = re.compile(r"^[A-Za-z0-9-]{8,64}$")

CSP: Final = "; ".join(
    (
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self'",
        "img-src 'self' data: https:",  # thumbnails come from platform CDNs
        "font-src 'self'",
        "connect-src 'self'",
        "media-src 'self'",
        "object-src 'none'",
        "base-uri 'none'",
        "form-action 'self'",
        "frame-ancestors 'none'",
        "manifest-src 'self'",
    )
)

BASE_HEADERS: Final = {
    "content-security-policy": CSP,
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
    "permissions-policy": (
        "camera=(), microphone=(), geolocation=(), payment=(), usb=(), browsing-topics=()"
    ),
    "cross-origin-opener-policy": "same-origin",
    "cross-origin-resource-policy": "same-origin",
    "x-frame-options": "DENY",
}


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp, *, metrics: Metrics, hsts: bool) -> None:
        self.app = app
        self.metrics = metrics
        self.headers = dict(BASE_HEADERS)
        if hsts:
            self.headers["strict-transport-security"] = "max-age=63072000; includeSubDomains"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = dict(scope.get("headers") or []).get(b"x-request-id", b"").decode("latin-1")
        rid = incoming if _REQUEST_ID_RE.match(incoming) else uuid.uuid4().hex
        token = request_id_var.set(rid)
        start = time.perf_counter()
        status = 500
        streaming = False

        async def send_wrapper(message: Message) -> None:
            nonlocal status, streaming
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = MutableHeaders(scope=message)
                for key, value in self.headers.items():
                    headers.setdefault(key, value)
                headers["x-request-id"] = rid
                path: str = scope["path"]
                if path.startswith("/api/"):
                    headers.setdefault("cache-control", "no-store")
                    headers["x-robots-tag"] = "noindex, nofollow"
                streaming = headers.get("content-type", "").startswith("text/event-stream")
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            route = scope.get("route")
            template = getattr(route, "path", None) or (
                "static" if not scope["path"].startswith("/api/") else "unmatched"
            )
            elapsed = time.perf_counter() - start
            self.metrics.http_requests.labels(template, scope["method"], str(status)).inc()
            if not streaming:
                self.metrics.http_latency.labels(template).observe(elapsed)
            if template != "static" or status >= 400:
                log.info(
                    "request",
                    extra={
                        "method": scope["method"],
                        "route": template,
                        "status": status,
                        "ms": round(elapsed * 1000, 1),
                    },
                )
            request_id_var.reset(token)
