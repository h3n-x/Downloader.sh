"""Ephemeral per-job storage.

- Each job gets a fresh ``mkdtemp`` directory (mode 0700, unpredictable name).
- Deletion refuses anything outside the jobs root or any symlink.
- `sweep` removes orphans (e.g. after a crash), so disk never fills with leftovers.
"""

from __future__ import annotations

import logging
import os
import shutil
import stat
import tempfile
import time
from pathlib import Path

log = logging.getLogger(__name__)


class JobStorage:
    def __init__(self, root: Path) -> None:
        self.root = root

    def prepare(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.root.chmod(0o700)
        if self.root.is_symlink():
            raise RuntimeError("jobs root must not be a symlink")

    def create(self, prefix: str) -> Path:
        return Path(tempfile.mkdtemp(prefix=f"{prefix}-", dir=self.root))

    def _is_child(self, path: Path) -> bool:
        try:
            st = path.lstat()
        except FileNotFoundError:
            return False
        if stat.S_ISLNK(st.st_mode):
            return False
        return path.resolve().parent == self.root.resolve()

    def remove(self, path: Path) -> None:
        if not self._is_child(path):
            if path.exists() or path.is_symlink():
                log.warning("refusing to remove path outside jobs root")
            return
        shutil.rmtree(path, ignore_errors=True)

    def usage_bytes(self) -> int:
        total = 0
        for dirpath, _dirs, files in os.walk(self.root):
            for name in files:
                try:
                    total += (Path(dirpath) / name).lstat().st_size
                except FileNotFoundError:
                    continue
        return total

    def sweep(self, active: set[Path], max_age: float) -> int:
        """Remove job dirs not in `active` older than `max_age` seconds."""
        removed = 0
        now = time.time()
        active_resolved = {p.resolve() for p in active}
        for entry in self.root.iterdir():
            if entry.resolve() in active_resolved:
                continue
            try:
                age = now - entry.lstat().st_mtime
            except FileNotFoundError:
                continue
            if age >= max_age:
                if entry.is_symlink() or not entry.is_dir():
                    entry.unlink(missing_ok=True)
                else:
                    shutil.rmtree(entry, ignore_errors=True)
                removed += 1
        return removed
