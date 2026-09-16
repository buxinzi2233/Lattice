"""Exercise shared application behavior with real processes, files and sockets."""
from __future__ import annotations

import json
import os
import shlex
import socket
import subprocess
import sys
import threading
import time
import venv
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest

from tooldeck import paths
from tooldeck.application import ToolDeckApplication
from tooldeck.catalog import ToolCatalog
from tooldeck.cli import main
from tooldeck.config import ConfigError, LaunchConfig, ReadinessConfig, ToolConfig, load_file, save
from tooldeck.gui.bridge import AppBridge
from tooldeck.gui.log_model import LogLineModel
from tooldeck.launchers import analyze_launch, preflight_tool
from tooldeck.layout import LayoutError
from tooldeck.procs import ProcManager
from tooldeck.storage import FileLockCancelled, FileLockTimeout, exclusive_file_lock
from tooldeck.tailer import LogTailer


def until(predicate, seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while not predicate() and time.monotonic() < deadline:
        QTest.qWait(10)
        time.sleep(0.005)
    assert predicate(), "The real operation did not finish before its deadline"


def python_command(source: str) -> str:
    argv = [sys.executable, "-u", "-X", "utf8", "-c", source]
    return subprocess.list2cmdline(argv) if os.name == "nt" else shlex.join(argv)


@pytest.fixture
def delayed_http():
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(20)
    listener.settimeout(0.05)
    shutdown = threading.Event()
    accepted = threading.Event()
    release = threading.Event()
    connections: list[socket.socket] = []

    def serve() -> None:
        while not shutdown.is_set():
            try:
                connection, _address = listener.accept()
                connections.append(connection)
                accepted.set()
            except TimeoutError:
                pass
            if release.is_set():
                while connections:
                    connection = connections.pop()
                    try:
                        connection.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
                    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                        pass
                    finally:
                        connection.close()
    thread = threading.Thread(target=serve)
    thread.start()
    try:
        yield f"http://127.0.0.1:{listener.getsockname()[1]}/", accepted, release
    finally:
        shutdown.set()
        thread.join(2)
        listener.close()
        for connection in connections:
            connection.close()
        assert not thread.is_alive()


def test_real_project_venv_is_independent_of_shared_base_python(tmp_path):
    environment = tmp_path / "项目 环境" / ".venv"
    venv.EnvBuilder(with_pip=False, symlinks=os.name != "nt").create(environment)
    interpreter = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    source = environment.parent / "main.py"
    source.write_text("import sys; print(sys.prefix)\n", encoding="utf-8")
    analysis = analyze_launch(source)
    assert not analysis.blocking
    assert analysis.plan is not None and analysis.plan.setup is None
    tool = ToolConfig("venv", "Venv", analysis.plan.command, str(source.parent), launch=analysis.plan.launch_config())
    assert not preflight_tool(tool).blocking
    result = subprocess.run([str(interpreter), "-X", "utf8", str(source)], check=True, capture_output=True, text=True, encoding="utf-8")
    assert Path(result.stdout.strip()).resolve() == environment.resolve()


def test_cli_edit_changes_the_command_actually_executed(tmp_path):
    source = tmp_path / "old script.py"
    source.write_text("print('OLD_COMMAND')\n", encoding="utf-8")
    launch = LaunchConfig("argv", "executable", str(source), (sys.executable, str(source)))
    tool = ToolConfig("edited", "Edited", "old display", str(tmp_path), launch=launch)
    save(tool)
    command = python_command("print('NEW_COMMAND')")
    assert main(["edit", tool.id, "--cmd", command]) == 0
    updated = load_file(paths.tool_toml(tool.id))
    assert updated.cmd == command and updated.launch is None
    application = ToolDeckApplication()
    try:
        application.start(tool.id)
        until(lambda: not application.runtime.status(tool.id).active, 5)
        lines = paths.log_file(tool.id).read_text(encoding="utf-8").splitlines()
        assert "NEW_COMMAND" in lines
        assert "OLD_COMMAND" not in lines
    finally:
        application.runtime.stop_blocking(updated)
        application.runtime.close()


def test_slow_readiness_does_not_block_gui_or_stop_requests(qapp, tmp_path, delayed_http):
    url, accepted, _release = delayed_http
    tools = [
        ToolConfig(f"slow{index}", f"Slow {index}", python_command("import time; time.sleep(60)"), str(tmp_path),
                   stop_timeout=0.1, readiness=ReadinessConfig("http", 0.0, 30.0, url, None))
        for index in range(4)
    ]
    for tool in tools:
        save(tool)
    bridge = AppBridge()
    ticks: list[float] = []
    heartbeat = QTimer()
    heartbeat.setInterval(10)
    heartbeat.timeout.connect(lambda: ticks.append(time.monotonic()))
    heartbeat.start()
    try:
        until(lambda: len(bridge._statuses) == len(tools), 4)
        for tool in tools:
            bridge.selectTool(tool.id)
            bridge.startSelected()
        until(lambda: accepted.is_set() and all(status.active for status in bridge._statuses.values()), 5)
        before = time.monotonic()
        for _ in range(10):
            bridge.refreshStatus()
        until(lambda: time.monotonic() - before >= 0.9, 2)
        bridge.stopAll()
        until(lambda: not bridge.process_service.pending and all(not status.active for status in bridge._statuses.values()), 4)
        assert time.monotonic() - before < 4
        assert len(ticks) > 30
        assert max(right - left for left, right in zip(ticks, ticks[1:])) < 0.5
    finally:
        heartbeat.stop()
        bridge.shutdown()
        cleanup = ProcManager()
        try:
            for tool in tools:
                cleanup.stop_blocking(tool)
        finally:
            cleanup.close()


def test_readiness_result_cannot_mark_a_new_run_ready(tmp_path, delayed_http):
    url, accepted, release = delayed_http
    manager = ProcManager()
    first = ToolConfig("replace", "Replace", python_command("import time; time.sleep(60)"), str(tmp_path),
                       stop_timeout=0.1, readiness=ReadinessConfig("http", 0.0, 10.0, url, None))
    second = ToolConfig("replace", "Replace", first.cmd, first.cwd, stop_timeout=0.1,
                        readiness=ReadinessConfig("process", 30.0, 60.0, "", None))
    try:
        manager.start(first)
        assert accepted.wait(2)
        old_run = json.loads(paths.state_json(first.id).read_text(encoding="utf-8"))["run_id"]
        manager.stop_blocking(first)
        manager.start(second)
        release.set()
        future = manager._probes[first.id]
        future.result(timeout=3)
        state = json.loads(paths.state_json(second.id).read_text(encoding="utf-8"))
        assert state["run_id"] != old_run
        assert state["readiness_state"] == "starting"
    finally:
        manager.stop_blocking(second)
        manager.close()


def test_async_save_reports_persistence_before_success_and_start(qapp, tmp_path):
    bridge = AppBridge()
    saved: list[tuple[str, bool]] = []
    bridge.toolSaveFinished.connect(lambda tool_id, success: saved.append((tool_id, success)))
    try:
        until(lambda: bridge._catalog_ready, 3)
        draft = bridge.newToolDraft()
        draft.update(id="saved", name="Saved", cwd=str(tmp_path), cmd=python_command("print('SAVED_THEN_STARTED')"), rawMode=True)
        assert bridge.saveAndStartToolDraft(draft)
        assert saved == []
        until(lambda: saved == [("saved", True)], 4)
        assert load_file(paths.tool_toml("saved")).name == "Saved"
        until(lambda: "SAVED_THEN_STARTED" in bridge.logText, 5)
        draft.update(originalId="saved", cwd=str(tmp_path / "missing"))
        assert bridge.saveToolDraft(draft)
        until(lambda: len(saved) == 2, 4)
        assert saved[-1] == ("saved", False)
        assert load_file(paths.tool_toml("saved")).cwd == str(tmp_path)
    finally:
        bridge.shutdown()


def test_corrupt_layout_keeps_tools_readable_but_blocks_mutations(tmp_path):
    tool = ToolConfig("kept", "Kept", "echo ready", str(tmp_path))
    save(tool)
    paths.layout_json().write_text("{broken", encoding="utf-8")
    catalog = ToolCatalog()
    snapshot = catalog.refresh()
    assert "kept" in snapshot.tools and snapshot.layout_error
    with pytest.raises(LayoutError):
        catalog.save_tool(tool, overwrite=True)
    assert paths.layout_json().read_text(encoding="utf-8") == "{broken"


def test_corrupt_process_state_is_visible_in_the_attention_filter(qapp, tmp_path):
    save(ToolConfig("broken-state", "Broken state", "echo ready", str(tmp_path)))
    paths.state_json("broken-state").write_text("{broken", encoding="utf-8")
    bridge = AppBridge()
    try:
        until(lambda: bridge.selected.get("state") == "error", 3)
        bridge.setFilterMode("exited")
        assert bridge.model.exitedCount == 1
        assert bridge.model.visibleCount == 1
        assert bridge.selected["stateLabel"] == "状态异常"
    finally:
        bridge.shutdown()


def test_atomic_create_does_not_replace_a_competing_writer(tmp_path):
    barrier = threading.Barrier(2)
    def create(name: str) -> str:
        barrier.wait(timeout=2)
        try:
            save(ToolConfig("race", name, "echo ready", str(tmp_path)), overwrite=False)
            return name
        except ConfigError:
            return "exists"
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(create, name) for name in ("first", "second")]
        results = [future.result(timeout=3) for future in futures]
    assert results.count("exists") == 1
    assert load_file(paths.tool_toml("race")).name in results


