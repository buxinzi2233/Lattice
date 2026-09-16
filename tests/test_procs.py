from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import tempfile
import time

import pytest

from tooldeck import paths
from tooldeck.config import ReadinessConfig, ToolConfig
from tooldeck.procs import ProcManager, ProcessError
from tooldeck.util import proc_alive, proc_starttime


def python_command(code: str) -> str:
    parts = [sys.executable, "-c", code]
    return subprocess.list2cmdline(parts) if os.name == "nt" else shlex.join(parts)


def wait_for(manager, tool_id, expected, timeout=3):
    deadline = time.time() + timeout
    while time.time() < deadline:
        manager.tick()
        status = manager.status(tool_id)
        if status.state in expected:
            return status
        time.sleep(0.03)
    raise AssertionError(f"{tool_id} did not reach {expected}: {manager.status(tool_id)}")


def test_start_and_stop_sleep():
    manager = ProcManager()
    tool = ToolConfig(
        "sleeper",
        "Sleeper",
        python_command("import time; time.sleep(60)"),
        tempfile.gettempdir(),
        stop_timeout=0.2,
    )
    running = manager.start(tool)
    assert running.state == "starting"
    assert proc_alive(running.pid)
    stopped = manager.stop_blocking(tool)
    assert stopped.state == "stopped"
    assert not proc_alive(running.pid)


def test_start_rolls_back_child_when_state_persistence_fails(monkeypatch):
    manager = ProcManager()
    children: list[subprocess.Popen] = []
    real_popen = subprocess.Popen

    def capture_child(*args, **kwargs):
        child = real_popen(*args, **kwargs)
        if "cwd" in kwargs:
            children.append(child)
        return child

    def fail_state_write(_tool_id, _state):
        raise OSError("state disk unavailable")

    monkeypatch.setattr("tooldeck.procs.subprocess.Popen", capture_child)
    monkeypatch.setattr(manager, "_write_state", fail_state_write)
    tool = ToolConfig(
        "state-write-failure",
        "State write failure",
        python_command("import time; time.sleep(60)"),
        tempfile.gettempdir(),
    )

    with pytest.raises(ProcessError, match="启动状态无法保存"):
        manager.start(tool)

    assert len(children) == 1
    assert children[0].poll() is not None
    assert tool.id not in manager._children
    assert not proc_alive(children[0].pid)
    assert "START-ROLLBACK" in paths.log_file(tool.id).read_text(errors="replace")


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group rollback semantics")
def test_start_state_failure_rolls_back_spawned_descendants(monkeypatch):
    manager = ProcManager()
    descendant_pid: list[int] = []
    child_code = "import time; time.sleep(60)"
    parent_code = (
        "import subprocess, sys, time; "
        f"child = subprocess.Popen([sys.executable, '-c', {child_code!r}]); "
        "print(child.pid, flush=True); time.sleep(60)"
    )
    tool = ToolConfig(
        "state-tree-failure",
        "State tree failure",
        python_command(parent_code),
        tempfile.gettempdir(),
    )

    def fail_after_descendant_started(_tool_id, _state):
        deadline = time.time() + 2
        while time.time() < deadline:
            text = paths.log_file(tool.id).read_text(errors="replace")
            found = next((int(line) for line in text.splitlines() if line.isdigit()), None)
            if found is not None:
                descendant_pid.append(found)
                break
            time.sleep(0.01)
        raise OSError("state disk unavailable")

    monkeypatch.setattr(manager, "_write_state", fail_after_descendant_started)
    with pytest.raises(ProcessError, match="启动状态无法保存"):
        manager.start(tool)

    assert descendant_pid
    assert not proc_alive(descendant_pid[0])


def test_corrupt_state_file_blocks_a_potential_duplicate_start(monkeypatch):
    manager = ProcManager()
    tool = ToolConfig("corrupt-state", "Corrupt state", python_command("pass"), tempfile.gettempdir())
    paths.state_json(tool.id).write_text("{not json", encoding="utf-8")
    launched = []
    monkeypatch.setattr("tooldeck.procs.subprocess.Popen", lambda *_args, **_kwargs: launched.append(True))

    with pytest.raises(ProcessError, match="状态文件损坏.*拒绝重复启动"):
        manager.start(tool)

    assert launched == []


