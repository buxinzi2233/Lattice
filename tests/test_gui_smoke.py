from __future__ import annotations

import tempfile

import subprocess
import sys
import time
from pathlib import Path

import shiboken6
from PySide6.QtCore import QMetaObject, QObject, QPoint, Qt, QUrl, qInstallMessageHandler
from PySide6.QtGui import QIcon
from PySide6.QtQml import QQmlEngine, QQmlExpression
from PySide6.QtTest import QSignalSpy, QTest

from tooldeck import paths
from tooldeck.config import default_shell, ToolConfig, load_file, save
from tooldeck.gui.app import create_engine, icon_path
from tooldeck.gui.bridge import AppBridge
from tooldeck.procs import ToolStatus
from tooldeck.telemetry import SystemSample


class FixedManager:
    def __init__(self, statuses: dict[str, ToolStatus] | None = None) -> None:
        self.statuses = dict(statuses or {})
        self.started: list[str] = []
        self.stopped: list[str] = []

    def tick(self) -> None:
        pass

    def status(self, tool_id: str) -> ToolStatus:
        return self.statuses.get(tool_id, ToolStatus(tool_id, "stopped"))

    def start(self, tool: ToolConfig) -> ToolStatus:
        self.started.append(tool.id)
        status = ToolStatus(tool.id, "running", pid=4200 + len(self.started), started_at=time.time())
        self.statuses[tool.id] = status
        return status

    def stop_begin(self, tool: ToolConfig) -> ToolStatus:
        self.stopped.append(tool.id)
        previous = self.status(tool.id)
        status = ToolStatus(tool.id, "stopping", pid=previous.pid, started_at=previous.started_at)
        self.statuses[tool.id] = status
        return status

    def stop_all_begin(self, tools: dict[str, ToolConfig]) -> list[str]:
        for tool in tools.values():
            if self.status(tool.id).active:
                self.stop_begin(tool)
        return []


def build_bridge(manager: FixedManager | None = None) -> AppBridge:
    return AppBridge(manager=manager or FixedManager(), auto_start_timers=False)


def test_lattice_icon_asset_loads(qapp):
    path = icon_path()
    expected_name = "lattice.ico" if sys.platform == "win32" else "lattice-mark.svg"
    assert path.name == expected_name
    assert path.is_file()
    assert not QIcon(str(path)).isNull()
    if path.suffix == ".svg":
        source = path.read_text(encoding="utf-8")
        assert "<rect" not in source
        assert "rx=" not in source


def test_tool_model_lists_searches_and_filters(qapp):
    save(ToolConfig("runner-special", "Alpha Console", "sleep 1", "/tmp/search-path-token"))
    save(ToolConfig("idle-tool", "Beta Worker", "sleep 1", "/tmp/idle-workspace"))
    manager = FixedManager(
        {
            "runner-special": ToolStatus(
                "runner-special",
                "running",
                pid=4321,
                started_at=time.time() - 10,
            ),
            "idle-tool": ToolStatus("idle-tool", "stopped"),
        }
    )
    bridge = build_bridge(manager)

    assert bridge.model.totalCount == 2
    assert bridge.model.runningCount == 1
    assert bridge.model.stoppedCount == 1
    assert bridge.selectedId == "runner-special"
    assert bridge.selected["active"] is True
    assert bridge.selected["stateLabel"] == "运行中"

    bridge.setSearchText("alpha")
    assert bridge.model.visibleCount == 1
    assert bridge.model.get(0)["toolId"] == "runner-special"

    bridge.setSearchText("idle-tool")
    assert bridge.model.visibleCount == 1
    assert bridge.model.get(0)["toolId"] == "idle-tool"

    bridge.setSearchText("search-path-token")
    assert bridge.model.visibleCount == 1
    assert bridge.model.get(0)["toolId"] == "runner-special"

    bridge.setSearchText("")
    bridge.setFilterMode("running")
    assert bridge.model.visibleCount == 1
    assert bridge.model.get(0)["toolId"] == "runner-special"

    bridge.setFilterMode("stopped")
    assert bridge.model.visibleCount == 1
    assert bridge.model.get(0)["toolId"] == "idle-tool"

    manager.statuses["idle-tool"] = ToolStatus("idle-tool", "exited", exit_code=7)
    bridge.refreshStatus()
    assert bridge.model.idleCount == 0
    assert bridge.model.exitedCount == 1
    bridge.setFilterMode("exited")
    assert bridge.model.visibleCount == 1
    assert bridge.model.get(0)["exitCodeText"] == "7"

    bridge.setSearchText("no-such-unit")
    assert bridge.model.visibleCount == 0
    bridge.clearFilters()
    assert bridge.model.visibleCount == 2
    assert bridge.searchText == ""
    assert bridge.filterMode == "all"
    bridge.shutdown()


