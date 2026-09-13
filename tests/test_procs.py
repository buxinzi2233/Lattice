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
from tooldeck.config import ToolConfig
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
    assert running.state == "running"
    assert proc_alive(running.pid)
    stopped = manager.stop_blocking(tool)
    assert stopped.state == "stopped"
    assert not proc_alive(running.pid)


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
    assert manager.status(tool.id).state == "running"
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
