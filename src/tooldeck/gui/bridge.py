from __future__ import annotations

import ipaddress
import math
import secrets
import shutil
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Property, QProcess, QRunnable, QSettings, QThreadPool, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import QSystemTrayIcon

from tooldeck import paths
from tooldeck.application import ToolDeckApplication
from tooldeck.catalog import CatalogError, CatalogSnapshot
from tooldeck.config import ConfigError, ToolConfig, default_shell
from tooldeck.drafts import (
    base_tool_id,
    parse_env_text,
    tool_from_draft,
    unique_tool_id,
)
from tooldeck.groups import display_group_name, normalize_group_key
from tooldeck.layout import LayoutState
from tooldeck.platform_ops import reveal_path
from tooldeck.ports import CatalogPort, RuntimePort
from tooldeck.procs import ProcessError, ToolStatus
from tooldeck.tailer import LogTailer
from tooldeck.telemetry import SystemSampler, parse_nvidia_smi
from tooldeck.themes import ThemeError, ThemeRegistry
from tooldeck.util import fmt_duration, short_home, strip_ansi

from .log_model import LogLineModel
from .tool_model import STATE_COLORS, STATE_LABELS, ToolListModel


class _SetupTaskSignals(QObject):
    started = Signal(str, str)
    progress = Signal(str, int, int, str)
    finished = Signal(str, object)