def test_catalog_lock_wait_can_be_cancelled_without_overwriting(tmp_path):
    path = tmp_path / "catalog.lock"
    with exclusive_file_lock(path, 1.0, None):
        with pytest.raises(FileLockTimeout):
            with exclusive_file_lock(path, 0.05, None):
                pytest.fail("A second writer acquired the exclusive lock")
        cancelled = threading.Event()
        cancelled.set()
        with pytest.raises(FileLockCancelled):
            with exclusive_file_lock(path, 1.0, cancelled):
                pytest.fail("A cancelled writer acquired the exclusive lock")


def test_live_log_preview_stays_bounded_and_resets_on_rotation(qapp, tmp_path):
    path = tmp_path / "live.log"
    path.write_bytes(b"progress 10%")
    tailer = LogTailer(path)
    model = LogLineModel()
    model.append_batch(tailer.read_batch())
    assert model.get(0)["logMessage"] == "progress 10%"
    with path.open("ab") as output:
        output.write(b"\rprogress 20%\n" + b"x" * (1024 * 1024))
    while tailer.offset < path.stat().st_size:
        before = tailer.offset
        model.append_batch(tailer.read_chunk(64 * 1024))
        assert tailer.offset - before <= 64 * 1024
        assert model.count <= 2000
        assert sum(len(value) for row in range(model.count) for value in model.get(row).values()) <= 256 * 1024
    assert all("progress 10%" not in model.get(row)["logMessage"] for row in range(model.count))
    replacement = tmp_path / "next.log"
    replacement.write_text("new run\n", encoding="utf-8")
    os.replace(replacement, path)
    model.append_batch(tailer.read_batch())
    assert model.count == 1
    assert model.get(0)["logMessage"] == "new run"
