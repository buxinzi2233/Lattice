"""Read CPU and memory through a serialized background system adapter."""
from __future__ import annotations
import os
from pathlib import Path
from dataclasses import dataclass
from PySide6.QtCore import QObject, QThread, Signal, Slot

def _read_cpu_percent(last: tuple[int, int] | None) -> tuple[float | None, tuple[int, int] | None]:
    if os.name == "nt":
        current = _read_windows_cpu_times()
        if current is None:
            raise OSError("GetSystemTimes did not return CPU counters")
        idle, total = current
    else:
        try:
            fields = Path("/proc/stat").read_text(encoding="utf-8").splitlines()[0].split()[1:]
            values = [int(value) for value in fields]
        except (OSError, ValueError, IndexError) as exc:
            raise OSError(f"Cannot read CPU counters from /proc/stat: {exc}") from exc
        if len(values) < 4:
            raise OSError("Invalid /proc/stat: at least four CPU counters are required")
        idle = values[3] + (values[4] if len(values) > 4 else 0)
        total = sum(values)
    current = (idle, total)
    if last is None:
        return None, current
    total_delta = total - last[1]
    if total_delta <= 0:
        return None, current
    value = (1 - (idle - last[0]) / total_delta) * 100
    return max(0.0, min(100.0, value)), current

def _read_windows_cpu_times() -> tuple[int, int] | None:
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    class FileTime(ctypes.Structure):
        _fields_ = (("low", wintypes.DWORD), ("high", wintypes.DWORD))

        def value(self) -> int:
            return (self.high << 32) | self.low

    idle = FileTime()
    kernel = FileTime()
    user = FileTime()
    if not ctypes.windll.kernel32.GetSystemTimes(
        ctypes.byref(idle),
        ctypes.byref(kernel),
        ctypes.byref(user),
    ):
        raise ctypes.WinError()
    return idle.value(), kernel.value() + user.value()

def _read_memory() -> tuple[float, str] | None:
    if os.name == "nt":
        return _read_windows_memory()
    try:
        values: dict[str, int] = {}
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            key, raw = line.split(":", 1)
            values[key] = int(raw.strip().split()[0])
        total = values["MemTotal"]
        available = values["MemAvailable"]
    except (OSError, ValueError, KeyError, IndexError) as exc:
        raise OSError(f"Cannot read memory counters from /proc/meminfo: {exc}") from exc
    if total <= 0:
        raise OSError("Invalid /proc/meminfo: MemTotal must be positive")
    used = total - available
    return used / total * 100, f"{used / 1024 / 1024:.1f} / {total / 1024 / 1024:.1f} GiB"

def _read_windows_memory() -> tuple[float, str] | None:
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    class MemoryStatus(ctypes.Structure):
        _fields_ = (
            ("length", wintypes.DWORD),
            ("memory_load", wintypes.DWORD),
            ("total_physical", ctypes.c_ulonglong),
            ("available_physical", ctypes.c_ulonglong),
            ("total_page_file", ctypes.c_ulonglong),
            ("available_page_file", ctypes.c_ulonglong),
            ("total_virtual", ctypes.c_ulonglong),
            ("available_virtual", ctypes.c_ulonglong),
            ("available_extended_virtual", ctypes.c_ulonglong),
        )

    status = MemoryStatus()
    status.length = ctypes.sizeof(status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        raise ctypes.WinError()
    if status.total_physical <= 0:
        raise OSError("GlobalMemoryStatusEx returned a non-positive physical memory size")
    used = status.total_physical - status.available_physical
    gib = 1024**3
    return used / status.total_physical * 100, f"{used / gib:.1f} / {status.total_physical / gib:.1f} GiB"


@dataclass(frozen=True, slots=True)
class HardwareSample:
    cpu: float | None
    memory: tuple[float, str] | None
    cpu_error: str
    memory_error: str


class HardwareWorker(QObject):
    ready = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.previous: tuple[int, int] | None = None

    @Slot()
    def read(self) -> None:
        cpu_error = ""
        memory_error = ""
        try:
            cpu, self.previous = _read_cpu_percent(self.previous)
        except OSError as exc:
            cpu = None
            cpu_error = str(exc)
        try:
            memory = _read_memory()
        except OSError as exc:
            memory = None
            memory_error = str(exc)
        self.ready.emit(HardwareSample(cpu, memory, cpu_error, memory_error))


class HardwareService(QObject):
    requested = Signal()
    ready = Signal(object)

    def __init__(self, parent: QObject) -> None:
        super().__init__(parent)
        self.thread = QThread(self)
        self.worker = HardwareWorker()
        self.worker.moveToThread(self.thread)
        self.thread.finished.connect(self.worker.deleteLater)
        self.requested.connect(self.worker.read)
        self.worker.ready.connect(self._receive)
        self.busy = False
        self.thread.start()

    def read(self) -> None:
        if not self.busy:
            self.busy = True
            self.requested.emit()

    @Slot(object)
    def _receive(self, sample: HardwareSample) -> None:
        self.busy = False
        self.ready.emit(sample)

    def shutdown(self) -> None:
        self.thread.quit()
        if not self.thread.wait(3000):
            raise OSError("硬件查询线程未在 3 秒内结束")