class _SetupTask(QRunnable):
    def __init__(
        self,
        token: str,
        application: ToolDeckApplication,
        setup: object,
        cancel_event: threading.Event,
    ) -> None:
        super().__init__()
        self.token = token
        self.application = application
        self.setup = setup
        self.cancel_event = cancel_event
        self.signals = _SetupTaskSignals()

    def run(self) -> None:
        try:
            result = self.application.prepare_environment(
                self.setup,
                confirmed=True,
                cancel_event=self.cancel_event,
                started=lambda log_path: self.signals.started.emit(self.token, str(log_path)),
                progress=lambda current, total, command: self.signals.progress.emit(
                    self.token, current, total, command
                ),
            )
        except Exception as exc:
            result = exc
        self.signals.finished.emit(self.token, result)


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
    themeChanged = Signal()
    themesChanged = Signal()
    layoutChanged = Signal()
    startupChanged = Signal()
    startupImageChanged = Signal()
    toastRequested = Signal(str, str)
    dialogRequested = Signal(str, str, str)
    editorRequested = Signal(str, "QVariantMap")
    importOverwriteRequested = Signal(str, str, str)
    setupProgressChanged = Signal("QVariantMap")
    setupFinished = Signal("QVariantMap")
    exitRequested = Signal()

    FONT_SCALE_MIN = 0.80
    FONT_SCALE_MAX = 1.50
    FONT_SCALE_DEFAULT = 1.00
    FONT_SCALE_KEY = "ui/font_scale"
    THEME_KEY = "ui/theme"
    LOG_TEXT_LIMIT = 256 * 1024

    def __init__(
        self,
        manager: RuntimePort | None = None,
        *,
        catalog: CatalogPort | None = None,
        application: ToolDeckApplication | None = None,
        theme_registry: ThemeRegistry | None = None,
        auto_start_timers: bool = True,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        if application is not None and (manager is not None or catalog is not None):
            raise ValueError("application 不能与 manager/catalog 同时传入")
        self.application = application or ToolDeckApplication(catalog=catalog, runtime=manager)
        # Kept as compatibility aliases for callers that injected these ports.
        self.manager = self.application.runtime
        self.catalog = self.application.catalog
        self.model = ToolListModel(self)
        self.model.countsChanged.connect(self.summaryChanged)
        self.log_model = LogLineModel(self)
        self._tools: dict[str, ToolConfig] = {}
        self._statuses: dict[str, ToolStatus] = {}
        self._selected_id = ""
        self._search_text = ""
        self._filter_mode = "all"
        self._tailer: LogTailer | None = None
        self._log_text = ""
        self._pending_restart: set[str] = set()
        self._setup_tasks: dict[str, tuple[_SetupTask, threading.Event, Path]] = {}
        self._system_sampler = SystemSampler()
        self._base_hardware_metrics = 0
        self._hardware_paused = False
        self._telemetry = self._empty_telemetry()
        self._tray_icon: QSystemTrayIcon | None = None
        self._allow_close = False
        self._settings = QSettings("ToolDeck", "ToolDeck")
        self._font_scale = self._normalize_font_scale(
            self._settings.value(self.FONT_SCALE_KEY, self.FONT_SCALE_DEFAULT)
        )
        self._theme_registry = theme_registry or ThemeRegistry()
        preferred_theme = str(
            self._settings.value(self.THEME_KEY, self._theme_registry.catalog.default_id)
        )
        self._theme_id = (
            preferred_theme
            if preferred_theme in self._theme_registry.catalog.themes
            else self._theme_registry.catalog.default_id
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
            "sampleSequence": 0,
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
        group_key = tool.group or ""
        group_index = self._layout.group_order.index(group_key) if group_key in self._layout.group_order else 0
        return {
            "id": tool.id,
            "name": tool.name,
            "sequence": self.model.sequence_text(tool.id),
            "group": tool.group,
            "groupLabel": display_group_name(tool.group),
            "groupCode": f"GRP-{group_index + 1:02d}",
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
            "pid": status.pid or 0,
            "pidText": str(status.pid) if status.pid else "----",
            "uptime": fmt_duration(status.uptime),
            "exitCode": status.exit_code if status.exit_code is not None else "--",
            "message": status.message or "",
            "readyUrl": status.ready_url or "",
            "logPath": str(self.application.log_path(tool.id)),
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

    @Property(QObject, constant=True)
    def logModel(self) -> LogLineModel:
        return self.log_model

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

    @Property(str, notify=themeChanged)
    def themeId(self) -> str:
        return self._theme_id

    @Property(str, notify=themeChanged)
    def themeAppearance(self) -> str:
        return self._theme_registry.get(self._theme_id).appearance

    @Property(str, notify=themeChanged)
    def themeShell(self) -> str:
        return self._theme_registry.get(self._theme_id).shell

    @Property(int, notify=themeChanged)
    def themeIndex(self) -> int:
        return list(self._theme_registry.catalog.themes).index(self._theme_id)

    @Property("QVariantList", notify=themesChanged)
    def availableThemes(self) -> list[dict[str, Any]]:
        return self._theme_registry.summaries()

    @Property("QVariantMap", notify=themeChanged)
    def themeTokens(self) -> dict[str, Any]:
        return self._theme_registry.get(self._theme_id).qml_tokens()

    @Property(bool, notify=filtersChanged)
    def reorderingAllowed(self) -> bool:
        return not bool(self._search_text.strip()) and self._filter_mode == "all"

    @Property("QStringList", notify=layoutChanged)
    def groupOrder(self) -> list[str]:
        return [display_group_name(group) for group in self._layout.group_order]

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
    def _startup_image_failed(self, _message: str, task: object) -> None:
        self._startup_image_tasks.discard(task)

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

    @Slot(str, result=bool)
    def setTheme(self, theme_id: str) -> bool:
        selected = str(theme_id).strip()
        try:
            self._theme_registry.get(selected)
        except ThemeError as exc:
            self.dialogRequested.emit("无法切换主题", str(exc), "error")
            return False
        if selected == self._theme_id:
            return True
        self._theme_id = selected
        self._settings.setValue(self.THEME_KEY, selected)
        self._settings.sync()
        self.themeChanged.emit()
        return True

    @Slot(result=bool)
    def reloadThemes(self) -> bool:
        try:
            catalog = self._theme_registry.reload()
        except (OSError, ThemeError) as exc:
            self.dialogRequested.emit("无法重载主题", str(exc), "error")
            return False
        if self._theme_id not in catalog.themes:
            self._theme_id = catalog.default_id
            self._settings.setValue(self.THEME_KEY, self._theme_id)
            self._settings.sync()
        self.themesChanged.emit()
        self.themeChanged.emit()
        if catalog.issues:
            messages = [f"{issue.path.name}: {issue.message}" for issue in catalog.issues]
            self.dialogRequested.emit("部分主题未载入", "\n".join(messages), "warning")
        else:
            self.toastRequested.emit("主题包已重载", "success")
        return True

    @Slot()
    def openThemeDirectory(self) -> None:
        directory = self._theme_registry.ensure_custom_dir()
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory)))

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
        if text == self._log_text:
            return
        self._log_text = text[-self.LOG_TEXT_LIMIT :]
        self.logChanged.emit()

    def _select_first_visible(self) -> None:
        candidate = self.model.visible_ids[0] if self.model.visible_ids else ""
        self.selectTool(candidate)

    def _sync_model(self, previous_selected_id: str | None = None, *, status_only: bool = False) -> None:
        previous = self._selected_id if previous_selected_id is None else previous_selected_id
        changed_ids = self.model.set_tools(self._tools, self._statuses)
        self.model.set_filter(self._search_text, self._filter_mode)
        if self._selected_id not in self._tools:
            self._selected_id = ""
        if not self._selected_id and self.model.visible_ids:
            self._selected_id = self.model.visible_ids[0]
        if self._selected_id != previous:
            self.selectionIdentityChanged.emit()
        if not status_only or self._selected_id != previous or self._selected_id in changed_ids:
            self.selectedChanged.emit()
        if not status_only:
            self.summaryChanged.emit()

    def _collect_statuses(self) -> tuple[dict[str, ToolStatus], list[str]]:
        snapshot = self.application.inspect_statuses(
            self._tools,
            previous_statuses=self._statuses,
        )
        failures = [f"{issue.tool_name}: {issue.message}" for issue in snapshot.issues]
        return snapshot.statuses, failures

    def _apply_catalog_snapshot(self, snapshot: CatalogSnapshot) -> None:
        """Copy application state into the Qt-facing model in one place."""

        self._tools = dict(snapshot.tools)
        self._layout = snapshot.layout.copy()
        self.model.set_layout(self._layout)

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
        normalized = mode if mode in {"all", "running", "stopped", "exited"} else "all"
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
        return str(normalize_group_key(value))

    @Slot(str, result=bool)
    def toggleGroup(self, group: str) -> bool:
        try:
            changed = self.application.toggle_group(group)
        except (CatalogError, OSError) as exc:
            self.dialogRequested.emit("无法更新分组", str(exc), "error")
            return False
        if changed:
            self._apply_catalog_snapshot(self.application.catalog_snapshot())
            self.layoutChanged.emit()
        return changed

    @Slot(str, bool, result=bool)
    def setGroupCollapsed(self, group: str, collapsed: bool) -> bool:
        try:
            changed = self.application.set_group_collapsed(group, collapsed)
        except (CatalogError, OSError) as exc:
            self.dialogRequested.emit("无法更新分组", str(exc), "error")
            return False
        if changed:
            self._apply_catalog_snapshot(self.application.catalog_snapshot())
            self.layoutChanged.emit()
        return changed

    @Slot(str, str, int, result=bool)
    def moveTool(self, tool_id: str, target_group: str, target_index: int) -> bool:
        """Move a tool within or across groups and persist its new group."""
        if not self.reorderingAllowed:
            return False
        try:
            changed = self.application.move_tool(tool_id, target_group, target_index)
        except (CatalogError, ConfigError, OSError) as exc:
            self.dialogRequested.emit("无法移动工具", str(exc), "error")
            return False
        if not changed:
            return False
        self._apply_catalog_snapshot(self.application.catalog_snapshot())
        self._sync_model(self._selected_id)
        self.layoutChanged.emit()
        return True

    @Slot(str, result=int)
    def groupToolCount(self, group: str) -> int:
        return len(self._layout.tool_order.get(self._group_key(group), []))

    @Slot(str, int, result=bool)
    def moveGroup(self, group: str, target_index: int) -> bool:
        if not self.reorderingAllowed:
            return False
        try:
            changed = self.application.move_group(group, target_index)
        except (CatalogError, OSError) as exc:
            self.dialogRequested.emit("无法移动分组", str(exc), "error")
            return False
        if not changed:
            return False
        self._apply_catalog_snapshot(self.application.catalog_snapshot())
        self._sync_model(self._selected_id)
        self.layoutChanged.emit()
        return changed

    @Slot(bool)
    def reloadTools(self, show_issues: bool = True) -> None:
        current = self._selected_id
        try:
            snapshot = self.application.refresh(previous_statuses=self._statuses)
        except (CatalogError, OSError) as exc:
            self.dialogRequested.emit("配置索引不可用", str(exc), "error")
            return
        self._apply_catalog_snapshot(snapshot.catalog)
        issues = snapshot.catalog.issues
        self._statuses = snapshot.runtime.statuses
        status_failures = [f"{issue.tool_name}: {issue.message}" for issue in snapshot.runtime.issues]
        self._selected_id = current if current in self._tools else ""
        self._sync_model(current)
        if self._selected_id:
            self._reset_log_tailer()
        if show_issues:
            if issues or status_failures:
                config_messages = [f"{issue.path.name}: {issue.message}" for issue in issues]
                message = "\n".join([*config_messages, *status_failures])
                self.dialogRequested.emit("配置或状态读取异常", message, "warning")
            else:
                self.toastRequested.emit("配置索引已重载", "success")

    @Slot()
    def refreshStatus(self) -> None:
        try:
            runtime = self.application.inspect_statuses(
                self._tools,
                previous_statuses=self._statuses,
                tick=True,
            )
        except (ProcessError, OSError) as exc:
            self.dialogRequested.emit("状态同步失败", str(exc), "error")
            runtime = self.application.inspect_statuses(
                self._tools,
                previous_statuses=self._statuses,
            )
        updated = runtime.statuses
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
                updated[tool_id] = self.application.start(tool.id)
                self.toastRequested.emit(f"正在重新启动 {tool.name}", "warning")
                if tool_id == self._selected_id:
                    self._reset_log_tailer()
            except (ConfigError, ProcessError) as exc:
                self.dialogRequested.emit("无法重启", str(exc), "error")
        for tool_id, status in updated.items():
            previous = self._statuses.get(tool_id)
            tool = self._tools.get(tool_id)
            if previous is None or tool is None or previous.state == status.state:
                continue
            if status.state == "running" and previous.state in {"starting", "unready"}:
                self.toastRequested.emit(f"{tool.name} 已就绪 · PID {status.pid}", "success")
            elif status.state == "unready" and previous.state == "starting":
                tail = self.application.log_tail(tool_id)
                message = status.message or "启动探测超时，进程仍在运行"
                if tail:
                    message += f"\n\n最近日志：\n{tail}"
                message += f"\n\n完整日志：{self.application.log_path(tool_id)}"
                self.dialogRequested.emit(f"{tool.name} 启动超时", message, "warning")
            elif status.state == "exited" and previous.state in {"starting", "unready"}:
                message = status.message or f"进程在启动期间退出，退出码 {status.exit_code}"
                message += f"\n\n完整日志：{self.application.log_path(tool_id)}"
                self.dialogRequested.emit(f"{tool.name} 未能启动", message, "error")
        self._statuses = updated
        self._sync_model(status_only=True)

    def _selected_tool(self) -> ToolConfig | None:
        return self._tools.get(self._selected_id)

    def _start(self, tool: ToolConfig, verb: str) -> None:
        try:
            status = self.application.start(tool.id)
        except (ConfigError, ProcessError) as exc:
            self.dialogRequested.emit(f"无法{verb}", str(exc), "error")
            return
        self._statuses[tool.id] = status
        if status.state == "running":
            self.toastRequested.emit(f"{tool.name} 已就绪 · PID {status.pid}", "success")
        else:
            self.toastRequested.emit(f"正在{verb} {tool.name} · PID {status.pid}", "warning")
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
        try:
            self.application.stop_begin(tool.id)
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
        status = self._statuses.get(tool.id)
        if status is None:
            try:
                status = self.application.inspect_statuses({tool.id: tool}).statuses[tool.id]
            except (ProcessError, OSError) as exc:
                self.dialogRequested.emit("无法重启", str(exc), "error")
                return
        if not status.active:
            self._start(tool, "重启")
            return
        try:
            self.application.stop_begin(tool.id)
        except ProcessError as exc:
            self.dialogRequested.emit("无法重启", str(exc), "error")
            return
        self._pending_restart.add(tool.id)
        self.toastRequested.emit(f"{tool.name} 正在执行重启序列", "warning")
        self.refreshStatus()

    @Slot()
    def stopAll(self) -> None:
        failures = self.application.stop_all_begin()
        self._pending_restart.clear()
        if failures:
            self.dialogRequested.emit("部分工具未能停止", "\n".join(failures), "warning")
        else:
            self.toastRequested.emit("全部活动单元已收到停止指令", "warning")
        self.refreshStatus()

    @Slot()
    def startAutostart(self) -> None:
        issues = self.application.start_autostart()
        self.refreshStatus()
        if issues:
            failures = [f"{issue.tool_name}: {issue.message}" for issue in issues]
            self.dialogRequested.emit("部分自动启动失败", "\n".join(failures), "warning")

    @staticmethod
    def _base_id(text: str) -> str:
        return base_tool_id(text)

    def _unique_id(self, text: str) -> str:
        return unique_tool_id(text, self._tools)

    @Slot(str, result=str)
    def suggestToolId(self, text: str) -> str:
        return self._unique_id(text or "tool")

    @Slot(result="QVariantMap")
    def newToolDraft(self) -> dict[str, Any]:
        return self.application.new_draft()

    @Slot(result="QVariantMap")
    def selectedToolDraft(self) -> dict[str, Any]:
        tool = self._selected_tool()
        return self.application.tool_draft(tool.id) if tool is not None else {}

    @staticmethod
    def _parse_env(text: str) -> dict[str, str]:
        return parse_env_text(text)

    @Slot("QVariantMap", result=bool)
    def saveToolDraft(self, draft: dict[str, Any]) -> bool:
        original_id = str(draft.get("originalId", "")).strip()
        tool_id = str(draft.get("id", "")).strip()
        if original_id and tool_id != original_id:
            self.dialogRequested.emit("无法保存", "已登记工具的 ID 不可更改", "error")
            return False
        if bool(draft.get("setupRequired", False)) and not bool(draft.get("rawMode", False)):
            self.dialogRequested.emit("需要准备环境", "请先确认并完成环境准备，再写入工具配置", "warning")
            return False
        try:
            tool = tool_from_draft(draft)
            snapshot = self.application.save_draft(draft)
        except (CatalogError, ConfigError, OSError, TypeError, ValueError) as exc:
            self.dialogRequested.emit("无法保存工具", str(exc), "error")
            return False
        self._apply_catalog_snapshot(snapshot)
        self._statuses = self.application.inspect_statuses(
            self._tools,
            previous_statuses=self._statuses,
        ).statuses
        self._sync_model(self._selected_id)
        self.layoutChanged.emit()
        self.selectTool(tool.id)
        self._reset_log_tailer()
        self.toastRequested.emit(f"{tool.name} 已写入配置索引", "success")
        return True

    @Slot("QVariantMap", result=bool)
    def saveAndStartToolDraft(self, draft: dict[str, Any]) -> bool:
        tool_id = str(draft.get("id", "")).strip()
        if not self.saveToolDraft(draft):
            return False
        tool = self._tools.get(tool_id)
        if tool is not None:
            self._start(tool, "启动")
        return True

    @Slot()
    def deleteSelected(self) -> None:
        tool = self._selected_tool()
        if tool is None:
            return
        status = self._statuses.get(tool.id, ToolStatus(tool.id, "stopped"))
        if status.active:
            self.dialogRequested.emit("无法删除", "工具仍在运行，请先停止该单元", "warning")
            return
        try:
            self.application.delete_tool(tool.id)
        except (CatalogError, ConfigError, OSError) as exc:
            self.dialogRequested.emit("无法删除工具", str(exc), "error")
            return
        name = tool.name
        self._apply_catalog_snapshot(self.application.catalog_snapshot())
        self._statuses.pop(tool.id, None)
        self._sync_model(self._selected_id)
        self.layoutChanged.emit()
        self._reset_log_tailer()
        self.toastRequested.emit(f"{name} 已从配置索引移除；磁盘日志保留", "warning")

    @staticmethod
    def command_for_launch_path(
        path: Path,
        shell: str | None = None,
        *,
        platform_name: str | None = None,
        python_executable: str | None = None,
    ) -> tuple[str, str]:
        return ToolDeckApplication.command_for_launch_path(
            path,
            shell,
            platform_name=platform_name,
            python_executable=python_executable,
        )

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
        try:
            return self.application.launch_draft(source, shell or default_shell())
        except ConfigError as exc:
            self.dialogRequested.emit("无法识别启动入口", str(exc), "error")
            return {}

    @Slot(str, result=str)
    def prepareEnvironmentForPath(self, value: str) -> str:
        source = self._path_from_url(value)
        try:
            analysis = self.application.analyze_launch(source)
        except (ConfigError, OSError) as exc:
            self.dialogRequested.emit("无法准备环境", str(exc), "error")
            return ""
        if analysis.blocking or analysis.plan is None:
            messages = [check.message for check in analysis.checks if check.level == "blocking"]
            self.dialogRequested.emit("无法准备环境", "\n".join(messages) or "启动入口检测失败", "error")
            return ""
        setup = analysis.plan.setup
        if setup is None:
            patch = self.application.launch_draft(source)
            self.setupFinished.emit(
                {
                    "token": "",
                    "success": True,
                    "cancelled": False,
                    "message": "现有环境已经可用",
                    "logPath": "",
                    "source": str(source),
                    "patch": patch,
                }
            )
            return ""
        token = secrets.token_hex(12)
        cancel_event = threading.Event()
        task = _SetupTask(token, self.application, setup, cancel_event)
        task.signals.started.connect(self._setup_started)
        task.signals.progress.connect(self._setup_progress)
        task.signals.finished.connect(self._setup_finished)
        self._setup_tasks[token] = (task, cancel_event, source)
        QThreadPool.globalInstance().start(task)
        return token

    @Slot(str, result=bool)
    def cancelEnvironmentPreparation(self, token: str) -> bool:
        entry = self._setup_tasks.get(str(token))
        if entry is None:
            return False
        entry[1].set()
        return True

    @Slot(str, int, int, str)
    def _setup_progress(self, token: str, current: int, total: int, command: str) -> None:
        self.setupProgressChanged.emit(
            {"token": token, "current": current, "total": total, "command": command}
        )

    @Slot(str, str)
    def _setup_started(self, token: str, log_path: str) -> None:
        self.setupProgressChanged.emit(
            {"token": token, "current": 0, "total": 0, "command": "", "logPath": log_path}
        )

    @Slot(str, object)
    def _setup_finished(self, token: str, result: object) -> None:
        entry = self._setup_tasks.pop(token, None)
        if entry is None:
            return
        source = entry[2]
        success = bool(getattr(result, "success", False))
        patch: dict[str, Any] = {}
        if success:
            try:
                patch = self.application.launch_draft(source)
                launch = patch.get("launch")
                if isinstance(launch, dict):
                    launch["managed_environment"] = True
            except (ConfigError, OSError) as exc:
                success = False
                result = exc
        message = str(getattr(result, "message", result))
        log_path = getattr(result, "log_path", "")
        payload = {
            "token": token,
            "success": success,
            "cancelled": bool(getattr(result, "cancelled", False)),
            "message": message,
            "logPath": str(log_path),
            "source": str(source),
            "patch": patch,
        }
        self.setupFinished.emit(payload)
        if success:
            self.toastRequested.emit("项目环境准备完成", "success")
        elif payload["cancelled"]:
            self.toastRequested.emit("环境准备已取消；未写入工具配置", "warning")
        else:
            detail = message + (f"\n\n完整日志：{log_path}" if log_path else "")
            self.dialogRequested.emit("环境准备失败", detail, "error")

    @Slot(str)
    def prepareImport(self, value: str) -> None:
        source = self._path_from_url(value)
        if not source.is_file():
            self.dialogRequested.emit("无法导入", f"文件不存在：{source}", "error")
            return
        try:
            plan = self.application.plan_import(source)
        except ConfigError as exc:
            self.dialogRequested.emit("无法读取配置", str(exc), "error")
            return
        if plan.kind == "config":
            candidate = plan.candidate
            if candidate is None:
                return
            if plan.overwrite_required:
                self.importOverwriteRequested.emit(str(source), candidate.id, candidate.name)
            else:
                self._import_toml(source, False)
            return
        if plan.draft is not None:
            self.editorRequested.emit("import", plan.draft)

    def _import_toml(self, source: Path, overwrite: bool) -> None:
        try:
            tool = self.application.import_tool(source, overwrite=overwrite)
        except (CatalogError, ConfigError, OSError) as exc:
            self.dialogRequested.emit("无法导入配置", str(exc), "error")
            return
        self._apply_catalog_snapshot(self.application.catalog_snapshot())
        self._statuses = self.application.inspect_statuses(
            self._tools,
            previous_statuses=self._statuses,
        ).statuses
        self._sync_model(self._selected_id)
        self.layoutChanged.emit()
        self.selectTool(tool.id)
        self._reset_log_tailer()
        self.toastRequested.emit(f"{tool.name} 已导入配置索引", "success")

    @Slot(str)
    def confirmImportOverwrite(self, value: str) -> None:
        self._import_toml(self._path_from_url(value), True)

    @Slot()
    def openConfigDirectory(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.application.tools_directory())))

    @staticmethod
    def _start_detached(program: str, arguments: list[str]) -> bool:
        result = QProcess.startDetached(program, arguments)
        return bool(result[0] if isinstance(result, tuple) else result)

    @classmethod
    def _reveal_path(cls, path: Path) -> bool:
        return reveal_path(
            path,
            start_detached=cls._start_detached,
            open_directory=lambda directory: QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory))),
            platform_name=sys.platform,
            which=shutil.which,
        )

    @Slot()
    def openSelectedLog(self) -> None:
        tool = self._selected_tool()
        if tool is None:
            return
        path = self.application.log_path(tool.id)
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

    @Slot()
    def copyVisibleLog(self) -> None:
        if not self._log_text.strip():
            self.toastRequested.emit("当前没有可复制的运行记录", "warning")
            return
        QGuiApplication.clipboard().setText(self._log_text)
        self.toastRequested.emit("已复制当前显示的运行记录", "success")

    @Slot(str)
    def openSetupLog(self, value: str) -> None:
        try:
            path = Path(value).expanduser().resolve()
            setup_root = paths.setup_logs_dir().resolve()
        except OSError as exc:
            self.dialogRequested.emit("无法定位准备日志", str(exc), "warning")
            return
        if not path.is_relative_to(setup_root) or not path.is_file():
            self.dialogRequested.emit("无法定位准备日志", f"准备日志不存在：{path}", "warning")
            return
        if self._reveal_path(path):
            self.toastRequested.emit(f"已在文件管理器中定位 {path.name}", "success")
        else:
            self.dialogRequested.emit("无法定位准备日志", f"文件管理器未接受定位请求：{path}", "warning")

    @Slot()
    def openSelectedService(self) -> None:
        tool = self._selected_tool()
        if tool is None:
            return
        status = self._statuses.get(tool.id)
        value = status.ready_url if status is not None else None
        url = QUrl(value or "")
        host = url.host().casefold()
        try:
            is_loopback = host == "localhost" or ipaddress.ip_address(host).is_loopback
        except ValueError:
            is_loopback = False
        if url.scheme() not in {"http", "https"} or not is_loopback:
            self.dialogRequested.emit("无法打开服务", "当前工具没有经过验证的本地服务地址", "warning")
            return
        QDesktopServices.openUrl(url)

    def _reset_log_tailer(self) -> None:
        if not self._selected_id:
            self._tailer = None
            self.log_model.clear()
            self._set_log_text("")
            return
        self._tailer = LogTailer(self.application.log_path(self._selected_id))
        self._tailer.seek_tail()
        self.log_model.clear()
        self._set_log_text("")
        self._tail_log()

    def _tail_log(self) -> None:
        if self._tailer is None:
            return
        chunk = self._tailer.read()
        if chunk:
            clean = strip_ansi(chunk)
            self.log_model.append_text(clean)
            self._set_log_text(self._log_text + clean)

    @Slot()
    def clearVisibleLog(self) -> None:
        if self._tailer is not None:
            try:
                self._tailer.offset = self._tailer.path.stat().st_size
            except FileNotFoundError:
                self._tailer.reset()
        message = "DISPLAY BUFFER CLEARED / PERSISTENT RECORD RETAINED"
        self.log_model.clear(message)
        self._set_log_text(f"{message}\n")
        self.toastRequested.emit("仅清除当前显示；磁盘日志未删除", "success")

    @Slot()
    def queryHardware(self) -> None:
        if self._hardware_paused:
            return
        telemetry = dict(self._telemetry)
        sample = self._system_sampler.sample()
        telemetry["cpuValue"] = sample.cpu_percent if sample.cpu_percent is not None else -1.0
        telemetry["cpuText"] = f"{sample.cpu_percent:.0f}%" if sample.cpu_percent is not None else "采样中"
        telemetry["cpuDetail"] = ""
        if sample.memory_percent is None:
            telemetry.update(memoryValue=-1.0, memoryText="不可用", memoryDetail=sample.memory_detail)
        else:
            telemetry.update(
                memoryValue=sample.memory_percent,
                memoryText=f"{sample.memory_percent:.0f}%",
                memoryDetail=sample.memory_detail,
            )
        self._base_hardware_metrics = sample.available_count
        self._telemetry = telemetry

        if shutil.which("nvidia-smi") is None:
            self._set_gpu_unavailable("无 NVIDIA")
            return
        if self.gpu_process.state() == QProcess.ProcessState.NotRunning:
            self.gpu_process.start(
                "nvidia-smi",
                [
                    "--query-gpu=utilization.gpu,memory.used,memory.total,name",
                    "--format=csv,noheader,nounits",
                ],
            )

    def _gpu_finished(self, exit_code: int, _status: QProcess.ExitStatus) -> None:
        if self._hardware_paused:
            return
        raw = bytes(self.gpu_process.readAllStandardOutput()).decode(errors="replace")
        if exit_code != 0 or not raw.strip():
            self._set_gpu_unavailable("读取失败")
            return
        try:
            sample = parse_nvidia_smi(raw)
        except ValueError:
            self._set_gpu_unavailable("读取失败")
            return
        self._telemetry.update(
            gpuValue=sample.utilization,
            gpuText=f"{sample.utilization:.0f}%",
            gpuDetail=f"VRAM {sample.used_mib / 1024:.1f} / {sample.total_mib / 1024:.1f} GiB",
            gpuName=sample.name,
        )
        self._finish_hardware_sample(True)

    def _gpu_error(self, _error: QProcess.ProcessError) -> None:
        if not self._hardware_paused:
            self._set_gpu_unavailable("读取失败")

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
        self._telemetry.update(
            state=state,
            stateLabel=label,
            updated=f"{datetime.now():%H:%M:%S}",
            sampleSequence=int(self._telemetry.get("sampleSequence", 0)) + 1,
        )
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
        settings = QSettings("ToolDeck", "ToolDeck")
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
        self.status_timer.stop()
        self.log_timer.stop()
        self.hardware_timer.stop()
        self.hardware_warmup_timer.stop()
        for _task, cancel_event, _source in self._setup_tasks.values():
            cancel_event.set()
        if self.gpu_process.state() != QProcess.ProcessState.NotRunning:
            self.gpu_process.kill()
            self.gpu_process.waitForFinished(1000)
