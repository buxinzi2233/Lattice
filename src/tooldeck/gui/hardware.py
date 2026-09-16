"""Read CPU and memory through a serialized background system adapter."""
from __future__ import annotations
import os
from pathlib import Path
from dataclasses import dataclass
from PySide6.QtCore import QObject, QThread, Signal, Slot

from tooldeck.telemetry import read_cpu_percent as _read_cpu_percent, read_memory as _read_memory


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
