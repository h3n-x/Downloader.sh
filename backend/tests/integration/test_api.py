import json
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from downloader.api.app import create_app
from downloader.config import Settings
from downloader.domain.errors import AppError, ErrorCode
from tests.fakes import FakeBackend

URL = "https://www.youtube.com/watch?v=abc123"


def make_client(
    tmp_path: Path, backend: FakeBackend, *, raise_errors: bool = True, **overrides: Any
) -> TestClient:
    static = tmp_path / "static"
    (static / "_astro").mkdir(parents=True, exist_ok=True)
    (static / "index.html").write_text("<!doctype html><title>t</title>")
    (static / "_astro" / "app.abc123.js").write_text("console.log(1)")
    settings = Settings(
        environment="test",
        data_dir=tmp_path / "data",
        static_dir=static,
        metrics_token="s3cret",  # noqa: S106 - test fixture
        **overrides,
    )
    return TestClient(create_app(settings, backend), raise_server_exceptions=raise_errors)


@pytest.fixture
def backend() -> FakeBackend:
    return FakeBackend()


@pytest.fixture
def client(tmp_path: Path, backend: FakeBackend) -> Iterator[TestClient]:
    with make_client(tmp_path, backend) as c:
        yield c


def error_code(resp: Any) -> str:
    return str(resp.json()["error"]["code"])


def test_meta(client: TestClient) -> None:
    body = client.get("/api/v1/meta").json()
    assert {"slug": "youtube", "name": "YouTube"} in body["providers"]
    assert body["limits"]["max_filesize"] > 0


def test_inspect_ok_with_security_headers(client: TestClient) -> None:
    resp = client.post("/api/v1/inspect", json={"url": URL})
    assert resp.status_code == 200
    body = resp.json()
    assert body["media"]["provider"] == {"slug": "youtube", "name": "YouTube"}
    assert [o["id"] for o in body["options"]] == ["v1080", "v720", "audio"]
    assert "url" not in json.dumps(body["formats"])  # no CDN URLs ever leave the server
    h = resp.headers
    assert "default-src 'self'" in h["content-security-policy"]
    assert h["x-content-type-options"] == "nosniff"
    assert h["cache-control"] == "no-store"
    assert h["referrer-policy"] == "no-referrer"
    assert len(h["x-request-id"]) == 32


@pytest.mark.parametrize(
    ("payload", "status", "code"),
    [
        ({"url": ""}, 422, "VALIDATION_ERROR"),
        ({"url": URL, "extra": 1}, 422, "VALIDATION_ERROR"),
        ({}, 422, "VALIDATION_ERROR"),
        ({"url": "x" * 5000}, 422, "VALIDATION_ERROR"),
        ({"url": "https://example.org/v"}, 422, "UNSUPPORTED_SITE"),
        ({"url": "http://169.254.169.254/latest"}, 400, "URL_NOT_ALLOWED"),
        ({"url": "file:///etc/passwd"}, 400, "INVALID_URL"),
    ],
)
def test_inspect_errors(
    client: TestClient, payload: dict[str, Any], status: int, code: str
) -> None:
    resp = client.post("/api/v1/inspect", json=payload)
    assert resp.status_code == status
    assert error_code(resp) == code
    assert resp.json()["error"]["request_id"]


def test_non_json_body_is_rejected(client: TestClient) -> None:
    # Blocks "simple request" cross-site form posts (no CORS preflight).
    resp = client.post(
        "/api/v1/inspect", content=f'{{"url": "{URL}"}}', headers={"content-type": "text/plain"}
    )
    assert resp.status_code == 422


def test_platform_error_is_mapped(client: TestClient, backend: FakeBackend) -> None:
    backend.inspect_error = AppError(ErrorCode.CONTENT_PRIVATE, detail="secret internal detail")
    resp = client.post("/api/v1/inspect", json={"url": URL})
    assert resp.status_code == 403
    assert error_code(resp) == "CONTENT_PRIVATE"
    assert "secret internal detail" not in resp.text


def test_unhandled_error_does_not_leak(tmp_path: Path) -> None:
    class Boom(FakeBackend):
        async def inspect(self, url: str, time_limit: float) -> Any:
            raise RuntimeError("/etc/shadow stack trace")

    with make_client(tmp_path, Boom(), raise_errors=False) as c:
        resp = c.post("/api/v1/inspect", json={"url": URL})
    assert resp.status_code == 500
    assert error_code(resp) == "INTERNAL_ERROR"
    assert "shadow" not in resp.text


def test_rate_limit(tmp_path: Path, backend: FakeBackend) -> None:
    with make_client(tmp_path, backend, inspect_per_minute=2) as c:
        assert c.post("/api/v1/inspect", json={"url": URL}).status_code == 200
        assert c.post("/api/v1/inspect", json={"url": URL}).status_code == 200
        resp = c.post("/api/v1/inspect", json={"url": URL})
    assert resp.status_code == 429
    assert error_code(resp) == "RATE_LIMITED"
    assert int(resp.headers["retry-after"]) >= 1


