"""Filename handling.

Files on disk never use user/platform-controlled names (always ``media.<ext>``
inside a per-job ``mkdtemp`` directory). Titles are only used for the
*suggested* download name in ``Content-Disposition``, sanitised here.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Final
from urllib.parse import quote

MAX_STEM_CHARS: Final = 120
SAFE_EXTENSIONS: Final = frozenset(
    {"mp4", "webm", "mkv", "m4a", "mp3", "opus", "ogg", "mov", "aac", "flac", "wav"}
)

_UNSAFE = re.compile(r'[\x00-\x1f\x7f/\\:*?"<>|;]+')
_SPACES = re.compile(r"\s+")
_WINDOWS_RESERVED: Final = frozenset(
    {
        "con",
        "prn",
        "aux",
        "nul",
        *(f"com{i}" for i in range(1, 10)),
        *(f"lpt{i}" for i in range(1, 10)),
    }
)


def safe_extension(ext: str) -> str | None:
    ext = ext.lower().lstrip(".")
    return ext if ext in SAFE_EXTENSIONS else None


def sanitize_stem(title: str, fallback: str = "download") -> str:
    """Return a cross-platform-safe file stem (no extension)."""
    text = _SPACES.sub(" ", unicodedata.normalize("NFC", title))
    # Drop bidi controls and other format characters that can spoof extensions.
    text = "".join(
        ch for ch in text if unicodedata.category(ch) not in {"Cc", "Cf", "Cs", "Co", "Cn"}
    )
    text = _UNSAFE.sub(" ", text)
    text = _SPACES.sub(" ", text).strip(" .-_")
    if len(text) > MAX_STEM_CHARS:
        text = text[:MAX_STEM_CHARS].rstrip(" .-_")
    if not text or text.lower() in _WINDOWS_RESERVED:
        return fallback
    return text


def content_disposition(title: str, ext: str) -> str:
    """RFC 6266 attachment header with an ASCII fallback and RFC 5987 UTF-8 name."""
    stem = sanitize_stem(title)
    full = f"{stem}.{ext}"
    ascii_stem = unicodedata.normalize("NFKD", stem).encode("ascii", "ignore").decode("ascii")
    ascii_stem = sanitize_stem(ascii_stem.replace("%", " "))
    ascii_name = f"{ascii_stem}.{ext}".replace('"', "")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(full, safe='')}"
