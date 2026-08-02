from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import shiboken6
from PySide6.QtCore import QObject, QPoint, Qt, QUrl, qInstallMessageHandler
from PySide6.QtGui import QIcon
from PySide6.QtTest import QSignalSpy, QTest

from tooldeck import paths
from tooldeck.config import ToolConfig, load_file, save
from tooldeck.gui.app import create_engine, icon_path
from tooldeck.gui.bridge import AppBridge
from tooldeck.procs import ToolStatus


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

    bridge.setSearchText("no-such-unit")
    assert bridge.model.visibleCount == 0
    bridge.clearFilters()
    assert bridge.model.visibleCount == 2
    assert bridge.searchText == ""
    assert bridge.filterMode == "all"
    bridge.shutdown()


def test_tool_model_groups_orders_and_searches(qapp):
    save(ToolConfig("ungrouped", "Loose Tool", "true", "/tmp"))
    save(ToolConfig("trainer", "Trainer", "true", "/tmp", group="02 TRAINING"))
    save(ToolConfig("runtime", "Runtime", "true", "/tmp", group="01 SERVICES"))
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
    save(ToolConfig("steady", "Steady Unit", "sleep 1", "/tmp"))
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


def test_bridge_tool_editor_round_trip(qapp):
    source = ToolConfig(
        "demo",
        "演示",
        "echo hello\nsleep 1",
        "/tmp",
        "/usr/bin/fish",
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
        "cwd": str(Path("/tmp")),
        "cmd": "echo hello\nsleep 1",
        "shell": "/usr/bin/fish",
        "envText": "PORT=1234",
        "autostart": True,
        "stopSignal": "INT",
        "stopTimeout": 4.5,
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
    draft.update(id="broken", name="Broken", cwd="/tmp", cmd="echo ok", envText="MISSING_SEPARATOR")

    assert bridge.saveToolDraft(draft) is False
    assert not paths.tool_toml("broken").exists()
    assert "缺少 =" in errors[-1][1]
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
    assert sys.executable in draft["cmd"]
    assert str(script) in draft["cmd"]
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
    save(ToolConfig("manual", "Manual", "sleep 1", "/tmp"))
    save(ToolConfig("auto", "Auto", "sleep 1", "/tmp", autostart=True))
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
    save(ToolConfig("logger", "Logger", "echo log", "/tmp"))
    paths.log_file("logger").write_text("\x1b[31mfirst\x1b[0m\nsecond\n", encoding="utf-8")
    bridge = build_bridge()
    bridge.selectTool("logger")

    assert "first" in bridge.logText
    assert "\x1b" not in bridge.logText
    before = paths.log_file("logger").read_text(encoding="utf-8")
    bridge.clearVisibleLog()
    assert "DISK LOG PRESERVED" in bridge.logText
    assert paths.log_file("logger").read_text(encoding="utf-8") == before
    bridge.shutdown()


def test_bridge_opens_full_log_with_visible_feedback(qapp, monkeypatch):
    save(ToolConfig("logger", "Logger", "echo log", "/tmp"))
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

    bridge.setHardwarePaused(True)
    assert bridge.hardwarePaused is True
    assert bridge.telemetry["state"] == "PAUSED"
    assert not bridge.hardware_timer.isActive()

    bridge.setHardwarePaused(False)
    assert bridge.hardwarePaused is False
    assert bridge.telemetry["state"] == "SYNC"
    assert bridge.hardware_timer.isActive()
    bridge.shutdown()


def test_qml_engine_loads_new_workspace_without_warnings(qapp):
    save(ToolConfig("one", "工具一", "sleep 1", "/tmp", group="模型训练"))
    save(ToolConfig("two", "工具二", "sleep 1", "/tmp", group="常驻服务"))
    bridge = build_bridge()
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
        "operationsContent",
        "manifestPanel",
        "toolEditor",
        "editorGroup",
        "fontScalePanel",
        "fontScaleSlider",
        "fontScaleValue",
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
    assert root.findChild(QObject, "editorId").property("text") == "tool"
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
