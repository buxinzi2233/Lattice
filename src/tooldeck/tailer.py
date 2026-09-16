"""Bounded file I/O and incremental terminal-text decoding shared by GUI and CLI."""
from __future__ import annotations

import codecs
import os
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

READ_BYTES = 256 * 1024
SEGMENT_CHARS = 16 * 1024


@dataclass(frozen=True, slots=True)
class TextState:
    line: str
    escape: str
    carriage_return: bool


@dataclass(frozen=True, slots=True)
class LogBatch:
    completed: str
    preview: str
    reset: bool


def parse_text(state: TextState, text: str) -> tuple[TextState, str]:
    """Fold terminal progress and consume split ANSI sequences without unbounded state."""
    line = list(state.line)
    escape = state.escape
    carriage_return = state.carriage_return
    output: list[str] = []
    for char in text:
        if escape:
            if escape == "esc":
                escape = "csi" if char == "[" else "osc" if char == "]" else ""
            elif escape == "csi":
                if "@" <= char <= "~":
                    escape = ""
            elif escape == "osc":
                if char == "\x07":
                    escape = ""
                elif char == "\x1b":
                    escape = "osc_end"
            else:
                escape = "" if char in {"\\", "\x07"} else "osc"
            continue
        if char == "\x1b":
            escape = "esc"
            continue
        if char == "\n":
            output.append("".join(line) + "\n")
            line = []
            carriage_return = False
        elif char == "\r":
            carriage_return = True
        else:
            if carriage_return:
                line = []
                carriage_return = False
            if char == "\b":
                if line:
                    line.pop()
            elif char >= " " or char == "\t":
                line.append(char)
            if len(line) >= SEGMENT_CHARS:
                output.append("".join(line))
                line = []
    return TextState("".join(line), escape, carriage_return), "".join(output)


class LogTailer:
    """Own a log-file cursor and decoder; each read is at most READ_BYTES."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.offset = 0
        self._identity: tuple[int, int] | None = None
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self._state = TextState("", "", False)

    def reset(self) -> None:
        self.offset = 0
        self._identity = None
        self._decoder.reset()
        self._state = TextState("", "", False)

    def seek_end(self) -> None:
        self.reset()
        try:
            stat = self.path.stat()
        except FileNotFoundError:
            return
        self.offset = stat.st_size
        self._identity = (stat.st_dev, stat.st_ino)

    def seek_tail(self, max_bytes: int) -> None:
        """Seek to a bounded suffix, dropping an incomplete first UTF-8 codepoint."""
        self.reset()
        try:
            with self.path.open("rb") as handle:
                stat = os.fstat(handle.fileno())
                self._identity = (stat.st_dev, stat.st_ino)
                self.offset = max(0, stat.st_size - max_bytes)
                if self.offset:
                    handle.seek(self.offset)
                    prefix = handle.read(min(READ_BYTES, max_bytes))
                    newline = prefix.find(b"\n")
                    if newline >= 0:
                        self.offset += newline + 1
                    else:
                        for char in prefix[:4]:
                            if char & 0xC0 != 0x80:
                                break
                            self.offset += 1
        except FileNotFoundError:
            return

    def seek_lines(self, count: int) -> int:
        """Capture identity and tail offset together, retaining appends after the seek."""
        self.reset()
        try:
            with self.path.open("rb") as handle:
                stat = os.fstat(handle.fileno())
                self._identity = (stat.st_dev, stat.st_ino)
                self.offset = _tail_offset(handle, count, stat.st_size)
                return stat.st_size
        except FileNotFoundError:
            return 0

    def read_batch(self) -> LogBatch:
        return self.read_chunk(READ_BYTES)

    def read_chunk(self, max_bytes: int) -> LogBatch:
        if not 0 < max_bytes <= READ_BYTES:
            raise ValueError(f"日志读取量必须在 1 到 {READ_BYTES} 字节之间")
        try:
            with self.path.open("rb") as handle:
                stat = os.fstat(handle.fileno())
                identity = (stat.st_dev, stat.st_ino)
                replaced = self._identity is not None and identity != self._identity
                truncated = stat.st_size < self.offset
                changed = replaced or truncated
                if changed:
                    self.reset()
                self._identity = identity
                handle.seek(self.offset)
                payload = handle.read(max_bytes)
                self.offset = handle.tell()
        except FileNotFoundError:
            changed = self._identity is not None
            self.reset()
            return LogBatch("", "", changed)
        text = self._decoder.decode(payload, final=False)
        self._state, completed = parse_text(self._state, text)
        return LogBatch(completed, self._state.line, changed)

    def read(self) -> str:
        return self.read_batch().completed

    def flush_pending(self) -> str:
        text = self._state.line
        self._state = TextState("", self._state.escape, self._state.carriage_return)
        return text


def _tail_offset(handle: BinaryIO, count: int, end: int) -> int:
    if count <= 0 or end == 0:
        return end
    handle.seek(end - 1)
    needed = count + int(handle.read(1) == b"\n")
    position = end
    while position > 0:
        length = min(READ_BYTES, position)
        position -= length
        handle.seek(position)
        block = handle.read(length)
        index = block.rfind(b"\n")
        while index >= 0:
            needed -= 1
            if needed == 0:
                return position + index + 1
            index = block.rfind(b"\n", 0, index)
    return 0


def tail_bytes(path: Path, count: int) -> bytes:
    """Read the exact newline-delimited suffix, without rewriting raw output."""
    try:
        with path.open("rb") as handle:
            end = handle.seek(0, os.SEEK_END)
            offset = _tail_offset(handle, count, end)
            handle.seek(offset)
            return handle.read(end - offset)
    except FileNotFoundError:
        return b""
