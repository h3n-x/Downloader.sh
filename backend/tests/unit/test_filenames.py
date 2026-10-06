import re

import pytest
from hypothesis import given
from hypothesis import strategies as st

from downloader.security.filenames import content_disposition, safe_extension, sanitize_stem


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("My video", "My video"),
        ("../../etc/passwd", "etc passwd"),
        ('a<b>c:"d"|e?*f', "a b c d e f"),
        ("CON", "download"),
        ("   ", "download"),
        ("evil\u202egnp.exe", "evilgnp.exe"),  # RTL override removed
        ("Ünïcödé 🎵", "Ünïcödé 🎵"),
        ("line\nbreak\r\ninjection", "line break injection"),
    ],
)
def test_sanitize_stem(title: str, expected: str) -> None:
    assert sanitize_stem(title) == expected


def test_safe_extension() -> None:
    assert safe_extension("MP4") == "mp4"
    assert safe_extension(".m4a") == "m4a"
    assert safe_extension("exe") is None
    assert safe_extension("html") is None


def test_content_disposition_has_ascii_and_utf8() -> None:
    header = content_disposition('Canción "final"', "mp4")
    assert header.startswith('attachment; filename="Cancion final.mp4"')
    assert "filename*=UTF-8''Canci%C3%B3n%20final.mp4" in header


@given(st.text(max_size=500))
def test_stem_is_always_safe(title: str) -> None:
    stem = sanitize_stem(title)
    assert stem
    assert len(stem) <= 120
    assert not re.search(r'[\x00-\x1f\x7f/\\:*?"<>|]', stem)
    assert stem not in {".", ".."}
    assert not stem.startswith((".", "-", " "))


@given(st.text(max_size=200))
def test_header_has_no_injection(title: str) -> None:
    header = content_disposition(title, "mp4")
    assert "\r" not in header
    assert "\n" not in header
    assert header.isascii()
