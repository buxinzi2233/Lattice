from __future__ import annotations

from pathlib import Path


class LogTailer:
    """Incrementally read a log while folding carriage-return progress updates."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.offset = 0
        self._pending = ""

    def reset(self) -> None:
        self.offset = 0
        self._pending = ""

    def seek_tail(self, max_bytes: int = 512 * 1024) -> None:
        """Position near the end while starting on a complete line."""
        self.reset()
        try:
            size = self.path.stat().st_size
        except FileNotFoundError:
            return
        self.offset = max(0, size - max_bytes)
        if self.offset == 0:
            return
        try:
            with self.path.open("rb") as handle:
                handle.seek(self.offset)
                handle.readline()
                self.offset = handle.tell()
        except OSError:
            self.reset()

    @staticmethod
    def _fold(line: str) -> str:
        return line.rsplit("\r", 1)[-1]

    def read(self) -> str:
        try:
            size = self.path.stat().st_size
        except FileNotFoundError:
            return ""
        if size < self.offset:
            self.reset()
        if size == self.offset:
            return ""

        try:
            with self.path.open("rb") as handle:
                handle.seek(self.offset)
                payload = handle.read()
                self.offset = handle.tell()
        except (FileNotFoundError, OSError):
            return ""

        text = self._pending + payload.decode("utf-8", errors="replace")
        complete = text.split("\n")
        self._pending = complete.pop()
        if not complete:
            return ""
        return "".join(self._fold(line) + "\n" for line in complete)

    def flush_pending(self) -> str:
        if not self._pending:
            return ""
        text = self._fold(self._pending)
        self._pending = ""
        return text