def test_exit_code_is_recorded():
    manager = ProcManager()
    tool = ToolConfig(
        "fail",
        "Failure",
        python_command("import sys; sys.exit(3)"),
        tempfile.gettempdir(),
    )
    manager.start(tool)
    status = wait_for(manager, tool.id, {"exited"})
    assert status.exit_code == 3
    assert "code=3" in paths.log_file(tool.id).read_text(errors="replace")


def test_process_readiness_moves_from_starting_to_running():
    manager = ProcManager()
    tool = ToolConfig(
        "readiness-process",
        "Readiness process",
        python_command("import time; time.sleep(60)"),
        tempfile.gettempdir(),
        readiness=ReadinessConfig("process", 0.05, 2),
        stop_timeout=0.1,
    )
    started = manager.start(tool)
    try:
        assert started.state in {"starting", "running"}
        ready = wait_for(manager, tool.id, {"running"}, timeout=1)
        assert ready.message == "已就绪"
    finally:
        manager.stop_blocking(tool)


def test_quick_exit_reports_code_and_log_tail_without_ready_state():
    manager = ProcManager()
    tool = ToolConfig(
        "startup-failure",
        "Startup failure",
        python_command("import sys; print('dependency missing', flush=True); sys.exit(7)"),
        tempfile.gettempdir(),
        readiness=ReadinessConfig("process", 1, 2),
    )

    started = manager.start(tool)
    assert started.state in {"starting", "exited"}
    exited = started if started.state == "exited" else wait_for(manager, tool.id, {"exited"})

    assert exited.exit_code == 7
    assert "退出码 7" in (exited.message or "")
    assert "dependency missing" in (exited.message or "")


def test_http_timeout_keeps_process_and_recovers_when_service_becomes_ready(monkeypatch):
    port = 18765
    probe_started = time.time()
    monkeypatch.setattr(ProcManager, "_probe_http", staticmethod(lambda _url: time.time() - probe_started >= 0.35))
    manager = ProcManager()
    tool = ToolConfig(
        "delayed-http",
        "Delayed HTTP",
        python_command("import time; time.sleep(60)"),
        tempfile.gettempdir(),
        readiness=ReadinessConfig("http", 0, 0.1, f"http://127.0.0.1:{port}/"),
        stop_timeout=0.1,
    )
    manager.start(tool)
    try:
        timed_out = wait_for(manager, tool.id, {"unready"}, timeout=1)
        assert timed_out.active
        assert proc_alive(timed_out.pid)
        ready = wait_for(manager, tool.id, {"running"}, timeout=7)
        assert ready.active
        assert ready.ready_url == f"http://127.0.0.1:{port}/"
    finally:
        manager.stop_blocking(tool)


def test_auto_readiness_waits_for_late_log_url_before_process_fallback(monkeypatch):
    detected_after = time.time() + 0.25
    local_url = "http://127.0.0.1:18766/"
    monkeypatch.setattr(
        ProcManager,
        "_detected_local_url",
        staticmethod(lambda _tool_id, _offset=0: local_url if time.time() >= detected_after else ""),
    )
    monkeypatch.setattr(ProcManager, "_probe_http", staticmethod(lambda _url: True))
    manager = ProcManager()
    tool = ToolConfig(
        "auto-late-url",
        "Auto late URL",
        python_command("import time; time.sleep(60)"),
        tempfile.gettempdir(),
        readiness=ReadinessConfig("auto", 0.05, 2),
        stop_timeout=0.1,
    )

    manager.start(tool)
    try:
        time.sleep(0.12)
        assert manager.status(tool.id).state == "starting"
        ready = wait_for(manager, tool.id, {"running"}, timeout=2)
        assert ready.ready_url == local_url
    finally:
        manager.stop_blocking(tool)


