from __future__ import annotations

from .preferences import application_settings

import hashlib
import math
import os
import re
import shlex
import shutil
import subprocess
import sys
import unicodedata
from datetime import datetime
from dataclasses import replace
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Property, QProcess, QSettings, QThreadPool, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QSystemTrayIcon

from tooldeck import paths
from tooldeck.config import ConfigError, ToolConfig, default_shell, delete, import_toml, load_all, load_file, save
from tooldeck.layout import LayoutError, LayoutState, load as load_layout, move_item, reconcile, save as save_layout
from tooldeck.procs import ProcManager, ProcessError, ToolStatus
from tooldeck.tailer import LogTailer, LogBatch
from tooldeck.util import fmt_duration, short_home, strip_ansi

from .tool_model import STATE_COLORS, STATE_LABELS, ToolListModel
from .hardware import HardwareService, HardwareSample
from .workers import ProcessService, LogService, LogDelivery, StatusSnapshot, OperationResult, Operation


class AppBridge(QObject):
    selectedChanged = Signal()
    selectionIdentityChanged = Signal()
    filtersChanged = Signal()
    summaryChanged = Signal()
    logChanged = Signal()
    telemetryChanged = Signal()
    hardwarePausedChanged = Signal()
    trayAvailableChanged = Signal()
    fontScaleChanged = Signal()
    layoutChanged = Signal()
    startupChanged = Signal()
    startupImageChanged = Signal()
    toastRequested = Signal(str, str)
    dialogRequested = Signal(str, str, str)
    editorRequested = Signal(str, "QVariantMap")
    importOverwriteRequested = Signal(str, str, str)
    exitRequested = Signal()

    FONT_SCALE_MIN = 0.80
    FONT_SCALE_MAX = 1.50
    FONT_SCALE_DEFAULT = 1.00
    FONT_SCALE_KEY = "ui/font_scale"

    def __init__(
        self,
        manager: ProcManager | None = None,
        *,
        auto_start_timers: bool = True,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.manager = manager
        self.process_service = ProcessService(self) if manager is None else None
        self.log_service = LogService(self) if manager is None else None
        self._layout_error = ""
        self._status_errors: tuple[str, ...] = ()
        self._log_preview = ""
        self._closed = False
        self._autostart_done = False
        self._autostart_pending: set[str] = set()
        if self.process_service is not None:
            self.process_service.snapshot.connect(self._receive_status)
            self.process_service.completed.connect(self._operation_completed)
            self.process_service.pendingChanged.connect(self.selectedChanged)
        if self.log_service is not None:
            self.log_service.delivered.connect(self._receive_log)
        self.hardware_service = HardwareService(self)
        self.hardware_service.ready.connect(self._hardware_ready)
        self.model = ToolListModel(self)
        self.model.countsChanged.connect(self.summaryChanged)
        self._tools: dict[str, ToolConfig] = {}
        self._statuses: dict[str, ToolStatus] = {}
        self._selected_id = ""
        self._search_text = ""
        self._filter_mode = "all"
        self._tailer: LogTailer | None = None
        self._log_text = ""
        self._pending_restart: set[str] = set()
        self._last_cpu_sample: tuple[int, int] | None = None
        self._base_hardware_metrics = 0
        self._hardware_paused = False
        self._telemetry = self._empty_telemetry()
        self._tray_icon: QSystemTrayIcon | None = None
        self._allow_close = False
        self._settings = application_settings()
        self._font_scale = self._normalize_font_scale(
            self._settings.value(self.FONT_SCALE_KEY, self.FONT_SCALE_DEFAULT)
        )
        self._layout = LayoutState()
        self._startup_mode = str(self._settings.value("startup/mode", "daily"))
        if self._startup_mode not in {"always", "daily", "off"}:
            self._startup_mode = "daily"
        self._startup_content = None
        self._startup_image_url = ""
        self._startup_image_tasks: set[object] = set()
        self._startup_auto_launch = False

        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self.refreshStatus)
        self.log_timer = QTimer(self)
        self.log_timer.timeout.connect(self._tail_log)
        self.hardware_timer = QTimer(self)
        self.hardware_timer.timeout.connect(self.queryHardware)
        self.hardware_warmup_timer = QTimer(self)
        self.hardware_warmup_timer.setSingleShot(True)
        self.hardware_warmup_timer.timeout.connect(self.queryHardware)

        self._gpu_failure = ""
        self.gpu_timeout = QTimer(self)
        self.gpu_timeout.setSingleShot(True)
        self.gpu_timeout.timeout.connect(self._gpu_timed_out)
        self.gpu_process = QProcess(self)
        self.gpu_process.finished.connect(self._gpu_finished)
        self.gpu_process.errorOccurred.connect(self._gpu_error)

        self.reloadTools(False)
        if auto_start_timers:
            self.status_timer.start(1000)
            self.log_timer.start(250)
            self.hardware_timer.start(5000)
            self.queryHardware()
            self.hardware_warmup_timer.start(350)

    @staticmethod
    def _empty_telemetry() -> dict[str, Any]:
        return {
            "state": "SYNC",
            "stateLabel": "连接中",
            "updated": "--:--:--",
            "cpuValue": -1.0,
            "cpuText": "采样中",
            "cpuDetail": "",
            "memoryValue": -1.0,
            "memoryText": "未读取",
            "memoryDetail": "",
            "gpuValue": -1.0,
            "gpuText": "未读取",
            "gpuDetail": "",
            "gpuName": "",
        }


    @Property(QObject, constant=True)
    def toolModel(self) -> ToolListModel:
        return self.model

    @Property(str, notify=selectionIdentityChanged)
    def selectedId(self) -> str:
        return self._selected_id

    @Property("QVariantMap", notify=selectedChanged)
    def selected(self) -> dict[str, Any]:
        tool = self._tools.get(self._selected_id)
        if tool is None:
            return {}
        status = self._statuses.get(tool.id, ToolStatus(tool.id, "stopped"))
        return {
            "id": tool.id,
            "name": tool.name,
            "group": tool.group,
            "groupLabel": tool.group or "未分组",
            "cmd": tool.cmd,
            "cwd": tool.cwd,
            "cwdShort": short_home(tool.cwd),
            "shell": tool.shell,
            "envText": "\n".join(f"{key}={value}" for key, value in sorted(tool.env.items())),
            "envCount": len(tool.env),
            "autostart": tool.autostart,
            "stopSignal": tool.stop_signal,
            "stopTimeout": tool.stop_timeout,
            "state": status.state,
            "stateLabel": STATE_LABELS.get(status.state, status.state),
            "stateColor": STATE_COLORS.get(status.state, STATE_COLORS["stopped"]),
            "active": status.active,
            "pending": self.process_service is not None and tool.id in self.process_service.pending,
            "pid": status.pid or 0,
            "pidText": str(status.pid) if status.pid else "----",
            "uptime": fmt_duration(status.uptime),
            "exitCode": status.exit_code if status.exit_code is not None else "--",
            "message": status.message or "",
            "logPath": str(paths.log_file(tool.id)),
        }


    @Property(str, notify=filtersChanged)
    def searchText(self) -> str:
        return self._search_text

    @Property(str, notify=filtersChanged)
    def filterMode(self) -> str:
        return self._filter_mode

    @Property(str, notify=summaryChanged)
    def globalSummary(self) -> str:
        return f"{self.model.runningCount:02d} ACTIVE / {self.model.totalCount:02d} UNITS"

    @Property("QStringList", notify=summaryChanged)
    def groupNames(self) -> list[str]:
        return sorted({tool.group for tool in self._tools.values() if tool.group}, key=str.casefold)

    @Property(str, notify=logChanged)
    def logText(self) -> str:
        return self._log_text

    @Property("QVariantMap", notify=telemetryChanged)
    def telemetry(self) -> dict[str, Any]:
        return dict(self._telemetry)

    @Property(bool, notify=hardwarePausedChanged)
    def hardwarePaused(self) -> bool:
        return self._hardware_paused

    @Property(bool, notify=trayAvailableChanged)
    def trayAvailable(self) -> bool:
        return self._tray_icon is not None and self._tray_icon.isVisible()

    @Property(float, notify=fontScaleChanged)
    def fontScale(self) -> float:
        return self._font_scale

    @Property(bool, notify=filtersChanged)
    def reorderingAllowed(self) -> bool:
        return not self._layout_error and not bool(self._search_text.strip()) and self._filter_mode == "all"

    @Property("QStringList", notify=layoutChanged)
    def groupOrder(self) -> list[str]:
        return [group or "未分组" for group in self._layout.group_order]

    @Property(str, notify=startupChanged)
    def startupMode(self) -> str:
        return self._startup_mode

    @Property(bool, notify=startupChanged)
    def startupShouldShow(self) -> bool:
        from tooldeck.startup import StartupPreferences

        return StartupPreferences(self._settings).should_show(self._startup_mode)

    @Property(bool, notify=startupChanged)
    def startupAutoLaunch(self) -> bool:
        return self._startup_auto_launch

    @Property("QVariantMap", notify=startupChanged)
    def startupContent(self) -> dict[str, Any]:
        self._prepare_startup_content()
        return dict(self._startup_content)

    @Property(str, notify=startupImageChanged)
    def startupImageUrl(self) -> str:
        self._prepare_startup_content()
        return self._startup_image_url

    def _prepare_startup_content(self) -> None:
        if self._startup_content is not None:
            return
        from tooldeck.startup import choose_startup_content

        self._startup_content = choose_startup_content(self._settings)
        self._startup_image_url = ""
        self._start_startup_image(self._startup_content)

    def _start_startup_image(self, content: dict[str, Any]) -> None:
        from tooldeck.startup import cached_image_url, create_image_task

        if not content.get("image_url"):
            return
        cached = cached_image_url(paths.startup_cache_dir(), content)
        if cached:
            self._startup_image_url = cached
            self.startupImageChanged.emit()
            return
        key = str(content.get("id", ""))
        task = create_image_task(content, paths.startup_cache_dir())
        self._startup_image_tasks.add(task)
        task.signals.ready.connect(self._startup_image_ready)
        task.signals.failed.connect(self._startup_image_failed)
        QThreadPool.globalInstance().start(task)

    @Slot(str, object)
    def _startup_image_ready(self, url: str, task: object) -> None:
        self._startup_image_tasks.discard(task)
        key = str(getattr(task, "entry", {}).get("id", ""))
        if self._startup_content is None or str(self._startup_content.get("id", "")) != key:
            return
        self._startup_image_url = url
        self.startupImageChanged.emit()

    @Slot(str, object)
    def _startup_image_failed(self, message: str, task: object) -> None:
        self._startup_image_tasks.discard(task)
        self.toastRequested.emit(f"启动图片加载失败：{message}", "warning")

    @classmethod
    def _normalize_font_scale(cls, value: Any) -> float:
        try:
            scale = float(value)
        except (TypeError, ValueError):
            scale = cls.FONT_SCALE_DEFAULT
        if not math.isfinite(scale):
            scale = cls.FONT_SCALE_DEFAULT
        return round(max(cls.FONT_SCALE_MIN, min(cls.FONT_SCALE_MAX, scale)), 2)

    @Slot(float)
    def setFontScale(self, scale: float) -> None:
        normalized = self._normalize_font_scale(scale)
        if normalized == self._font_scale:
            return
        self._font_scale = normalized
        self._settings.setValue(self.FONT_SCALE_KEY, normalized)
        self._settings.sync()
        self.fontScaleChanged.emit()

    @Slot(str)
    def setStartupMode(self, mode: str) -> None:
        normalized = mode if mode in {"always", "daily", "off"} else "daily"
        if normalized == self._startup_mode:
            return
        self._startup_mode = normalized
        self._settings.setValue("startup/mode", normalized)
        self._settings.sync()
        self.startupChanged.emit()

    @Slot()
    def markStartupShown(self) -> None:
        from tooldeck.startup import StartupPreferences

        StartupPreferences(self._settings).mark_shown()
        self.startupChanged.emit()

    @Slot()
    def previewStartup(self) -> None:
        self._startup_content = None
        self._startup_image_url = ""
        self._prepare_startup_content()
        self.startupChanged.emit()
        self.startupImageChanged.emit()

    @Slot(bool)
    def setStartupAutoLaunch(self, enabled: bool) -> None:
        self._startup_auto_launch = bool(enabled)
        self.startupChanged.emit()

    @Slot(result=bool)
    def clearStartupCache(self) -> bool:
        from tooldeck.startup import clear_cache

        removed = clear_cache(paths.startup_cache_dir())
        self._startup_image_url = ""
        self.startupImageChanged.emit()
        self.toastRequested.emit(f"已清理 {removed} 个启动素材缓存", "success")
        return True

    def _set_log_text(self, text: str) -> None:
        self._log_preview = ""
        if text == self._log_text:
            return
        self._log_text = text[-1_500_000:]
        self.logChanged.emit()

    def _select_first_visible(self) -> None:
        candidate = self.model.visible_ids[0] if self.model.visible_ids else ""
        self.selectTool(candidate)

    def _sync_model(self, previous_selected_id: str | None = None) -> None:
        previous = self._selected_id if previous_selected_id is None else previous_selected_id
        self.model.set_tools(self._tools, self._statuses)
        self.model.set_filter(self._search_text, self._filter_mode)
        if self._selected_id not in self._tools:
            self._selected_id = ""
        if not self._selected_id and self.model.visible_ids:
            self._selected_id = self.model.visible_ids[0]
        if self._selected_id != previous:
            self.selectionIdentityChanged.emit()
        self.selectedChanged.emit()
        self.summaryChanged.emit()

    def _load_layout(self) -> None:
        try:
            loaded = load_layout(paths.layout_json())
            self._layout_error = ""
        except LayoutError as exc:
            self._layout_error = str(exc)
            message = self._layout_error
            QTimer.singleShot(0, lambda: self.dialogRequested.emit("布局读取失败", message, "error"))
            loaded = self._layout
        self._layout = reconcile(self._tools, loaded)
        self.model.set_layout(self._layout)
        self.filtersChanged.emit()

    def _save_layout(self) -> bool:
        if self._layout_error:
            self.dialogRequested.emit("布局需要修复", self._layout_error, "error")
            return False
        try:
            self._layout = reconcile(self._tools, self._layout)
            save_layout(paths.layout_json(), self._layout)
        except OSError as exc:
            self._load_layout()
            self._sync_model()
            self.dialogRequested.emit("布局未保存", f"工具分组以已保存的配置为准；布局写入失败：{exc}", "error")
            return False
        self.model.set_layout(self._layout)
        self.layoutChanged.emit()
        return True


    @Slot(str)
    def selectTool(self, tool_id: str) -> None:
        selected = tool_id if tool_id in self._tools else ""
        if selected == self._selected_id:
            return
        self._selected_id = selected
        self._reset_log_tailer()
        self.selectionIdentityChanged.emit()
        self.selectedChanged.emit()

    @Slot(str)
    def setSearchText(self, text: str) -> None:
        if text == self._search_text:
            return
        self._search_text = text
        self.model.set_filter(text, self._filter_mode)
        if self.model.visible_ids and self._selected_id not in self.model.visible_ids:
            self.selectTool(self.model.visible_ids[0])
        self.filtersChanged.emit()

    @Slot(str)
    def setFilterMode(self, mode: str) -> None:
        normalized = mode if mode in {"all", "running", "stopped"} else "all"
        if normalized == self._filter_mode:
            return
        self._filter_mode = normalized
        self.model.set_filter(self._search_text, normalized)
        if self.model.visible_ids and self._selected_id not in self.model.visible_ids:
            self.selectTool(self.model.visible_ids[0])
        self.filtersChanged.emit()


    @Slot()
    def clearFilters(self) -> None:
        changed = bool(self._search_text) or self._filter_mode != "all"
        self._search_text = ""
        self._filter_mode = "all"
        self.model.set_filter("", "all")
        if self.model.visible_ids and self._selected_id not in self.model.visible_ids:
            self.selectTool(self.model.visible_ids[0])
        if changed:
            self.filtersChanged.emit()


    @staticmethod
    def _group_key(value: str) -> str:
        return "" if value in {"", "未分组"} else value.strip()

    @Slot(str, result=bool)
    def toggleGroup(self, group: str) -> bool:
        key = self._group_key(group)
        if key not in self._layout.group_order:
            return False
        if key in self._layout.collapsed_groups:
            self._layout.collapsed_groups.remove(key)
        else:
            self._layout.collapsed_groups.add(key)
        saved = self._save_layout()
        return saved

    @Slot(str, bool, result=bool)
    def setGroupCollapsed(self, group: str, collapsed: bool) -> bool:
        key = self._group_key(group)
        if key not in self._layout.group_order:
            return False
        if collapsed:
            self._layout.collapsed_groups.add(key)
        else:
            self._layout.collapsed_groups.discard(key)
        return self._save_layout()

    @Slot(str, str, int, result=bool)
    def moveTool(self, tool_id: str, target_group: str, target_index: int) -> bool:
        """Move a tool within or across groups and persist its new group."""
        if not self.reorderingAllowed or tool_id not in self._tools:
            return False
        target = self._group_key(target_group)
        if target not in self._layout.group_order:
            return False
        source = self._tools[tool_id].group or ""
        if source == target and tool_id not in self._layout.tool_order.get(source, []):
            return False
        source_order = [item for item in self._layout.tool_order.get(source, []) if item != tool_id]
        target_order = [item for item in self._layout.tool_order.get(target, []) if item != tool_id]
        if source == target:
            original_index = self._layout.tool_order.get(source, []).index(tool_id)
            if original_index < target_index:
                target_index -= 1
        if source != target:
            try:
                updated = replace(self._tools[tool_id], group=target)
                save(updated)
                self._tools[tool_id] = updated
            except (ConfigError, OSError) as exc:
                self.dialogRequested.emit("无法移动工具", str(exc), "error")
                return False
        self._layout.tool_order[source] = source_order
        self._layout.tool_order[target] = move_item(target_order, tool_id, target_index)
        saved = self._save_layout()
        self._sync_model(self._selected_id)
        return saved

    @Slot(str, result=int)
    def groupToolCount(self, group: str) -> int:
        return len(self._layout.tool_order.get(self._group_key(group), []))

    @Slot(str, int, result=bool)
    def moveGroup(self, group: str, target_index: int) -> bool:
        if not self.reorderingAllowed:
            return False
        key = self._group_key(group)
        if key not in self._layout.group_order:
            return False
        self._layout.group_order = move_item(self._layout.group_order, key, target_index)
        saved = self._save_layout()
        self._sync_model(self._selected_id)
        return saved

    @Slot(bool)
    def reloadTools(self, show_issues: bool = True) -> None:
        current = self._selected_id
        self._tools, issues = load_all()
        self._load_layout()
        if self.process_service is not None:
            self._statuses = {tool_id: self._statuses.get(tool_id, ToolStatus(tool_id, "loading")) for tool_id in self._tools}
            self.process_service.configure(self._tools)
        else:
            self._statuses = {tool_id: self.manager.status(tool_id) for tool_id in self._tools}
        self._selected_id = current if current in self._tools else ""
        self._sync_model(current)
        if self._selected_id:
            self._reset_log_tailer()
        if show_issues:
            if issues:
                message = "\n".join(f"{issue.path.name}: {issue.message}" for issue in issues)
                self.dialogRequested.emit("配置读取异常", message, "warning")
            elif not self._layout_error:
                self.toastRequested.emit("配置索引已重载", "success")

    @Slot()
    def refreshStatus(self) -> None:
        if self.process_service is not None:
            self.process_service.refresh()
            return
        try:
            self.manager.tick()
        except ProcessError as exc:
            self.dialogRequested.emit("状态同步失败", str(exc), "error")
        updated = {tool_id: self.manager.status(tool_id) for tool_id in self._tools}
        for tool_id in tuple(self._pending_restart):
            status = updated.get(tool_id)
            tool = self._tools.get(tool_id)
            if status is None or tool is None:
                self._pending_restart.discard(tool_id)
                continue
            if status.active:
                continue
            self._pending_restart.discard(tool_id)
            try:
                updated[tool_id] = self.manager.start(tool)
                self.toastRequested.emit(f"{tool.name} 已重新接入", "success")
                if tool_id == self._selected_id:
                    self._reset_log_tailer()
            except ProcessError as exc:
                self.dialogRequested.emit("无法重启", str(exc), "error")
        self._statuses = updated
        self._sync_model()

    @Slot(object)
    def _receive_status(self, snapshot: StatusSnapshot) -> None:
        previous = self.selected
        self._statuses = {key: value for key, value in snapshot.statuses.items() if key in self._tools}
        self.model.set_tools(self._tools, self._statuses)
        self._launch_autostart_ready()
        if self.selected != previous:
            self.selectedChanged.emit()
        if snapshot.errors != self._status_errors:
            self._status_errors = snapshot.errors
            if snapshot.errors:
                self.dialogRequested.emit("状态同步失败", "\n".join(snapshot.errors), "error")

    @Slot(object)
    def _operation_completed(self, result: OperationResult) -> None:
        if result.error:
            self.dialogRequested.emit("工具操作失败", f"{result.tool_id} / {result.action}：{result.error}", "error")
            return
        self.toastRequested.emit(f"{result.tool_id} / {result.action} 已完成", "success")
        if result.action in {"start", "restart"} and result.tool_id == self._selected_id:
            self._reset_log_tailer()

    def _request_operation(self, tool: ToolConfig, action: Operation) -> None:
        try:
            self.process_service.request(tool, action)
        except ProcessError as exc:
            self.dialogRequested.emit("无法执行操作", str(exc), "error")

    def _selected_tool(self) -> ToolConfig | None:
        return self._tools.get(self._selected_id)

    def _start(self, tool: ToolConfig, verb: str) -> None:
        if self.process_service is not None:
            self._request_operation(tool, "start")
            return
        try:
            status = self.manager.start(tool)
        except ProcessError as exc:
            self.dialogRequested.emit(f"无法{verb}", str(exc), "error")
            return
        self.toastRequested.emit(f"{tool.name} {verb}完成 · PID {status.pid}", "success")
        if self._selected_id == tool.id:
            self._reset_log_tailer()
        self.refreshStatus()

    @Slot()
    def startSelected(self) -> None:
        tool = self._selected_tool()
        if tool is not None:
            self._start(tool, "启动")

    @Slot()
    def stopSelected(self) -> None:
        tool = self._selected_tool()
        if tool is None:
            return
        if self.process_service is not None:
            self._request_operation(tool, "stop")
            return
        try:
            self.manager.stop_begin(tool)
        except ProcessError as exc:
            self.dialogRequested.emit("无法停止", str(exc), "error")
            return
        self.toastRequested.emit(f"正在停止 {tool.name}", "warning")
        self.refreshStatus()

    @Slot()
    def restartSelected(self) -> None:
        tool = self._selected_tool()
        if tool is None:
            return
        if self.process_service is not None:
            self._request_operation(tool, "restart")
            return
        status = self._statuses.get(tool.id)
        if status is None:
            status = self.manager.status(tool.id)
        if not status.active:
            self._start(tool, "重启")
            return
        try:
            self.manager.stop_begin(tool)
        except ProcessError as exc:
            self.dialogRequested.emit("无法重启", str(exc), "error")
            return
        self._pending_restart.add(tool.id)
        self.toastRequested.emit(f"{tool.name} 正在执行重启序列", "warning")
        self.refreshStatus()

    @Slot()
    def stopAll(self) -> None:
        if self.process_service is not None:
            for tool in self._tools.values():
                if self._statuses.get(tool.id, ToolStatus(tool.id, "loading")).active:
                    self._request_operation(tool, "stop")
            return
        failures = self.manager.stop_all_begin(self._tools)
        self._pending_restart.clear()
        if failures:
            self.dialogRequested.emit("部分工具未能停止", "\n".join(failures), "warning")
        else:
            self.toastRequested.emit("全部活动单元已收到停止指令", "warning")
        self.refreshStatus()

    @Slot()
    def startAutostart(self) -> None:
        if self._autostart_done:
            return
        self._autostart_done = True
        if self.process_service is not None:
            self._autostart_pending = {tool.id for tool in self._tools.values() if tool.autostart}
            self._launch_autostart_ready()
            return
        failures: list[str] = []
        for tool in self._tools.values():
            if not tool.autostart or self.manager.status(tool.id).active:
                continue
            try:
                self.manager.start(tool)
            except ProcessError as exc:
                failures.append(f"{tool.name}: {exc}")
        self.refreshStatus()
        if failures:
            self.dialogRequested.emit("部分自动启动失败", "\n".join(failures), "warning")

    def _launch_autostart_ready(self) -> None:
        for tool_id in tuple(self._autostart_pending):
            status = self._statuses.get(tool_id)
            if status is None or status.state == "loading":
                continue
            self._autostart_pending.discard(tool_id)
            if status.state in {"stopped", "exited"} and tool_id in self._tools:
                self._request_operation(self._tools[tool_id], "start")

    @staticmethod
    def _base_id(text: str) -> str:
        normalized = unicodedata.normalize("NFKD", text)
        ascii_text = normalized.encode("ascii", "ignore").decode().casefold()
        slug = re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")
        if slug:
            return slug[:64]
        if text:
            return f"tool-{hashlib.sha1(text.encode('utf-8')).hexdigest()[:8]}"
        return "tool"

    def _unique_id(self, text: str) -> str:
        base = self._base_id(text)
        candidate = base
        number = 2
        while candidate in self._tools:
            candidate = f"{base}-{number}"
            number += 1
        return candidate

    @Slot(str, result=str)
    def suggestToolId(self, text: str) -> str:
        return self._unique_id(text or "tool")

    @Slot(result="QVariantMap")
    def newToolDraft(self) -> dict[str, Any]:
        return {
            "originalId": "",
            "id": self._unique_id("tool"),
            "name": "",
            "group": "",
            "cwd": str(Path.home()),
            "cmd": "",
            "shell": default_shell(),
            "envText": "",
            "autostart": False,
            "stopSignal": "TERM",
            "stopTimeout": 10.0,
        }

    @Slot(result="QVariantMap")
    def selectedToolDraft(self) -> dict[str, Any]:
        tool = self._selected_tool()
        if tool is None:
            return {}
        return {
            "originalId": tool.id,
            "id": tool.id,
            "name": tool.name,
            "group": tool.group,
            "cwd": tool.cwd,
            "cmd": tool.cmd,
            "shell": tool.shell,
            "envText": "\n".join(f"{key}={value}" for key, value in sorted(tool.env.items())),
            "autostart": tool.autostart,
            "stopSignal": tool.stop_signal,
            "stopTimeout": tool.stop_timeout,
        }

    @staticmethod
    def _parse_env(text: str) -> dict[str, str]:
        env: dict[str, str] = {}
        for number, raw_line in enumerate(text.splitlines(), 1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                raise ConfigError(f"环境变量第 {number} 行缺少 =")
            key, value = line.split("=", 1)
            key = key.strip()
            if not key:
                raise ConfigError(f"环境变量第 {number} 行的名称为空")
            env[key] = value
        return env

    @Slot("QVariantMap", result=bool)
    def saveToolDraft(self, draft: dict[str, Any]) -> bool:
        try:
            required = ("originalId", "id", "name", "group", "cmd", "cwd", "shell", "envText", "stopSignal")
            for key in required:
                if key not in draft or not isinstance(draft[key], str):
                    raise ConfigError(f"编辑数据的 {key} 必须是字符串")
            if type(draft.get("autostart")) is not bool:
                raise ConfigError("编辑数据的 autostart 必须是布尔值")
            if type(draft.get("stopTimeout")) not in {int, float}:
                raise ConfigError("编辑数据的 stopTimeout 必须是数字")
            original_id = draft["originalId"].strip()
            tool_id = draft["id"].strip()
            if original_id and tool_id != original_id:
                raise ConfigError("已登记工具的 ID 不可更改")
            tool = ToolConfig.from_mapping(tool_id, {
                "name": draft["name"], "group": draft["group"], "cmd": draft["cmd"],
                "cwd": draft["cwd"], "shell": draft["shell"],
                "env": self._parse_env(draft["envText"]), "autostart": draft["autostart"],
                "stop_signal": draft["stopSignal"], "stop_timeout": draft["stopTimeout"],
            })
            save(tool, overwrite=bool(original_id))
        except (ConfigError, OSError, TypeError, ValueError) as exc:
            self.dialogRequested.emit("无法保存工具", str(exc), "error")
            return False
        self.reloadTools(False)
        self.selectTool(tool.id)
        self.toastRequested.emit(f"{tool.name} 已写入配置索引", "success")
        return True

    @Slot()
    def deleteSelected(self) -> None:
        tool = self._selected_tool()
        if tool is None:
            return
        status = self._statuses.get(tool.id, ToolStatus(tool.id, "stopped"))
        if status.active or status.state in {"loading", "error"} or (
            self.process_service is not None and tool.id in self.process_service.pending
        ):
            self.dialogRequested.emit("无法删除", "工具仍在运行，请先停止该单元", "warning")
            return
        try:
            delete(tool.id)
        except ConfigError as exc:
            self.dialogRequested.emit("无法删除工具", str(exc), "error")
            return
        name = tool.name
        self.reloadTools(False)
        self.toastRequested.emit(f"{name} 已从配置索引移除；磁盘日志保留", "warning")

    @staticmethod
    def command_for_launch_path(
        path: Path,
        shell: str | None = None,
        *,
        platform_name: str | None = None,
        python_executable: str | None = None,
    ) -> tuple[str, str]:
        source = Path(path).expanduser().resolve()
        selected_platform = platform_name or os.name
        selected_shell = shell or default_shell(selected_platform)
        selected_python = python_executable or sys.executable
        suffix = source.suffix.casefold()
        if selected_platform == "nt":
            if suffix == ".ps1":
                powershell = shutil.which("pwsh") or shutil.which("powershell") or "powershell.exe"
                escaped = str(source).replace("'", "''")
                return f"& '{escaped}'", powershell
            if suffix == ".exe":
                return f'start "" /wait {subprocess.list2cmdline([str(source)])}', default_shell("nt")
            if suffix in {".bat", ".cmd"}:
                return subprocess.list2cmdline([str(source)]), default_shell("nt")
            parts = [selected_python, str(source)] if suffix == ".py" else [str(source)]
            return subprocess.list2cmdline(parts), selected_shell
        if suffix == ".py":
            parts = [selected_python, str(source)]
        elif suffix == ".sh" and not os.access(source, os.X_OK):
            parts = [selected_shell, str(source)]
        else:
            parts = [str(source)]
        return shlex.join(parts), selected_shell

    @staticmethod
    def _path_from_url(value: str) -> Path:
        url = QUrl(value)
        raw = url.toLocalFile() if url.isLocalFile() else value
        return Path(raw).expanduser().resolve()

    @Slot(str, result=str)
    def pathFromUrl(self, value: str) -> str:
        return str(self._path_from_url(value))

    @Slot(str, str, result="QVariantMap")
    def launchDraftForPath(self, value: str, shell: str) -> dict[str, Any]:
        source = self._path_from_url(value)
        if not source.is_file():
            return {}
        command, selected_shell = self.command_for_launch_path(source, shell or default_shell())
        return {
            "name": source.stem,
            "cwd": str(source.parent),
            "cmd": command,
            "shell": selected_shell,
            "suggestedId": self._unique_id(source.stem),
        }

    @Slot(str)
    def prepareImport(self, value: str) -> None:
        source = self._path_from_url(value)
        if not source.is_file():
            self.dialogRequested.emit("无法导入", f"文件不存在：{source}", "error")
            return
        if source.suffix.casefold() == ".toml":
            try:
                candidate = load_file(source)
            except ConfigError as exc:
                self.dialogRequested.emit("无法读取配置", str(exc), "error")
                return
            if candidate.id in self._tools:
                self.importOverwriteRequested.emit(str(source), candidate.id, candidate.name)
                return
            self._import_toml(source, False)
            return
        command, shell = self.command_for_launch_path(source, default_shell())
        draft = self.newToolDraft()
        draft.update(
            id=self._unique_id(source.stem),
            name=source.stem,
            cwd=str(source.parent),
            cmd=command,
            shell=shell,
        )
        self.editorRequested.emit("import", draft)

    def _import_toml(self, source: Path, overwrite: bool) -> None:
        try:
            tool = import_toml(source, overwrite=overwrite)
        except ConfigError as exc:
            self.dialogRequested.emit("无法导入配置", str(exc), "error")
            return
        self.reloadTools(False)
        self.selectTool(tool.id)
        self.toastRequested.emit(f"{tool.name} 已导入配置索引", "success")

    @Slot(str)
    def confirmImportOverwrite(self, value: str) -> None:
        self._import_toml(self._path_from_url(value), True)

    @Slot()
    def openConfigDirectory(self) -> None:
        paths.ensure_dirs()
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(paths.tools_dir())))

    @staticmethod
    def _start_detached(program: str, arguments: list[str]) -> bool:
        result = QProcess.startDetached(program, arguments)
        return bool(result[0] if isinstance(result, tuple) else result)

    @classmethod
    def _reveal_path(cls, path: Path) -> bool:
        target = path.resolve()
        if sys.platform == "win32":
            return cls._start_detached("explorer.exe", [f"/select,{target}"])
        if sys.platform == "darwin":
            return cls._start_detached("open", ["-R", str(target)])

        reveal_commands = (
            ("thunar", ["--select", str(target)]),
            ("dolphin", ["--select", str(target)]),
            ("nautilus", ["--select", str(target)]),
            ("nemo", [str(target)]),
        )
        for program, arguments in reveal_commands:
            if shutil.which(program) and cls._start_detached(program, arguments):
                return True
        return QDesktopServices.openUrl(QUrl.fromLocalFile(str(target.parent)))

    @Slot()
    def openSelectedLog(self) -> None:
        tool = self._selected_tool()
        if tool is None:
            return
        path = paths.log_file(tool.id)
        if not path.exists():
            self.toastRequested.emit(f"{tool.name} 尚无磁盘日志", "warning")
            return
        if self._reveal_path(path):
            self.toastRequested.emit(f"已在文件管理器中定位 {path.name}", "success")
        else:
            self.dialogRequested.emit(
                "无法定位完整日志",
                f"文件管理器未接受定位请求：{path}",
                "warning",
            )

    def _reset_log_tailer(self) -> None:
        if self.log_service is not None:
            self._set_log_text("")
            self.log_service.select(paths.log_file(self._selected_id) if self._selected_id else None)
            return
        if not self._selected_id:
            self._tailer = None
            self._set_log_text("")
            return
        self._tailer = LogTailer(paths.log_file(self._selected_id))
        self._tailer.seek_tail(512 * 1024)
        self._set_log_text("")
        self._tail_log()

    def _tail_log(self) -> None:
        if self.log_service is not None:
            self.log_service.read()
            return
        if self._tailer is not None:
            try:
                self._apply_log_batch(self._tailer.read_batch())
            except OSError as exc:
                self.dialogRequested.emit("日志读取失败", str(exc), "error")

    @Slot(object)
    def _receive_log(self, delivery: LogDelivery) -> None:
        if delivery.error:
            self.dialogRequested.emit("日志读取失败", delivery.error, "error")
            return
        self._apply_log_batch(delivery.batch)

    def _apply_log_batch(self, batch: LogBatch) -> None:
        previous = self._log_preview
        if batch.reset:
            self._set_log_text("")
            previous = ""
        if not batch.completed and batch.preview == previous:
            return
        remove = len(previous)
        base = self._log_text[:-remove] if remove else self._log_text
        addition = batch.completed + batch.preview
        merged = base + addition
        self._log_text = merged[-1_500_000:]
        self._log_preview = batch.preview
        self.logChanged.emit()

    @Slot()
    def clearVisibleLog(self) -> None:
        if self.log_service is not None:
            self.log_service.clear()
        elif self._tailer is not None:
            self._tailer.seek_end()
        self._set_log_text("[LATTICE] DISPLAY BUFFER CLEARED · DISK LOG PRESERVED\n")
        self.toastRequested.emit("仅清除当前显示；磁盘日志未删除", "success")


    @Slot()
    def queryHardware(self) -> None:
        if self._hardware_paused:
            return
        self.hardware_service.read()

    @Slot(object)
    def _hardware_ready(self, sample: HardwareSample) -> None:
        if self._hardware_paused or self._closed:
            return
        telemetry = dict(self._telemetry)
        cpu = sample.cpu
        memory = sample.memory
        available = 0
        telemetry["cpuValue"] = cpu if cpu is not None else -1.0
        telemetry["cpuText"] = f"{cpu:.0f}%" if cpu is not None else ("读取失败" if sample.cpu_error else "采样中")
        telemetry["cpuDetail"] = sample.cpu_error
        if cpu is not None:
            available += 1
        if memory is None:
            telemetry.update(memoryValue=-1.0, memoryText="不可用", memoryDetail=sample.memory_error)
        else:
            telemetry.update(memoryValue=memory[0], memoryText=f"{memory[0]:.0f}%", memoryDetail=memory[1])
            available += 1
        self._base_hardware_metrics = available
        self._telemetry = telemetry
        self.telemetryChanged.emit()

        if shutil.which("nvidia-smi") is None:
            self._set_gpu_unavailable("未安装 nvidia-smi；此查询仅支持 NVIDIA")
            return
        if self.gpu_process.state() == QProcess.ProcessState.NotRunning:
            self._gpu_failure = ""
            self.gpu_timeout.start(2500)
            self.gpu_process.start(
                "nvidia-smi",
                [
                    "--query-gpu=utilization.gpu,memory.used,memory.total,name",
                    "--format=csv,noheader,nounits",
                ],
            )

    def _gpu_timed_out(self) -> None:
        self._gpu_failure = "nvidia-smi 查询超过 2.5 秒；可在硬件菜单重新查询"
        self.gpu_process.kill()
        self._set_gpu_unavailable(self._gpu_failure)

    def _gpu_finished(self, exit_code: int, _status: QProcess.ExitStatus) -> None:
        self.gpu_timeout.stop()
        if self._hardware_paused:
            return
        raw = bytes(self.gpu_process.readAllStandardOutput()).decode(errors="replace").splitlines()
        if self._gpu_failure:
            self._set_gpu_unavailable(self._gpu_failure)
            return
        if exit_code != 0 or not raw:
            error = bytes(self.gpu_process.readAllStandardError()).decode(errors="replace").strip()
            self._set_gpu_unavailable(f"nvidia-smi 退出码 {exit_code}；输出：{raw!r}；错误：{error}")
            return
        try:
            parts = [value.strip() for value in raw[0].split(",")]
            utilization, used, total = (float(value) for value in parts[:3])
            name = ", ".join(parts[3:]) or "NVIDIA GPU"
        except (ValueError, IndexError) as exc:
            self._set_gpu_unavailable(f"nvidia-smi 返回了无法解析的数据 {raw[0]!r}：{exc}")
            return
        self._telemetry.update(
            gpuValue=utilization,
            gpuText=f"{utilization:.0f}%",
            gpuDetail=f"VRAM {used / 1024:.1f} / {total / 1024:.1f} GiB",
            gpuName=name,
        )
        self._finish_hardware_sample(True)

    def _gpu_error(self, _error: QProcess.ProcessError) -> None:
        if not self._hardware_paused:
            self._set_gpu_unavailable(self._gpu_failure or f"nvidia-smi 查询失败：{self.gpu_process.errorString()}")

    def _set_gpu_unavailable(self, detail: str) -> None:
        self._telemetry.update(gpuValue=-1.0, gpuText="不可用", gpuDetail=detail, gpuName="")
        self._finish_hardware_sample(False)

    def _finish_hardware_sample(self, gpu_available: bool) -> None:
        count = self._base_hardware_metrics + int(gpu_available)
        if count >= 3:
            state, label = "LIVE", "实时"
        elif count:
            state, label = "PARTIAL", "部分可用"
        else:
            state, label = "OFFLINE", "未连接"
        self._telemetry.update(state=state, stateLabel=label, updated=f"{datetime.now():%H:%M:%S}")
        self.telemetryChanged.emit()

    @Slot(bool)
    def setHardwarePaused(self, paused: bool) -> None:
        if paused == self._hardware_paused:
            return
        self._hardware_paused = paused
        if paused:
            self.hardware_timer.stop()
            self._telemetry.update(state="PAUSED", stateLabel="已暂停")
            self.telemetryChanged.emit()
        else:
            self.hardware_timer.start(5000)
            self._telemetry.update(state="SYNC", stateLabel="连接中")
            self.telemetryChanged.emit()
            self.queryHardware()
        self.hardwarePausedChanged.emit()

    def set_tray_icon(self, tray_icon: QSystemTrayIcon | None) -> None:
        self._tray_icon = tray_icon
        self.trayAvailableChanged.emit()

    def allow_exit(self) -> None:
        self._allow_close = True

    @Slot(result=bool)
    def acceptWindowClose(self) -> bool:
        if self._allow_close or not self.trayAvailable:
            self.shutdown()
            return True
        settings = application_settings()
        if not settings.value("qml_tray_notice_shown", False, type=bool) and self._tray_icon is not None:
            self._tray_icon.showMessage(
                "Lattice 仍在运行",
                "控制中枢已隐藏；活动工具继续在后台运行。",
                QSystemTrayIcon.MessageIcon.Information,
                4000,
            )
            settings.setValue("qml_tray_notice_shown", True)
        return False

    @Slot()
    def requestExit(self) -> None:
        self.exitRequested.emit()

    @Slot()
    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.status_timer.stop()
        self.log_timer.stop()
        self.hardware_timer.stop()
        self.hardware_warmup_timer.stop()
        self.gpu_timeout.stop()
        self.hardware_service.shutdown()
        if self.process_service is not None:
            self.process_service.shutdown()
        if self.log_service is not None:
            self.log_service.shutdown()
        if self.gpu_process.state() != QProcess.ProcessState.NotRunning:
            self.gpu_process.kill()
            self.gpu_process.waitForFinished(1000)