def test_tool_model_groups_orders_and_searches(qapp):
    save(ToolConfig("ungrouped", "Loose Tool", "true", tempfile.gettempdir()))
    save(ToolConfig("trainer", "Trainer", "true", tempfile.gettempdir(), group="02 TRAINING"))
    save(ToolConfig("runtime", "Runtime", "true", tempfile.gettempdir(), group="01 SERVICES"))
    bridge = build_bridge()

    assert [bridge.model.get(row)["toolId"] for row in range(3)] == ["runtime", "trainer", "ungrouped"]
    assert [bridge.model.get(row)["toolGroup"] for row in range(3)] == [
        "01 SERVICES",
        "02 TRAINING",
        "未分组",
    ]
    bridge.setSearchText("training")
    assert bridge.model.visibleCount == 1
    assert bridge.model.get(0)["toolId"] == "trainer"
    bridge.shutdown()


def test_status_refresh_is_incremental_and_keeps_selection_identity(qapp):
    save(ToolConfig("steady", "Steady Unit", "sleep 1", tempfile.gettempdir()))
    manager = FixedManager(
        {
            "steady": ToolStatus(
                "steady",
                "running",
                pid=4321,
                started_at=time.time() - 10,
            )
        }
    )
    bridge = build_bridge(manager)
    identity_changes = QSignalSpy(bridge.selectionIdentityChanged)
    selected_updates = QSignalSpy(bridge.selectedChanged)
    model_resets = QSignalSpy(bridge.model.modelReset)
    data_updates = QSignalSpy(bridge.model.dataChanged)

    manager.statuses["steady"] = ToolStatus("steady", "stopped", exit_code=0)
    bridge.refreshStatus()

    assert identity_changes.count() == 0
    assert selected_updates.count() == 1
    assert model_resets.count() == 0
    assert data_updates.count() == 1
    assert bridge.selected["state"] == "stopped"

    selected_update_count = selected_updates.count()
    data_update_count = data_updates.count()
    bridge.refreshStatus()
    assert selected_updates.count() == selected_update_count
    assert data_updates.count() == data_update_count
    bridge.shutdown()


def test_font_scale_clamps_and_persists(qapp):
    bridge = build_bridge()
    changes = QSignalSpy(bridge.fontScaleChanged)

    bridge.setFontScale(0.25)
    assert bridge.fontScale == 0.80
    bridge.setFontScale(2.0)
    assert bridge.fontScale == 1.50
    bridge.setFontScale(1.174)
    assert bridge.fontScale == 1.17
    assert changes.count() == 3
    bridge.shutdown()

    restored = build_bridge()
    assert restored.fontScale == 1.17
    restored.shutdown()


def test_theme_switch_updates_frontend_tokens_and_persists(qapp):
    bridge = build_bridge()
    assert {theme["id"] for theme in bridge.availableThemes} >= {"lattice-day", "lattice-night", "lattice-archive"}

    assert bridge.setTheme("lattice-night") is True
    assert bridge.themeId == "lattice-night"
    assert bridge.themeAppearance == "dark"
    assert bridge.themeShell == "operations"
    assert bridge.themeTokens["paper"] == "#1b201c"
    bridge.shutdown()

    restored = build_bridge()
    assert restored.themeId == "lattice-night"
    restored.shutdown()


def test_archive_theme_selects_archive_shell(qapp):
    bridge = build_bridge()

    assert bridge.setTheme("lattice-archive") is True
    assert bridge.themeAppearance == "light"
    assert bridge.themeShell == "archive"
    assert bridge.themeTokens["command"] == "#c7432c"
    bridge.shutdown()


def test_bridge_tool_editor_round_trip(qapp):
    source = ToolConfig(
        "demo",
        "演示",
        "echo hello\nsleep 1",
        tempfile.gettempdir(),
        default_shell(),
        {"PORT": "1234"},
        True,
        "INT",
        4.5,
        group="模型训练",
    )
    save(source)
    bridge = build_bridge()
    bridge.selectTool("demo")

    draft = bridge.selectedToolDraft()
    assert draft == {
        "originalId": "demo",
        "id": "demo",
        "name": "演示",
        "group": "模型训练",
        "cwd": str(Path(tempfile.gettempdir())),
        "cmd": "echo hello\nsleep 1",
        "shell": default_shell(),
        "envText": "PORT=1234",
        "autostart": True,
        "stopSignal": "INT",
        "stopTimeout": 4.5,
        "launch": None,
        "readiness": {
            "mode": "auto",
            "grace_seconds": 3.0,
            "timeout_seconds": 120.0,
            "health_url": "",
            "health_port": None,
        },
        "rawMode": True,
        "source": "",
        "checks": [],
        "setupRequired": False,
        "setupSummary": "",
        "setupTarget": "",
        "setupNetwork": False,
        "setupCommands": [],
    }

    draft.update(name="演示二号", group="实验服务", envText="PORT=2345\nMODE=dev", stopSignal="TERM")
    assert bridge.saveToolDraft(draft) is True
    updated = load_file(paths.tool_toml("demo"))
    assert updated.name == "演示二号"
    assert updated.group == "实验服务"
    assert updated.env == {"PORT": "2345", "MODE": "dev"}
    assert updated.stop_signal == "TERM"
    bridge.shutdown()


