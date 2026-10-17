"""Bounded daily-log reads and retention, shared by the panel backend."""

from datetime import date, timedelta
import os
from pathlib import Path
import re

from . import rules


def cleanup_logs(log_dir, today):
    cutoff = today - timedelta(days=rules.RETENTION_DAYS)
    removed = 0
    for path in Path(log_dir).glob("*.jsonl"):
        if not path.is_file() or not re.fullmatch(r"\d{4}-\d{2}-\d{2}\.jsonl", path.name):
            continue
        try:
            log_day = date.fromisoformat(path.stem)
        except ValueError:
            continue
        if log_day < cutoff:
            path.unlink()
            removed += 1
    return removed


class Tail:
    """Byte offsets advance only past complete lines; never buffer a partial line."""
    def __init__(self, path, *, from_end=False, snapshot=False):
        self.path = Path(path)
        size = self._size()
        self.offset = size if from_end else 0
        self.stop_at = size if snapshot else None
        self.caught_up = False
        self._identity = self._stat_identity()

    def _size(self):
        try:
            return self.path.stat().st_size
        except FileNotFoundError:
            return 0

    def _stat_identity(self):
        try:
            stat = self.path.stat()
            return stat.st_dev, stat.st_ino
        except FileNotFoundError:
            return None

    @property
    def at_eof(self):
        return self.offset >= self._size()

    def read_lines(self):
        self.caught_up = False
        try:
            file = self.path.open("rb")
        except FileNotFoundError:
            self.caught_up = True
            return
        with file:
            stat = os.fstat(file.fileno())
            identity = (stat.st_dev, stat.st_ino)
            if stat.st_size < self.offset or (self._identity is not None and identity != self._identity):
                self.offset = 0
            self._identity = identity
            end = min(stat.st_size, self.stop_at) if self.stop_at is not None else stat.st_size
            file.seek(self.offset)
            for _ in range(rules.MAX_LINES_PER_POLL):
                if file.tell() >= end:
                    break
                raw = file.readline(min(rules.MAX_LINE_BYTES + 1, end - file.tell()))
                oversized = len(raw) > rules.MAX_LINE_BYTES
                while not raw.endswith(b"\n") and file.tell() < end:
                    oversized = True
                    raw = file.readline(min(rules.MAX_LINE_BYTES + 1, end - file.tell()))
                if not raw.endswith(b"\n"):
                    self.caught_up = True
                    return
                self.offset = file.tell()
                yield None if oversized else raw
            self.caught_up = self.offset >= end