def wait_ready(client: TestClient, job_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        body: dict[str, Any] = client.get(f"/api/v1/downloads/{job_id}").json()
        if body["phase"] in {"ready", "failed", "cancelled"}:
            return body
        time.sleep(0.02)
    raise AssertionError("job did not finish")


def test_download_lifecycle(client: TestClient, backend: FakeBackend) -> None:
    resp = client.post("/api/v1/downloads", json={"url": URL, "option_id": "v1080"})
    assert resp.status_code == 202
    job = resp.json()
    assert resp.headers["location"] == f"/api/v1/downloads/{job['id']}"
    assert len(job["id"]) == 22
    body = wait_ready(client, job["id"])
    assert body["phase"] == "ready"
    assert body["file_url"] == f"/api/v1/downloads/{job['id']}/file"

    with client.stream("GET", body["events_url"]) as stream:
        assert stream.headers["content-type"].startswith("text/event-stream")
        text = "".join(stream.iter_text())
    events = [json.loads(line[5:]) for line in text.splitlines() if line.startswith("data:")]
    assert "event: job" in text
    assert events[-1]["phase"] == "ready"
    assert events[-1]["title"] == "Sample <b>title</b>"  # raw; the UI renders it as text

    file = client.get(body["file_url"])
    assert file.status_code == 200
    assert file.content == backend.payload
    assert file.headers["content-type"] == "video/mp4"
    assert file.headers["content-disposition"].startswith(
        'attachment; filename="Sample b title b.mp4"'
    )
    assert file.headers["cache-control"] == "private, no-store"

    partial = client.get(body["file_url"], headers={"Range": "bytes=0-3"})
    assert partial.status_code == 206
    assert partial.content == backend.payload[:4]

    assert client.delete(f"/api/v1/downloads/{job['id']}").status_code == 204
    gone = client.get(body["file_url"])
    assert gone.status_code == 410
    assert error_code(gone) == "JOB_EXPIRED"


def test_download_failure_is_reported(client: TestClient) -> None:
    job = client.post("/api/v1/downloads", json={"url": URL, "option_id": "v4320"}).json()
    body = wait_ready(client, job["id"])
    assert body["phase"] == "failed"
    assert body["error_code"] == "FORMAT_UNAVAILABLE"
    assert body["file_url"] is None


@pytest.mark.parametrize("option_id", ["1+2", "best[height<99]", "f:../../x", ""])
def test_download_rejects_bad_option(client: TestClient, option_id: str) -> None:
    resp = client.post("/api/v1/downloads", json={"url": URL, "option_id": option_id})
    assert resp.status_code == 422


def test_unknown_and_malformed_job_ids(client: TestClient) -> None:
    resp = client.get("/api/v1/downloads/AAAAAAAAAAAAAAAAAAAAAA")
    assert resp.status_code == 404
    assert error_code(resp) == "JOB_NOT_FOUND"
    assert client.get("/api/v1/downloads/AAAAAAAAAAAAAAAAAAAAAA/events").status_code == 404
    assert client.get("/api/v1/downloads/../../etc/passwd").status_code in {404, 422}


def test_unknown_route_uses_envelope(client: TestClient) -> None:
    resp = client.get("/api/v1/nope")
    assert resp.status_code == 404
    assert error_code(resp) == "NOT_FOUND"


def test_request_id_propagation(client: TestClient) -> None:
    ok = client.get("/api/v1/health", headers={"x-request-id": "abcdef12-3456"})
    assert ok.headers["x-request-id"] == "abcdef12-3456"
    bad = client.get("/api/v1/health", headers={"x-request-id": "evil\x01id"})
    assert bad.headers["x-request-id"] != "evil\x01id"


def test_metrics_require_token(client: TestClient) -> None:
    assert client.get("/metrics").status_code == 404
    resp = client.get("/metrics", headers={"authorization": "Bearer s3cret"})
    assert resp.status_code == 200
    assert "dl_http_requests_total" in resp.text


def test_static_caching(client: TestClient) -> None:
    index = client.get("/")
    assert index.status_code == 200
    assert index.headers["cache-control"] == "no-cache"
    assert "frame-ancestors 'none'" in index.headers["content-security-policy"]
    asset = client.get("/_astro/app.abc123.js")
    assert asset.headers["cache-control"] == "public, max-age=31536000, immutable"


def test_openapi_schema_is_served(client: TestClient) -> None:
    schema = client.get("/api/v1/openapi.json").json()
    assert "/api/v1/inspect" in schema["paths"]
    assert "ErrorOut" in schema["components"]["schemas"]