def test_bridge_rejects_invalid_environment_without_writing(qapp):
    bridge = build_bridge()
    errors: list[tuple[str, str, str]] = []
    bridge.dialogRequested.connect(lambda title, message, kind: errors.append((title, message, kind)))
    draft = bridge.newToolDraft()
    draft.update(id="broken", name="Broken", cwd=tempfile.gettempdir(), cmd="echo ok", envText="MISSING_SEPARATOR")

    assert bridge.saveToolDraft(draft) is False
    assert not paths.tool_toml("broken").exists()
    assert "缺少 =" in errors[-1][1]
    bridge.shutdown()


def test_bridge_never_saves_while_environment_setup_is_pending(qapp, tmp_path):
    bridge = build_bridge()
    errors: list[tuple[str, str, str]] = []
    bridge.dialogRequested.connect(lambda title, message, kind: errors.append((title, message, kind)))
    draft = bridge.newToolDraft()
    draft.update(
        id="pending-setup",
        name="Pending setup",
        cwd=str(tmp_path),
        cmd="generated",
        setupRequired=True,
        rawMode=False,
    )

    assert bridge.saveToolDraft(draft) is False
    assert not paths.tool_toml("pending-setup").exists()
    assert errors[-1][0] == "需要准备环境"
    bridge.shutdown()


def test_bridge_prefills_program_import_without_qwidget_dialog(qapp, tmp_path):
    script = tmp_path / "quick start.py"
    script.write_text("print('ready')\n", encoding="utf-8")
    bridge = build_bridge()
    requested: list[tuple[str, dict]] = []
    bridge.editorRequested.connect(lambda mode, draft: requested.append((mode, dict(draft))))

    bridge.prepareImport(QUrl.fromLocalFile(str(script)).toString())

    assert len(requested) == 1
    mode, draft = requested[0]
    assert mode == "import"
    assert draft["name"] == "quick start"
    assert draft["cwd"] == str(tmp_path)
    assert sys.executable not in draft["cmd"]
    assert str(script) in draft["cmd"]
    assert draft["setupRequired"] is True
    assert draft["launch"]["detector"] == "python"
    bridge.shutdown()


def test_launch_command_cross_platform_contract(tmp_path):
    script = tmp_path / "serve tool.py"
    script.write_text("print('ready')\n", encoding="utf-8")
    windows_command, windows_shell = AppBridge.command_for_launch_path(
        script,
        r"C:\Windows\System32\cmd.exe",
        platform_name="nt",
        python_executable=r"C:\Python312\python.exe",
    )
    assert windows_command == subprocess.list2cmdline([r"C:\Python312\python.exe", str(script.resolve())])
    assert windows_shell == r"C:\Windows\System32\cmd.exe"

    executable = tmp_path / "My Tool.exe"
    executable.write_bytes(b"")
    exe_command, exe_shell = AppBridge.command_for_launch_path(
        executable,
        "powershell.exe",
        platform_name="nt",
    )
    assert exe_command == f'start "" /wait {subprocess.list2cmdline([str(executable.resolve())])}'
    assert exe_shell.casefold().endswith("cmd.exe")


def test_bridge_start_stop_restart_and_autostart(qapp):
    save(ToolConfig("manual", "Manual", "sleep 1", tempfile.gettempdir()))
    save(ToolConfig("auto", "Auto", "sleep 1", tempfile.gettempdir(), autostart=True))
    manager = FixedManager()
    bridge = build_bridge(manager)

    bridge.selectTool("manual")
    bridge.startSelected()
    assert manager.started == ["manual"]
    assert bridge.selected["active"] is True

    bridge.stopSelected()
    assert manager.stopped == ["manual"]
    assert bridge.selected["state"] == "stopping"

    manager.statuses["manual"] = ToolStatus("manual", "stopped")
    bridge.refreshStatus()
    bridge.restartSelected()
    assert manager.started == ["manual", "manual"]

    bridge.startAutostart()
    assert manager.started[-1] == "auto"
    bridge.stopAll()
    assert set(manager.stopped) >= {"manual", "auto"}
    bridge.shutdown()


def test_bridge_log_view_clear_preserves_disk_log(qapp):
    save(ToolConfig("logger", "Logger", "echo log", tempfile.gettempdir()))
    paths.log_file("logger").write_text("\x1b[31mfirst\x1b[0m\nsecond\n", encoding="utf-8")
    bridge = build_bridge()
    bridge.selectTool("logger")

    assert "first" in bridge.logText
    assert "\x1b" not in bridge.logText
    assert bridge.logModel.count == 2
    assert bridge.logModel.get(0)["logMessage"] == "first"
    before = paths.log_file("logger").read_text(encoding="utf-8")
    bridge.clearVisibleLog()
    assert "PERSISTENT RECORD RETAINED" in bridge.logText
    assert bridge.logModel.count == 1
    assert bridge.logModel.get(0)["logLevel"] == "command"
    assert paths.log_file("logger").read_text(encoding="utf-8") == before
    bridge.shutdown()


