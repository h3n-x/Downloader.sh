from urllib.parse import urlsplit

import pytest
from hypothesis import given
from hypothesis import strategies as st

from downloader.domain.errors import AppError, ErrorCode
from downloader.security.url import MAX_URL_LENGTH, ValidatedUrl, validate_url


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://www.youtube.com/watch?v=abc", "https://www.youtube.com/watch?v=abc"),
        ("  https://X.com/user/status/1  ", "https://x.com/user/status/1"),
        ("youtube.com/watch?v=abc", "https://youtube.com/watch?v=abc"),
        ("//vimeo.com/1", "https://vimeo.com/1"),
        ("https://example.com", "https://example.com/"),
        ("https://example.com/a#frag", "https://example.com/a"),
        ("https://example.com./a", "https://example.com/a"),
        ("http://example.com:80/a", "http://example.com:80/a"),
        ("https://bücher.de/x", "https://xn--bcher-kva.de/x"),
        ("https://example.com/a b".replace(" ", "%20"), "https://example.com/a%20b"),
        ("https://example.com/ü", "https://example.com/%C3%BC"),
    ],
)
def test_normalizes(raw: str, expected: str) -> None:
    assert validate_url(raw).url == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "javascript:alert(1)",
        "file:///etc/passwd",
        "ftp://example.com/a",
        "gopher://example.com",
        "data:text/html,hi",
        "https://exa mple.com",
        "https://example.com\\@evil.com",
        "https://example.com/\x00",
        "https://-bad-.com",
        "https://example.123",
        "https://0x7f.1",
        "https://0177.0.0.1",
        "https://2130706433",
        "https://",
        "http://[::1",
        "https://a..b.com",
    ],
)
def test_rejects_invalid(raw: str) -> None:
    with pytest.raises(AppError) as exc:
        validate_url(raw)
    assert exc.value.code is ErrorCode.INVALID_URL


@pytest.mark.parametrize(
    "raw",
    [
        "http://127.0.0.1/",
        "http://localhost/",
        "localhost:8080",
        "http://LOCALHOST./",
        "http://foo.localhost/",
        "http://printer.local/",
        "http://db.internal/",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/",
        "http://[::ffff:127.0.0.1]/",
        "http://[64:ff9b::7f00:1]/",
        "http://10.1.2.3/",
        "http://intranet/",
        "https://example.com:8443/",
        "https://example.com:22/",
        "http://[fd00:ec2::254]/",
    ],
)
def test_rejects_internal_destinations(raw: str) -> None:
    with pytest.raises(AppError) as exc:
        validate_url(raw)
    assert exc.value.code is ErrorCode.URL_NOT_ALLOWED


def test_rejects_userinfo() -> None:
    for raw in ("https://user:pw@youtube.com/", "https://youtube.com@127.0.0.1/"):
        with pytest.raises(AppError) as exc:
            validate_url(raw)
        assert exc.value.code is ErrorCode.INVALID_URL


def test_rejects_oversized() -> None:
    with pytest.raises(AppError):
        validate_url("https://example.com/" + "a" * MAX_URL_LENGTH)


def test_public_ip_literal_is_accepted_but_normalized() -> None:
    v = validate_url("http://[2606:4700:0::1111]/")
    assert v.url == "http://[2606:4700::1111]/"
    assert v.ip is not None


@given(st.text(max_size=300))
def test_never_crashes_and_output_is_safe(raw: str) -> None:
    outcome: ValidatedUrl | ErrorCode
    try:
        outcome = validate_url(raw)
    except AppError as exc:
        outcome = exc.code
    if isinstance(outcome, ErrorCode):
        assert outcome in {ErrorCode.INVALID_URL, ErrorCode.URL_NOT_ALLOWED}
        return
    v = outcome
    parts = urlsplit(v.url)
    assert parts.scheme in {"http", "https"}
    assert parts.username is None
    assert parts.hostname == v.host or parts.hostname == v.host.strip("[]")
    assert not any(c in v.url for c in "\x00\r\n\t \\")
    # Idempotent: re-validating the normalized URL yields the same URL.
    assert validate_url(v.url).url == v.url