def test_log_url_detection_ignores_remote_hosts_and_normalizes_bind_all(tmp_path):
    manager = ProcManager()
    paths.log_file("urls").write_text(
        "remote https://example.com:8000\nlocal http://0.0.0.0:8188/ui\n",
        encoding="utf-8",
    )

    assert manager._detected_local_url("urls") == "http://127.0.0.1:8188/ui"

    paths.log_file("urls").write_text(
        "lookalike http://localhost.evil.example:8188/\nremote https://example.com:8000/\n",
        encoding="utf-8",
    )
    assert manager._detected_local_url("urls") == ""


def test_log_url_detection_ignores_urls_before_current_run_offset():
    manager = ProcManager()
    log_path = paths.log_file("current-run-url")
    log_path.write_text("old http://127.0.0.1:8001/\n", encoding="utf-8")
    current_run_offset = log_path.stat().st_size

    assert manager._detected_local_url("current-run-url", current_run_offset) == ""

    with log_path.open("a", encoding="utf-8") as handle:
        handle.write("new http://0.0.0.0:8002/\n")
    assert manager._detected_local_url("current-run-url", current_run_offset) == "http://127.0.0.1:8002/"


def test_local_url_normalization_preserves_path_and_accepts_loopback_range():
    assert ProcManager._normalized_local_url(
        "http://0.0.0.0:8188/path/0.0.0.0?next=0.0.0.0"
    ) == "http://127.0.0.1:8188/path/0.0.0.0?next=0.0.0.0"
    assert ProcManager._normalized_local_url("http://127.0.0.2:8000/") == "http://127.0.0.2:8000/"
    assert ProcManager._normalized_local_url("https://example.com/") == ""
    assert ProcManager._normalized_local_url("http://127.0.0.1:99999/") == ""


def test_tcp_readiness_probes_only_configured_loopback_port(monkeypatch):
    probed: list[int] = []
    monkeypatch.setattr(ProcManager, "_probe_tcp", staticmethod(lambda port: probed.append(port) or True))
    monkeypatch.setattr(ProcManager, "_probe_http", staticmethod(lambda _url: False))
    manager = ProcManager()
    tool = ToolConfig(
        "tcp-ready",
        "TCP ready",
        python_command("import time; time.sleep(60)"),
        tempfile.gettempdir(),
        readiness=ReadinessConfig("tcp", 0.05, 2, "http://127.0.0.1:19999/", 18767),
        stop_timeout=0.1,
    )

    try:
        assert manager.start(tool).state == "starting"
        ready = wait_for(manager, tool.id, {"running"}, timeout=3)
        assert ready.active
        assert probed == [18767]
    finally:
        manager.stop_blocking(tool)


def test_stop_kills_whole_process_group():
    manager = ProcManager()
    child_code = "import time; time.sleep(60)"
    parent_code = (
        "import subprocess, sys; "
        f"child = subprocess.Popen([sys.executable, '-c', {child_code!r}]); "
        "print(child.pid, flush=True); child.wait()"
    )
    tool = ToolConfig(
        "group",
        "Group",
        python_command(parent_code),
        tempfile.gettempdir(),
        stop_timeout=0.2,
    )
    parent = manager.start(tool)
    deadline = time.time() + 2
    child_pid = None
    while time.time() < deadline and child_pid is None:
        text = paths.log_file(tool.id).read_text(errors="replace")
        for line in text.splitlines():
            if line.isdigit():
                child_pid = int(line)
        time.sleep(0.02)
    assert child_pid and proc_alive(child_pid)
    manager.stop_blocking(tool)
    assert not proc_alive(parent.pid)
    assert not proc_alive(child_pid)


@pytest.mark.skipif(os.name == "nt", reason="POSIX signal escalation semantics")
def test_ignored_term_escalates_to_kill():
    manager = ProcManager()
    tool = ToolConfig(
        "stubborn",
        "Stubborn",
        "trap '' TERM; echo ready; while true; do sleep 1; done",
        tempfile.gettempdir(),
        stop_timeout=0.1,
    )
    running = manager.start(tool)
    time.sleep(0.08)
    manager.stop_blocking(tool)
    assert not proc_alive(running.pid)
    assert "LATTICE KILL" in paths.log_file(tool.id).read_text(errors="replace")