def test_bridge_copies_visible_log_and_preserves_clipboard_when_empty(qapp):
    save(ToolConfig("logger", "Logger", "echo log", tempfile.gettempdir()))
    paths.log_file("logger").write_text("\x1b[31mfirst\x1b[0m\nsecond\n", encoding="utf-8")
    bridge = build_bridge()
    bridge.selectTool("logger")
    toasts: list[tuple[str, str]] = []
    bridge.toastRequested.connect(lambda message, kind: toasts.append((message, kind)))
    clipboard = qapp.clipboard()
    previous = clipboard.text()

    try:
        clipboard.setText("sentinel")
        bridge.copyVisibleLog()
        assert clipboard.text() == bridge.logText == "first\nsecond\n"
        assert toasts[-1] == ("已复制当前显示的运行记录", "success")

        bridge._set_log_text("")
        clipboard.setText("keep-me")
        bridge.copyVisibleLog()
        assert clipboard.text() == "keep-me"
        assert toasts[-1] == ("当前没有可复制的运行记录", "warning")
    finally:
        clipboard.setText(previous)
        bridge.shutdown()


def test_bridge_opens_full_log_with_visible_feedback(qapp, monkeypatch):
    save(ToolConfig("logger", "Logger", "echo log", tempfile.gettempdir()))
    log_path = paths.log_file("logger")
    log_path.write_text("persistent output\n", encoding="utf-8")
    bridge = build_bridge()
    bridge.selectTool("logger")
    revealed: list[Path] = []
    toasts: list[tuple[str, str]] = []
    dialogs: list[tuple[str, str, str]] = []
    bridge.toastRequested.connect(lambda message, kind: toasts.append((message, kind)))
    bridge.dialogRequested.connect(lambda title, message, kind: dialogs.append((title, message, kind)))

    monkeypatch.setattr(bridge, "_reveal_path", lambda path: revealed.append(path) or True)
    bridge.openSelectedLog()
    assert revealed[-1] == log_path
    assert toasts[-1] == (f"已在文件管理器中定位 {log_path.name}", "success")

    monkeypatch.setattr(bridge, "_reveal_path", lambda _path: False)
    bridge.openSelectedLog()
    assert dialogs[-1][0] == "无法定位完整日志"
    assert str(log_path) in dialogs[-1][1]
    bridge.shutdown()


def test_bridge_opens_only_setup_logs_from_the_state_directory(qapp, monkeypatch, tmp_path):
    bridge = build_bridge()
    setup_log = paths.setup_logs_dir() / "setup.log"
    setup_log.parent.mkdir(parents=True, exist_ok=True)
    setup_log.write_text("setup output\n", encoding="utf-8")
    revealed: list[Path] = []
    dialogs: list[tuple[str, str, str]] = []
    bridge.dialogRequested.connect(lambda title, message, kind: dialogs.append((title, message, kind)))
    monkeypatch.setattr(bridge, "_reveal_path", lambda path: revealed.append(path) or True)

    bridge.openSetupLog(str(setup_log))
    bridge.openSetupLog(str(tmp_path / "outside.log"))

    assert revealed == [setup_log.resolve()]
    assert dialogs[-1][0] == "无法定位准备日志"
    bridge.shutdown()


def test_startup_timeout_and_exit_dialogs_include_complete_log_path(qapp):
    save(ToolConfig("service", "Service", "sleep 1", tempfile.gettempdir()))
    log_path = paths.log_file("service")
    log_path.write_text("boot output\n", encoding="utf-8")
    manager = FixedManager({"service": ToolStatus("service", "starting", pid=4321)})
    bridge = build_bridge(manager)
    dialogs: list[tuple[str, str, str]] = []
    bridge.dialogRequested.connect(lambda title, message, kind: dialogs.append((title, message, kind)))

    manager.statuses["service"] = ToolStatus("service", "unready", pid=4321, message="timeout")
    bridge.refreshStatus()
    manager.statuses["service"] = ToolStatus("service", "exited", pid=4321, exit_code=7, message="exit 7")
    bridge.refreshStatus()

    assert dialogs[0][0] == "Service 启动超时"
    assert str(log_path) in dialogs[0][1]
    assert dialogs[1][0] == "Service 未能启动"
    assert str(log_path) in dialogs[1][1]
    bridge.shutdown()


