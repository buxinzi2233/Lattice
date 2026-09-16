"""Qt adapters that keep process and log I/O away from the scene thread."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import time
from pathlib import Path
from typing import Literal

from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot

from tooldeck.application import ImportPlan, ToolDeckApplication
from tooldeck.launchers import LaunchAnalysis
from tooldeck.catalog import CatalogError, CatalogSnapshot, ToolCatalog
from tooldeck.config import ConfigError, ToolConfig
from tooldeck.layout import LayoutError
from tooldeck.procs import ProcManager, ProcessError, ToolStatus
from tooldeck.tailer import LogBatch, LogTailer

Operation = Literal["start", "stop", "restart"]


@dataclass(frozen=True, slots=True)
class OperationRequest:
    request_id: int
    tool: ToolConfig
    action: Operation


@dataclass(frozen=True, slots=True)
class OperationResult:
    request_id: int
    tool_id: str
    action: Operation
    error: str


@dataclass(frozen=True, slots=True)
class StatusSnapshot:
    statuses: dict[str, ToolStatus]
    errors: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CatalogRequest:
    request_id: int
    operation: Callable[[ToolDeckApplication], CatalogSnapshot]


@dataclass(frozen=True, slots=True)
class CatalogResult:
    request_id: int
    snapshot: CatalogSnapshot | None
    error: str


QueryValue = ImportPlan | LaunchAnalysis


@dataclass(frozen=True, slots=True)
class QueryRequest:
    request_id: int
    operation: Callable[[ToolDeckApplication], QueryValue]


@dataclass(frozen=True, slots=True)
class QueryResult:
    request_id: int
    value: QueryValue | None
    error: str


class ProcessWorker(QObject):
    queryCompleted = Signal(object)
    catalogCompleted = Signal(object)
    polled = Signal()
    snapshot = Signal(object)
    completed = Signal(object)

    def __init__(self, application: ToolDeckApplication) -> None:
        super().__init__()
        self.application = application
        self.manager = application.runtime
        self.tools: dict[str, ToolConfig] = {}
        self.waiting: dict[str, OperationRequest] = {}
        self.deadlines: dict[str, float] = {}

    @Slot(object)
    def query(self, request: QueryRequest) -> None:
        try:
            self.queryCompleted.emit(QueryResult(request.request_id, request.operation(self.application), ""))
        except (CatalogError, ConfigError, LayoutError, ProcessError, OSError) as exc:
            self.queryCompleted.emit(QueryResult(request.request_id, None, str(exc)))

    @Slot(object)
    def update_catalog(self, request: CatalogRequest) -> None:
        try:
            snapshot = request.operation(self.application)
        except (CatalogError, ConfigError, LayoutError, ProcessError, OSError) as exc:
            self.catalogCompleted.emit(CatalogResult(request.request_id, None, str(exc)))
            return
        self.tools = dict(snapshot.tools)
        self.catalogCompleted.emit(CatalogResult(request.request_id, snapshot, ""))
        self.refresh()

    @Slot(object)
    def configure(self, tools: dict[str, ToolConfig]) -> None:
        self.tools = dict(tools)
        self.refresh()

    @Slot(object)
    def operate(self, request: OperationRequest) -> None:
        try:
            if request.action == "start":
                self.application.start(request.tool.id)
                self.completed.emit(OperationResult(request.request_id, request.tool.id, request.action, ""))
            else:
                if request.action == "restart":
                    report = self.application.preflight_tool(request.tool)
                    if report.blocking:
                        raise ConfigError("；".join(report.blocking_messages))
                self.application.stop_begin(request.tool.id)
                self.waiting[request.tool.id] = request
                self.deadlines[request.tool.id] = time.monotonic() + request.tool.stop_timeout + 6
        except (ConfigError, ProcessError, OSError) as exc:
            self.completed.emit(OperationResult(request.request_id, request.tool.id, request.action, str(exc)))
        self.refresh()

    @Slot()
    def poll_once(self) -> None:
        self.refresh()
        self.polled.emit()

    @Slot()
    def refresh(self) -> None:
        if isinstance(self.manager, ProcManager):
            with self.manager.snapshot_groups():
                self._refresh_snapshot()
        else:
            self._refresh_snapshot()

    def _refresh_snapshot(self) -> None:
        errors: list[str] = []
        statuses: dict[str, ToolStatus] = {}
        try:
            self.manager.tick()
        except (ConfigError, ProcessError, OSError) as exc:
            errors.append(str(exc))
        for tool_id in self.tools:
            try:
                status = self.manager.status(tool_id)
            except (ConfigError, ProcessError, OSError) as exc:
                status = ToolStatus(tool_id, "error", message=str(exc))
                errors.append(str(exc))
            request = self.waiting.get(tool_id)
            if request is not None and status.active and time.monotonic() > self.deadlines[tool_id]:
                self.waiting.pop(tool_id)
                self.completed.emit(OperationResult(request.request_id, tool_id, request.action, "停止进程树超过期限，请检查进程状态"))
            elif request is not None and (status.state == "error"):
                self.waiting.pop(tool_id)
                self.completed.emit(OperationResult(request.request_id, tool_id, request.action, status.message or "状态不可读"))
            elif request is not None and not status.active:
                self.waiting.pop(tool_id)
                try:
                    if request.action == "restart":
                        status = self.application.start(request.tool.id)
                    self.completed.emit(OperationResult(request.request_id, tool_id, request.action, ""))
                except (ConfigError, ProcessError, OSError) as exc:
                    self.completed.emit(OperationResult(request.request_id, tool_id, request.action, str(exc)))
            if tool_id not in self.waiting:
                self.deadlines.pop(tool_id, None)
            statuses[tool_id] = status
        self.snapshot.emit(StatusSnapshot(statuses, tuple(errors)))


class ProcessService(QObject):
    """Serialize lifecycle requests and coalesce polling before crossing threads."""
    queryRequested = Signal(object)
    queryCompleted = Signal(object)
    catalogRequested = Signal(object)
    catalogCompleted = Signal(object)
    configured = Signal(object)
    requested = Signal(object)
    poll = Signal()
    snapshot = Signal(object)
    completed = Signal(object)
    pendingChanged = Signal()

    def __init__(self, parent: QObject, application: ToolDeckApplication) -> None:
        super().__init__(parent)
        self.thread = QThread(self)
        self.worker = ProcessWorker(application)
        self.queryRequested.connect(self.worker.query)
        self.worker.queryCompleted.connect(self.queryCompleted)
        self.catalogRequested.connect(self.worker.update_catalog)
        self.worker.catalogCompleted.connect(self.catalogCompleted)
        self.worker.moveToThread(self.thread)
        self.thread.finished.connect(self.worker.deleteLater)
        self.configured.connect(self.worker.configure)
        self.requested.connect(self.worker.operate)
        self.poll.connect(self.worker.poll_once)
        self.worker.polled.connect(self._poll_completed)
        self.worker.snapshot.connect(self._snapshot)
        self.worker.completed.connect(self._completed)
        self.pending: dict[str, OperationRequest] = {}
        self._serial = 0
        self._polling = False
        self.thread.start()

    def request_query(self, operation: Callable[[ToolDeckApplication], QueryValue]) -> int:
        self._serial += 1
        self.queryRequested.emit(QueryRequest(self._serial, operation))
        return self._serial

    def request_catalog(self, operation: Callable[[ToolDeckApplication], CatalogSnapshot]) -> int:
        self._serial += 1
        self.catalogRequested.emit(CatalogRequest(self._serial, operation))
        return self._serial

    def configure(self, tools: dict[str, ToolConfig]) -> None:
        self.configured.emit(dict(tools))

    def request(self, tool: ToolConfig, action: Operation) -> None:
        if tool.id in self.pending:
            raise ProcessError(f"{tool.name} 的 {self.pending[tool.id].action} 操作尚未完成")
        self._serial += 1
        request = OperationRequest(self._serial, tool, action)
        self.pending[tool.id] = request
        self.pendingChanged.emit()
        self.requested.emit(request)

    @Slot()
    def refresh(self) -> None:
        if not self._polling:
            self._polling = True
            self.poll.emit()

    @Slot(object)
    def _snapshot(self, snapshot: StatusSnapshot) -> None:
        self.snapshot.emit(snapshot)

    @Slot()
    def _poll_completed(self) -> None:
        self._polling = False

    @Slot(object)
    def _completed(self, result: OperationResult) -> None:
        self.pending.pop(result.tool_id, None)
        self.pendingChanged.emit()
        self.completed.emit(result)

    def shutdown(self) -> None:
        if isinstance(self.worker.manager, ProcManager):
            self.worker.manager.close()
        if isinstance(self.worker.application.catalog, ToolCatalog):
            self.worker.application.catalog.close()
        self.thread.quit()
        if not self.thread.wait(6000):
            raise ProcessError("进程控制线程未在 6 秒内完成当前操作")


@dataclass(frozen=True, slots=True)
class LogSelection:
    generation: int
    path: Path | None


@dataclass(frozen=True, slots=True)
class LogDelivery:
    generation: int
    batch: LogBatch
    error: str


class LogWorker(QObject):
    delivered = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.generation = 0
        self.tailer: LogTailer | None = None

    @Slot(object)
    def select(self, selection: LogSelection) -> None:
        self.generation = selection.generation
        self.tailer = LogTailer(selection.path) if selection.path is not None else None
        try:
            if self.tailer is not None:
                self.tailer.seek_tail(512 * 1024)
            self.read()
        except OSError as exc:
            self.delivered.emit(LogDelivery(self.generation, LogBatch("", "", False), str(exc)))

    @Slot(int)
    def clear(self, generation: int) -> None:
        self.generation = generation
        try:
            if self.tailer is not None:
                self.tailer.seek_end()
            self.delivered.emit(LogDelivery(self.generation, LogBatch("", "", False), ""))
        except OSError as exc:
            self.delivered.emit(LogDelivery(self.generation, LogBatch("", "", False), str(exc)))

    @Slot()
    def read(self) -> None:
        try:
            batch = self.tailer.read_chunk(64 * 1024) if self.tailer is not None else LogBatch("", "", False)
            self.delivered.emit(LogDelivery(self.generation, batch, ""))
        except OSError as exc:
            self.delivered.emit(LogDelivery(self.generation, LogBatch("", "", False), str(exc)))


class LogService(QObject):
    selection = Signal(object)
    poll = Signal()
    cleared = Signal(int)
    delivered = Signal(object)

    def __init__(self, parent: QObject) -> None:
        super().__init__(parent)
        self.thread = QThread(self)
        self.worker = LogWorker()
        self.worker.moveToThread(self.thread)
        self.thread.finished.connect(self.worker.deleteLater)
        self.selection.connect(self.worker.select)
        self.poll.connect(self.worker.read)
        self.cleared.connect(self.worker.clear)
        self.worker.delivered.connect(self._receive)
        self.generation = 0
        self._busy = False
        self.thread.start()

    def select(self, path: Path | None) -> None:
        self.generation += 1
        self._busy = True
        self.selection.emit(LogSelection(self.generation, path))

    def read(self) -> None:
        if not self._busy:
            self._busy = True
            self.poll.emit()

    def clear(self) -> None:
        self.generation += 1
        self._busy = True
        self.cleared.emit(self.generation)

    @Slot(object)
    def _receive(self, delivery: LogDelivery) -> None:
        if delivery.generation == self.generation:
            self._busy = False
            self.delivered.emit(delivery)

    def shutdown(self) -> None:
        self.thread.quit()
        if not self.thread.wait(3000):
            raise OSError("日志读取线程未在 3 秒内结束")
