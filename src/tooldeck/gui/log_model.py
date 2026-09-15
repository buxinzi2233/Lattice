from __future__ import annotations

import re
from dataclasses import dataclass

from PySide6.QtCore import QAbstractListModel, QModelIndex, Property, Qt, Signal, Slot


_TIME_RE = re.compile(r"(?P<clock>\d{2}:\d{2}:\d{2})(?:[.,](?P<fraction>\d+))?")
_BRACKET_TIME_RE = re.compile(r"^\s*\[(?P<stamp>[^\]]+)\]\s*(?P<rest>.*)$")
_PLAIN_TIME_RE = re.compile(
    r"^\s*(?P<stamp>(?:\d{4}-\d{2}-\d{2}[ T])?\d{2}:\d{2}:\d{2}(?:[.,]\d+)?)\s+(?P<rest>.*)$"
)
_LEVEL_RE = re.compile(
    r"^\s*\[?(?P<level>DEBUG|TRACE|INFO|NOTICE|WARN(?:ING)?|ERROR|FATAL|CRITICAL|COMMAND|CMD)\]?\s*(?::|-)?\s*(?P<rest>.*)$",
    re.IGNORECASE,
)
_WARNING_RE = re.compile(r"\b(?:warn(?:ing)?|deprecated|pressure|retrying)\b", re.IGNORECASE)
_ERROR_RE = re.compile(r"\b(?:error|fatal|critical|exception|traceback|failed|failure)\b", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class LogLine:
    timestamp: str
    level: str
    message: str


def _clock_label(value: str) -> str:
    match = _TIME_RE.search(value)
    if match is None:
        return ""
    fraction = match.group("fraction")
    return match.group("clock") + (f".{fraction[:3]}" if fraction else "")


def parse_log_line(value: str) -> LogLine | None:
    line = value.rstrip("\r")
    if not line.strip():
        return None

    timestamp = ""
    message = line.strip()
    time_match = _BRACKET_TIME_RE.match(message) or _PLAIN_TIME_RE.match(message)
    if time_match is not None and _TIME_RE.search(time_match.group("stamp")):
        timestamp = _clock_label(time_match.group("stamp"))
        message = time_match.group("rest").strip()

    marker = message.startswith("---") and message.endswith("---")
    if marker:
        message = message.strip("- ")

    level = "info"
    level_match = _LEVEL_RE.match(message)
    if level_match is not None:
        raw_level = level_match.group("level").casefold()
        message = level_match.group("rest").strip()
        if raw_level in {"warn", "warning"}:
            level = "warn"
        elif raw_level in {"error", "fatal", "critical"}:
            level = "error"
        elif raw_level in {"command", "cmd"}:
            level = "command"
    elif marker or message.startswith(("$ ", "> ")) or re.match(r"^(?:exec|python|bash|sh|npm|uv)\s", message):
        level = "command"
    elif _ERROR_RE.search(message):
        level = "error"
    elif _WARNING_RE.search(message):
        level = "warn"

    return LogLine(timestamp, level, message)


class LogLineModel(QAbstractListModel):
    """Bounded, append-only presentation model for the live log view."""

    countChanged = Signal()

    TimestampRole = Qt.ItemDataRole.UserRole + 1
    LevelRole = TimestampRole + 1
    MessageRole = LevelRole + 1

    _ROLES = {
        TimestampRole: b"logTime",
        LevelRole: b"logLevel",
        MessageRole: b"logMessage",
    }

    def __init__(self, parent=None, *, max_lines: int = 2_000) -> None:
        super().__init__(parent)
        self._max_lines = max(1, int(max_lines))
        self._lines: list[LogLine] = []

    def roleNames(self) -> dict[int, bytes]:
        return self._ROLES

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._lines)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._lines):
            return None
        entry = self._lines[index.row()]
        if role == self.TimestampRole:
            return entry.timestamp
        if role == self.LevelRole:
            return entry.level
        if role in {self.MessageRole, Qt.ItemDataRole.DisplayRole}:
            return entry.message
        return None

    @Property(int, notify=countChanged)
    def count(self) -> int:
        return len(self._lines)

    def append_text(self, text: str) -> int:
        parsed = [entry for line in text.splitlines() if (entry := parse_log_line(line)) is not None]
        if not parsed:
            return 0
        if len(self._lines) + len(parsed) > self._max_lines:
            self.beginResetModel()
            self._lines = (self._lines + parsed)[-self._max_lines :]
            self.endResetModel()
        else:
            first = len(self._lines)
            self.beginInsertRows(QModelIndex(), first, first + len(parsed) - 1)
            self._lines.extend(parsed)
            self.endInsertRows()
        self.countChanged.emit()
        return len(parsed)

    def clear(self, message: str = "") -> None:
        replacement = [LogLine("", "command", message)] if message else []
        if replacement == self._lines:
            return
        self.beginResetModel()
        self._lines = replacement
        self.endResetModel()
        self.countChanged.emit()

    @Slot(int, result="QVariantMap")
    def get(self, row: int) -> dict[str, str]:
        if not 0 <= row < len(self._lines):
            return {}
        entry = self._lines[row]
        return {"logTime": entry.timestamp, "logLevel": entry.level, "logMessage": entry.message}