def test_reveal_path_uses_first_available_linux_file_manager(monkeypatch, tmp_path):
    log_path = tmp_path / "worker.log"
    log_path.write_text("output\n", encoding="utf-8")
    started: list[tuple[str, list[str]]] = []

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(
        "tooldeck.gui.bridge.shutil.which",
        lambda program: f"/usr/bin/{program}" if program == "dolphin" else None,
    )
    monkeypatch.setattr(
        AppBridge,
        "_start_detached",
        staticmethod(lambda program, arguments: started.append((program, arguments)) or True),
    )

    assert AppBridge._reveal_path(log_path) is True
    assert started == [("dolphin", ["--select", str(log_path.resolve())])]


def test_telemetry_pause_resume_state(qapp, monkeypatch):
    bridge = build_bridge()
    monkeypatch.setattr(bridge, "queryHardware", lambda: None)
    assert bridge.telemetry["sampleSequence"] == 0

    bridge.setHardwarePaused(True)
    assert bridge.hardwarePaused is True
    assert bridge.telemetry["state"] == "PAUSED"
    assert bridge.telemetry["sampleSequence"] == 0
    assert not bridge.hardware_timer.isActive()

    bridge.setHardwarePaused(False)
    assert bridge.hardwarePaused is False
    assert bridge.telemetry["state"] == "SYNC"
    assert bridge.telemetry["sampleSequence"] == 0
    assert bridge.hardware_timer.isActive()
    bridge.shutdown()


def test_hardware_sample_emits_one_telemetry_update(qapp, monkeypatch):
    bridge = build_bridge()
    monkeypatch.setattr(bridge._system_sampler, "sample", lambda: SystemSample(12.0, 34.0, "12 / 32 GiB"))
    monkeypatch.setattr("tooldeck.gui.bridge.shutil.which", lambda _program: None)
    changes = QSignalSpy(bridge.telemetryChanged)

    bridge.queryHardware()

    assert changes.count() == 1
    assert bridge.telemetry["state"] == "PARTIAL"
    assert bridge.telemetry["sampleSequence"] == 1
    bridge.shutdown()