@pytest.mark.skipif(os.name == "nt", reason="POSIX orphaned process-group semantics")
def test_stop_waits_for_surviving_group_child():
    manager = ProcManager()
    tool = ToolConfig(
        "orphan-group",
        "Orphan group",
        "trap 'exit 0' TERM; sh -c \"trap '' TERM; while true; do sleep 1; done\" & child=$!; echo $child; wait",
        tempfile.gettempdir(),
        stop_timeout=0.1,
    )
    manager.start(tool)
    deadline = time.time() + 2
    child_pid = None
    while time.time() < deadline and child_pid is None:
        text = paths.log_file(tool.id).read_text(errors="replace")
        child_pid = next((int(line) for line in text.splitlines() if line.isdigit()), None)
        time.sleep(0.02)
    assert child_pid and proc_alive(child_pid)
    manager.stop_blocking(tool)
    assert not proc_alive(child_pid)
    assert "LATTICE KILL" in paths.log_file(tool.id).read_text(errors="replace")


@pytest.mark.skipif(os.name == "nt", reason="POSIX orphaned process-group semantics")
def test_surviving_group_blocks_duplicate_start():
    manager = ProcManager()
    child_code = "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)"
    parent_code = (
        "import subprocess, sys; "
        f"child = subprocess.Popen([sys.executable, '-c', {child_code!r}]); "
        "print(child.pid, flush=True)"
    )
    tool = ToolConfig(
        "surviving-group",
        "Surviving group",
        python_command(parent_code),
        tempfile.gettempdir(),
        stop_timeout=0.1,
    )
    leader = manager.start(tool)
    deadline = time.time() + 2
    child_pid = None
    while time.time() < deadline:
        text = paths.log_file(tool.id).read_text(errors="replace")
        child_pid = next((int(line) for line in text.splitlines() if line.isdigit()), child_pid)
        manager.status(tool.id)
        if child_pid is not None and not proc_alive(leader.pid):
            break
        time.sleep(0.02)

    assert child_pid and proc_alive(child_pid)
    assert not proc_alive(leader.pid)
    assert manager.status(tool.id).active
    with pytest.raises(ProcessError, match="已在运行"):
        manager.start(tool)

    manager.stop_blocking(tool)
    assert not proc_alive(child_pid)


def test_new_manager_can_reattach_and_stop():
    owner = ProcManager()
    tool = ToolConfig(
        "reattach",
        "Reattach",
        python_command("import time; time.sleep(60)"),
        tempfile.gettempdir(),
        stop_timeout=0.1,
    )
    running = owner.start(tool)
    reattached = ProcManager()
    assert reattached.status(tool.id).pid == running.pid
    assert reattached.stop_blocking(tool).state == "stopped"
    owner.status(tool.id)


@pytest.mark.skipif(os.name == "nt", reason="POSIX PID and process-group semantics")
def test_stale_pid_is_never_signalled(monkeypatch):
    manager = ProcManager()
    state = {
        "pid": os.getpid(),
        "pgid": os.getpgrp(),
        "starttime": 1,
        "started_at": time.time(),
        "lifecycle": "running",
    }
    paths.ensure_dirs()
    paths.state_json("stale").write_text(json.dumps(state), encoding="utf-8")
    called = []
    monkeypatch.setattr(os, "killpg", lambda *args: called.append(args))
    monkeypatch.setattr("tooldeck.procs.proc_group_alive", lambda _pgid: True)
    tool = ToolConfig("stale", "Stale", python_command("pass"), tempfile.gettempdir())
    assert manager.stop_begin(tool).state == "exited"
    assert called == []


