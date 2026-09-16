"""Exercise real process services, exact configuration writes and log boundaries."""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

import pytest
import shiboken6
from PySide6.QtCore import QObject, QtMsgType, qInstallMessageHandler
from PySide6.QtTest import QTest

from tooldeck import paths
from tooldeck.config import ToolConfig, load_file, save
from tooldeck.gui.app import create_engine
from tooldeck.gui.bridge import AppBridge
from tooldeck.procs import ProcManager, StateFileError
from tooldeck.tailer import LogTailer, READ_BYTES, SEGMENT_CHARS


def until(predicate, seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        QTest.qWait(10)
        time.sleep(0.005)
    assert predicate(), "Condition did not become true before the deadline"


def python_command(source: str) -> str:
    args = [sys.executable, "-u", "-X", "utf8", "-c", source]
    return subprocess.list2cmdline(args) if os.name == "nt" else shlex.join(args)


def test_stream_decoder_handles_unicode_ansi_replacement_and_live_progress(tmp_path):
    path = tmp_path / "output.log"
    path.write_bytes(b"\x1b[3")
    tailer = LogTailer(path)
    assert tailer.read() == ""
    with path.open("ab") as stream:
        stream.write(b"1m" + "中".encode()[:1])
    assert tailer.read() == ""
    with path.open("ab") as stream:
        stream.write("中".encode()[1:] + b"\x1b[0m\r\nprogress 1")
    batch = tailer.read_batch()
    assert batch.completed == "中\n"
    assert batch.preview == "progress 1"
    with path.open("ab") as stream:
        stream.write(b"\rprogress 2")
    assert tailer.read_batch().preview == "progress 2"
    replacement = tmp_path / "new.log"
    replacement.write_bytes(b"x" * path.stat().st_size)
    replacement.replace(path)
    batch = tailer.read_batch()
    assert batch.reset
    assert batch.preview.startswith("x")
    tailer.seek_end()
    assert tailer.read_batch().preview == ""


def test_five_mib_burst_has_bounded_reads_and_partial_line_state(tmp_path):
    path = tmp_path / "burst.log"
    payload = b"x" * (5 * 1024 * 1024)
    path.write_bytes(payload)
    tailer = LogTailer(path)
    received = 0
    while tailer.offset < len(payload):
        before = tailer.offset
        batch = tailer.read_batch()
        assert tailer.offset - before <= READ_BYTES
        assert len(batch.preview) < SEGMENT_CHARS
        received += len(batch.completed)
    received += len(tailer.flush_pending())
    assert received == len(payload)


@pytest.mark.parametrize("command", ["\necho 中文", "\n\necho a\necho b", "echo '''quoted'''\n\\test", "\r\necho x"])
def test_config_preserves_exact_command_through_disk(command):
    tool = ToolConfig("command", "Command", command, str(Path.home()))
    destination = save(tool)
    assert load_file(destination).cmd == command


def test_corrupt_process_state_is_not_reported_as_stopped():
    paths.ensure_dirs()
    path = paths.state_json("broken")
    path.write_text('{"pid": true}', encoding="utf-8")
    manager = ProcManager()
    with pytest.raises(StateFileError, match="pid"):
        manager.status("broken")
    assert json.loads(path.read_text())["pid"] is True


def test_real_restart_replaces_pid_and_rejects_overlapping_operations(qapp, tmp_path):
    tool = ToolConfig("restart", "Restart", python_command("import time; print('alive'); time.sleep(60)"), str(tmp_path), stop_timeout=0.2)
    save(tool)
    bridge = AppBridge()
    errors: list[str] = []
    bridge.dialogRequested.connect(lambda _title, message, _kind: errors.append(message))
    try:
        until(lambda: bridge.selected.get("state") == "stopped", 3)
        bridge.startSelected()
        bridge.startSelected()
        assert any("尚未完成" in error for error in errors)
        until(lambda: bridge.selected.get("active") and not bridge.selected.get("pending"), 5)
        pid = bridge.selected["pid"]
        bridge.restartSelected()
        until(lambda: bridge.selected.get("active") and not bridge.selected.get("pending") and bridge.selected["pid"] != pid, 6)
        bridge.clearVisibleLog()
        until(lambda: not bridge.log_service._busy, 3)
        assert "DISPLAY BUFFER CLEARED" in bridge.logText
        assert "alive" not in bridge.logText
        assert "alive" in paths.log_file(tool.id).read_text(encoding="utf-8")
        bridge.stopSelected()
        until(lambda: not bridge.selected.get("active") and not bridge.selected.get("pending"), 6)
    finally:
        try:
            if bridge.selected.get("active"):
                bridge.stopSelected()
                until(lambda: not bridge.selected.get("active"), 6)
        finally:
            bridge.shutdown()


def test_failed_state_persistence_cleans_new_process(tmp_path, monkeypatch):
    tool = ToolConfig("persist", "Persist", python_command("import time; time.sleep(60)"), str(tmp_path))
    manager = ProcManager()
    owned_pids: list[int] = []

    def reject_state(tool_id, state):
        owned_pids.append(state["pid"])
        raise OSError("simulated full state filesystem")

    monkeypatch.setattr(manager, "_write_state", reject_state)
    from tooldeck.procs import ProcessError
    from tooldeck.util import proc_alive
    with pytest.raises(ProcessError, match="已清理"):
        manager.start(tool)
    assert len(owned_pids) == 1
    assert not proc_alive(owned_pids[0])
    assert not manager._children


def test_cli_tail_cursor_preserves_append_and_exact_raw_suffix(tmp_path):
    from tooldeck.tailer import tail_bytes
    path = tmp_path / "cli.log"
    path.write_bytes(b"old\nprogress 1\rprogress 2\npartial")
    assert tail_bytes(path, 2) == b"progress 1\rprogress 2\npartial"
    tailer = LogTailer(path)
    end = tailer.seek_lines(2)
    with path.open("ab") as stream:
        stream.write(" 中文\n".encode())
    batch = tailer.read_batch()
    assert batch.completed == "progress 2\npartial 中文\n"
    assert tailer.offset > end
    assert tail_bytes(path, 1) == "partial 中文\n".encode()
    assert tail_bytes(path, 0) == b""


def test_original_interface_receives_worker_results(qapp, tmp_path):
    save(ToolConfig("service", "后台服务", python_command("import time; print('ready 中文'); time.sleep(60)"), str(tmp_path), stop_timeout=0.2))
    bridge = AppBridge()
    messages: list[str] = []
    previous_handler = qInstallMessageHandler(lambda kind, _context, message: messages.append(message) if kind in {QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg} else None)
    engine, _ = create_engine(bridge)
    root = engine.rootObjects()[0]
    try:
        until(lambda: bridge.selected.get("state") == "stopped", 3)
        bridge.startSelected()
        until(lambda: bridge.selected.get("active") and not bridge.selected.get("pending"), 5)
        log = root.findChild(QObject, "logText")
        until(lambda: "ready 中文" in log.property("text"), 3)
        assert root.findChild(QObject, "telemetryBand") is not None
        assert root.findChild(QObject, "manifestPanel") is not None
        until(lambda: bridge.selected.get("state") == "running", 5)
        assert bridge.selected["stateColor"] == "#16b8a6"
        thread = bridge.process_service.thread
        for _ in range(30):
            bridge.refreshStatus()
        QTest.qWait(100)
        assert bridge.process_service.thread is thread
        bridge.stopSelected()
        until(lambda: not bridge.selected.get("active") and not bridge.selected.get("pending"), 6)
        unexpected_messages = [message for message in messages if "QFontDatabase: Cannot find font directory" not in message]
        assert not unexpected_messages
    finally:
        try:
            if bridge.selected.get("active"):
                bridge.stopSelected()
                until(lambda: not bridge.selected.get("active"), 6)
        finally:
            root.hide()
            bridge.shutdown()
            shiboken6.delete(root)
            shiboken6.delete(engine)
            qInstallMessageHandler(previous_handler)