def test_qml_engine_loads_new_workspace_without_warnings(qapp):
    save(ToolConfig("one", "工具一", "sleep 1", tempfile.gettempdir(), group="模型训练"))
    save(ToolConfig("two", "工具二", "sleep 1", tempfile.gettempdir(), group="常驻服务"))
    bridge = build_bridge()
    bridge.setTheme("lattice-day")
    bridge.setFontScale(1.0)
    messages: list[str] = []

    def handler(_kind, _context, message: str) -> None:
        messages.append(message)

    qInstallMessageHandler(handler)
    engine, _ = create_engine(bridge)
    qapp.processEvents()

    assert len(engine.rootObjects()) == 1
    root = engine.rootObjects()[0]
    root.show()
    root.requestActivate()
    QTest.qWait(60)
    assert root.objectName() == "mainWindow"
    assert root.property("title") == "Lattice / Local Operations"
    for object_name in (
        "commandRail",
        "brandMark",
        "processIndex",
        "operationsWorkspace",
        "telemetryBand",
        "toolList",
        "logConsole",
        "logText",
        "copyLogAction",
        "operationsContent",
        "manifestPanel",
        "toolEditor",
        "editorGroup",
        "editorSource",
        "editorSetupPanel",
        "editorSetupAction",
        "editorSetupLogPath",
        "editorSetupLogAction",
        "editorAdvancedToggle",
        "editorAdvancedExecution",
        "editorRawMode",
        "editorPrimaryAction",
        "fontScaleSection",
        "fontScaleSlider",
        "fontScaleValue",
        "themeSelector",
    ):
        assert root.findChild(QObject, object_name) is not None

    operations_content = root.findChild(QObject, "operationsContent")
    log_text = root.findChild(QObject, "logText")
    scale_value = root.findChild(QObject, "fontScaleValue")
    assert operations_content.property("opacity") == 1.0
    bridge.refreshStatus()
    QTest.qWait(90)
    assert operations_content.property("opacity") == 1.0

    assert log_text.property("font").pixelSize() == 11
    assert scale_value.property("text") == "100%"
    bridge.setFontScale(1.5)
    QTest.qWait(30)
    assert log_text.property("font").pixelSize() == 17
    assert scale_value.property("text") == "150%"
    bridge.setFontScale(0.8)
    QTest.qWait(30)
    assert log_text.property("font").pixelSize() == 9
    assert scale_value.property("text") == "80%"

    search = root.findChild(QObject, "toolSearch")
    editor = root.findChild(QObject, "toolEditor")
    QTest.keyClick(root, Qt.Key.Key_N, Qt.KeyboardModifier.ControlModifier)
    QTest.qWait(500)
    assert editor.property("opened") is True
    assert editor.property("mode") == "add"
    assert editor.property("advancedExpanded") is False
    assert editor.property("rawMode") is False
    assert root.findChild(QObject, "editorId").property("text") == "tool"
    assert root.findChild(QObject, "editorId").property("visible") is False
    assert root.findChild(QObject, "editorSource").property("visible") is True
    assert root.findChild(QObject, "editorAdvancedExecution").property("visible") is False
    assert root.findChild(QObject, "editorPrimaryAction").property("enabled") is False
    QTest.mouseClick(
        root,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(18, root.height() // 2),
    )
    QTest.qWait(240)
    assert editor.property("opened") is False

    QTest.keyClick(root, Qt.Key.Key_F2)
    QTest.qWait(500)
    assert editor.property("opened") is True
    assert editor.property("mode") == "edit"
    assert editor.property("originalId") in {"one", "two"}
    assert editor.property("advancedExpanded") is True
    assert editor.property("rawMode") is True
    assert root.findChild(QObject, "editorAdvancedExecution").property("visible") is True
    assert root.findChild(QObject, "editorGroup").property("text") in {"模型训练", "常驻服务"}
    QTest.keyClick(root, Qt.Key.Key_Escape)
    QTest.qWait(240)

    QTest.keyClick(root, Qt.Key.Key_K, Qt.KeyboardModifier.ControlModifier)
    qapp.processEvents()
    assert search.property("activeFocus") is True
    unexpected_messages = [message for message in messages if "QFontDatabase: Cannot find font directory" not in message]
    assert unexpected_messages == []

    root.hide()
    shiboken6.delete(root)
    shiboken6.delete(engine)
    qInstallMessageHandler(None)
    bridge.shutdown()


def test_editor_setup_progress_unlocks_structured_add_flow(qapp, tmp_path):
    source = tmp_path / "project" / "main.py"
    source.parent.mkdir()
    source.write_text("print('ready')\n", encoding="utf-8")
    interpreter = source.parent / ".venv" / "bin" / "python"
    bridge = build_bridge()
    draft = bridge.newToolDraft()
    draft.update(
        id="prepared",
        name="Prepared",
        cwd=str(source.parent),
        cmd=f"{interpreter} {source}",
        source=str(source),
        launch={
            "mode": "argv",
            "detector": "python",
            "source": str(source),
            "argv": [str(interpreter), str(source)],
            "interpreter": str(interpreter),
            "managed_environment": True,
        },
        rawMode=False,
        setupRequired=True,
        setupSummary="创建项目环境",
        setupTarget=str(interpreter.parent.parent),
        setupCommands=["python -m venv .venv"],
    )
    engine, _ = create_engine(bridge)
    root = engine.rootObjects()[0]
    root.show()
    qapp.processEvents()

    QTest.keyClick(root, Qt.Key.Key_N, Qt.KeyboardModifier.ControlModifier)
    QTest.qWait(500)
    editor = root.findChild(QObject, "toolEditor")
    assert editor.property("opened") is True
    editor.setProperty("sourcePath", str(source))
    editor.setProperty("launchData", draft["launch"])
    editor.setProperty("setupRequired", True)
    editor.setProperty("setupSummary", "创建项目环境")
    editor.setProperty("setupTarget", str(interpreter.parent.parent))
    editor.setProperty("setupCommands", ["python -m venv .venv"])
    root.findChild(QObject, "editorName").setProperty("text", "Prepared")
    qapp.processEvents()
    assert root.findChild(QObject, "editorSetupPanel").property("visible") is True
    assert root.findChild(QObject, "editorSetupAction").property("visible") is True
    assert root.findChild(QObject, "editorPrimaryAction").property("enabled") is False

    editor.setProperty("setupToken", "setup-token")
    editor.setProperty("setupRunning", True)
    setup_log = tmp_path / "setup.log"
    bridge.setupProgressChanged.emit(
        {"token": "setup-token", "current": 0, "total": 0, "command": "", "logPath": str(setup_log)}
    )
    bridge.setupProgressChanged.emit(
        {"token": "setup-token", "current": 1, "total": 2, "command": "python -m venv .venv"}
    )
    qapp.processEvents()
    assert editor.property("setupLogPath") == str(setup_log)
    assert str(setup_log) in root.findChild(QObject, "editorSetupLogPath").property("text")
    assert "步骤 1 / 2" in editor.property("setupProgressText")

    completed_patch = dict(draft)
    completed_patch.update(
        suggestedId="prepared",
        setupRequired=False,
        setupSummary="",
        setupTarget="",
        setupNetwork=False,
        setupCommands=[],
        checks=[{"code": "python-environment", "level": "ok", "message": "环境可用"}],
    )
    bridge.setupFinished.emit(
        {
            "token": "setup-token",
            "success": True,
            "cancelled": False,
            "message": "环境准备完成",
            "logPath": str(tmp_path / "setup.log"),
            "source": str(source),
            "patch": completed_patch,
        }
    )
    QTest.qWait(30)
    assert editor.property("setupRequired") is False
    assert editor.property("setupRunning") is False
    assert root.findChild(QObject, "editorPrimaryAction").property("enabled") is True

    root.hide()
    shiboken6.delete(root)
    shiboken6.delete(engine)
    bridge.shutdown()


def test_archive_shell_loads_and_switches_without_runtime_warnings(qapp):
    save(ToolConfig("one", "工具一", "sleep 1", tempfile.gettempdir(), group="模型训练"))
    save(ToolConfig("two", "工具二", "sleep 1", tempfile.gettempdir(), group="常驻服务"))
    paths.log_file("one").write_text("[12:34:56] INFO copy target\n", encoding="utf-8")
    bridge = build_bridge()
    bridge.selectTool("one")
    bridge.setTheme("lattice-archive")
    messages: list[str] = []

    def handler(_kind, _context, message: str) -> None:
        messages.append(message)

    qInstallMessageHandler(handler)
    engine, _ = create_engine(bridge)
    qapp.processEvents()

    assert len(engine.rootObjects()) == 1
    root = engine.rootObjects()[0]
    root.show()
    root.requestActivate()
    QTest.qWait(120)
    archive = root.findChild(QObject, "archiveShell")
    operations = root.findChild(QObject, "operationsWorkspace")
    divider = root.findChild(QObject, "archiveWorkspaceDivider")
    matrix = root.findChild(QObject, "archiveMatrix")
    operations_scanner = root.findChild(QObject, "operationsScannerAnimation")
    startup_scanner = root.findChild(QObject, "startupScannerAnimation")
    assert archive is not None
    assert archive.property("visible") is True
    assert operations.property("visible") is False
    assert operations_scanner.property("running") is False
    assert startup_scanner.property("running") is False
    for object_name in (
        "archiveIdentityBand",
        "archiveGlobalActionsCell",
        "archiveGlobalActions",
        "archiveEvidenceBand",
        "archiveMatrix",
        "archiveToolList",
        "archiveDossier",
        "archiveLogText",
        "archiveCopyLogAction",
        "archiveTelemetryTrace",
    ):
        assert root.findChild(QObject, object_name) is not None

    for index in range(43):
        bridge._telemetry.update(
            sampleSequence=index + 1,
            cpuValue=20.0 + index,
            memoryValue=40.0 + index / 2,
            gpuValue=60.0 - index / 3,
        )
        bridge.telemetryChanged.emit()
    qapp.processEvents()
    cpu_history = archive.property("cpuHistory")
    if hasattr(cpu_history, "toVariant"):
        cpu_history = cpu_history.toVariant()
    assert len(cpu_history) == 42
    assert cpu_history[0] == 0.21
    assert cpu_history[-1] == 0.62

    history_length = len(cpu_history)
    bridge.setHardwarePaused(True)
    qapp.processEvents()
    paused_history = archive.property("cpuHistory")
    if hasattr(paused_history, "toVariant"):
        paused_history = paused_history.toVariant()
    assert len(paused_history) == history_length

    actions_cell = root.findChild(QObject, "archiveGlobalActionsCell")
    actions = root.findChild(QObject, "archiveGlobalActions")

    def assert_actions_centered() -> None:
        assert abs(actions.property("x") - (actions_cell.property("width") - actions.property("width")) / 2) < 0.6
        assert abs(actions.property("y") - (actions_cell.property("height") - actions.property("height")) / 2) < 0.6

    for width, height in ((1024, 700), (1280, 800), (1920, 900)):
        root.setProperty("width", width)
        root.setProperty("height", height)
        QTest.qWait(40)
        assert_actions_centered()

    archive_log = root.findChild(QObject, "archiveLogText")
    assert bridge.logModel.count == 1
    assert archive_log.property("count") == 1
    assert archive_log.property("height") > 0

    row_expression = QQmlExpression(
        QQmlEngine.contextForObject(archive_log), archive_log, "itemAtIndex(0)"
    )
    log_row = row_expression.evaluate()[0]
    assert not row_expression.hasError()
    assert log_row is not None

    def delegate_item(item_id: str):
        expression = QQmlExpression(QQmlEngine.contextForObject(log_row), log_row, item_id)
        item = expression.evaluate()[0]
        assert not expression.hasError()
        assert item is not None
        return item

    log_time = delegate_item("logTimeLabel")
    log_level = delegate_item("logLevelLabel")
    log_message = delegate_item("logMessageLabel")
    assert log_time.property("readOnly") is True
    assert log_time.property("selectByMouse") is True
    assert log_level.property("selectByMouse") is True
    assert log_message.property("selectByMouse") is True
    assert log_message.property("text") == "copy target"

    clipboard = qapp.clipboard()
    previous_clipboard = clipboard.text()
    try:
        clipboard.setText("sentinel")
        focus_expression = QQmlExpression(
            QQmlEngine.contextForObject(log_message), log_message, "forceActiveFocus()"
        )
        focus_expression.evaluate()
        assert not focus_expression.hasError()
        assert QMetaObject.invokeMethod(log_message, "selectAll") is True
        qapp.processEvents()
        assert log_message.property("activeFocus") is True
        assert log_message.property("selectedText") == "copy target"
        QTest.keyClick(root, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
        qapp.processEvents()
        assert clipboard.text() == "copy target"
    finally:
        clipboard.setText(previous_clipboard)

    QTest.keyClick(root, Qt.Key.Key_K, Qt.KeyboardModifier.ControlModifier)
    qapp.processEvents()
    assert root.findChild(QObject, "archiveToolSearch").property("activeFocus") is True

    root.setProperty("width", 2048)
    root.setProperty("height", 900)
    QTest.qWait(40)
    assert divider.property("minimumRatio") == 0.20
    assert divider.property("maximumRatio") == 0.80
    assert divider.property("currentRatio") == 0.60
    assert matrix.property("showAutostart") is True
    assert root.findChild(QObject, "archiveAutostartHeader").property("visible") is True
    assert root.findChild(QObject, "archiveStartAction").property("showLabel") is True

    bridge.setTheme("lattice-day")
    QTest.qWait(40)
    assert archive.property("visible") is False
    assert operations.property("visible") is True
    assert operations_scanner.property("running") is True

    unexpected_messages = [message for message in messages if "QFontDatabase: Cannot find font directory" not in message]
    assert unexpected_messages == []

    root.hide()
    shiboken6.delete(root)
    shiboken6.delete(engine)
    qInstallMessageHandler(None)
    bridge.shutdown()


def test_motion_animations_stop_with_hidden_shells(qapp):
    save(ToolConfig("one", "工具一", "sleep 1", tempfile.gettempdir(), group="模型训练"))
    save(ToolConfig("two", "工具二", "sleep 1", tempfile.gettempdir(), group="常驻服务"))
    bridge = build_bridge()
    bridge.setTheme("lattice-day")
    messages: list[str] = []

    def handler(_kind, _context, message: str) -> None:
        messages.append(message)

    def as_list(value):
        return value.toVariant() if hasattr(value, "toVariant") else value

    qInstallMessageHandler(handler)
    engine, _ = create_engine(bridge)
    qapp.processEvents()
    root = engine.rootObjects()[0]
    root.show()
    QTest.qWait(40)

    archive = root.findChild(QObject, "archiveShell")
    telemetry_animation = root.findChild(QObject, "archiveTelemetryAnimation")
    archive_selection_animation = root.findChild(QObject, "archiveSelectionAnimation")
    archive_tab_animation = root.findChild(QObject, "archiveTabAnimation")
    operations_selection_animation = root.findChild(QObject, "operationsSelectionAnimation")
    assert archive is not None
    assert telemetry_animation is not None
    assert archive_selection_animation is not None
    assert archive_tab_animation is not None
    assert operations_selection_animation is not None
    assert archive.property("visible") is False

    bridge._telemetry.update(sampleSequence=1, cpuValue=28.0, memoryValue=52.0, gpuValue=34.0)
    bridge.telemetryChanged.emit()
    qapp.processEvents()
    assert as_list(archive.property("cpuHistory")) == []
    assert telemetry_animation.property("running") is False

    bridge.setTheme("lattice-archive")
    QTest.qWait(50)
    assert archive.property("visible") is True
    assert len(as_list(archive.property("cpuHistory"))) == 42
    assert telemetry_animation.property("running") is True
    progress = float(archive.property("traceProgress"))
    assert 0.0 < progress < 1.0

    bridge._telemetry.update(sampleSequence=2, cpuValue=61.0, memoryValue=58.0, gpuValue=47.0)
    bridge.telemetryChanged.emit()
    qapp.processEvents()
    assert telemetry_animation.property("running") is True
    QTest.qWait(520)
    assert telemetry_animation.property("running") is False
    assert abs(float(archive.property("traceProgress")) - 1.0) < 0.001

    next_tool = "one" if bridge.selectedId != "one" else "two"
    bridge.selectTool(next_tool)
    qapp.processEvents()
    assert archive_selection_animation.property("running") is True
    assert archive_tab_animation.property("running") is True

    bridge.setTheme("lattice-day")
    QTest.qWait(40)
    assert archive.property("visible") is False
    assert telemetry_animation.property("running") is False
    assert archive_selection_animation.property("running") is False
    assert archive_tab_animation.property("running") is False

    operations_target = "one" if bridge.selectedId != "one" else "two"
    bridge.selectTool(operations_target)
    qapp.processEvents()
    assert operations_selection_animation.property("running") is True
    QTest.qWait(260)
    assert operations_selection_animation.property("running") is False

    unexpected_messages = [message for message in messages if "QFontDatabase: Cannot find font directory" not in message]
    assert unexpected_messages == []

    root.hide()
    shiboken6.delete(root)
    shiboken6.delete(engine)
    qInstallMessageHandler(None)
    bridge.shutdown()