def test_finished_child_cannot_overwrite_a_new_run_state():
    manager = ProcManager()

    class FinishedChild:
        pid = 12345

        @staticmethod
        def poll():
            return 0

    state = {
        "pid": os.getpid(),
        "pgid": os.getpid(),
        "starttime": proc_starttime(os.getpid()),
        "started_at": time.time(),
        "lifecycle": "running",
        "run_id": "new-run",
    }
    paths.ensure_dirs()
    paths.state_json("state-race").write_text(json.dumps(state), encoding="utf-8")
    manager._children["state-race"] = (FinishedChild(), "old-run")  # type: ignore[assignment]

    assert manager.status("state-race").state == "running"
    persisted = json.loads(paths.state_json("state-race").read_text(encoding="utf-8"))
    assert persisted["run_id"] == "new-run"
    assert persisted["readiness_state"] == "ready"
    assert "leader_exit_code" not in persisted
    assert "state-race" not in manager._children


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group targeting")
def test_stop_signals_saved_process_group_instead_of_display_pid(monkeypatch):
    manager = ProcManager()
    target_pgid = 424242
    state = {
        "pid": os.getpid(),
        "pgid": target_pgid,
        "starttime": proc_starttime(os.getpid()),
        "started_at": time.time(),
        "lifecycle": "running",
        "group_validated": True,
    }
    paths.ensure_dirs()
    paths.state_json("saved-pgid").write_text(json.dumps(state), encoding="utf-8")
    calls = []
    monkeypatch.setattr("tooldeck.procs.proc_group_alive", lambda pgid: pgid == target_pgid)
    monkeypatch.setattr(os, "killpg", lambda *args: calls.append(args))
    tool = ToolConfig("saved-pgid", "Saved PGID", python_command("pass"), tempfile.gettempdir())

    assert manager.stop_begin(tool).state == "stopping"
    assert calls[0][0] == target_pgid


def test_log_rotation():
    manager = ProcManager(max_log_bytes=8)
    paths.ensure_dirs()
    paths.log_file("rotate").write_text("0123456789", encoding="utf-8")
    tool = ToolConfig("rotate", "Rotate", python_command("pass"), tempfile.gettempdir())
    manager.start(tool)
    wait_for(manager, tool.id, {"exited"})
    assert paths.log_file("rotate").with_suffix(".log.1").read_text() == "0123456789"


def test_process_identity_rejects_wrong_start_time():
    starttime = proc_starttime(os.getpid())
    assert starttime is not None
    assert proc_alive(os.getpid(), starttime)
    assert not proc_alive(os.getpid(), starttime + 1)


def test_windows_shell_argv_and_taskkill_command(monkeypatch):
    assert ProcManager._shell_argv("cmd.exe", "echo ready", windows=True) == [
        "cmd.exe",
        "/d",
        "/c",
        "echo ready",
    ]
    assert ProcManager._launch_spec("cmd.exe", '"C:\\Python312\\python.exe" -V', windows=True) == (
        '"C:\\Python312\\python.exe" -V',
        {"shell": True, "executable": "cmd.exe"},
    )
    assert ProcManager._shell_argv("powershell.exe", "Get-Date", windows=True) == [
        "powershell.exe",
        "-NoLogo",
        "-NoProfile",
        "-Command",
        "Get-Date",
    ]

    calls = []

    class Result:
        returncode = 0

    monkeypatch.setattr(subprocess, "run", lambda command, **kwargs: calls.append((command, kwargs)) or Result())
    assert ProcManager._taskkill_tree(4321, force=True)
    assert calls[0][0] == ["taskkill", "/PID", "4321", "/T", "/F"]


def test_windows_taskkill_failure_is_reported(monkeypatch):
    class Result:
        returncode = 1
        stdout = b""
        stderr = b"Access denied"

    monkeypatch.setattr(subprocess, "run", lambda *_args, **_kwargs: Result())
    monkeypatch.setattr("tooldeck.procs.proc_group_alive", lambda _pid: True)
    assert not ProcManager._taskkill_tree(4321, force=False)
    with pytest.raises(ProcessError, match="Windows 无法强制停止"):
        ProcManager._taskkill_tree(4321, force=True)
