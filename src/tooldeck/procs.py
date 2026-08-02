from __future__ import annotations

import json
import os
import secrets
import shutil
import signal
import subprocess
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from . import paths
from .config import ToolConfig
from .util import proc_alive, proc_group_alive, proc_starttime

if os.name == "nt":
    import msvcrt
else:
    import fcntl


class ProcessError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ToolStatus:
    id: str
    state: str
    pid: int | None = None
    started_at: float | None = None
    exited_at: float | None = None
    exit_code: int | None = None
    message: str | None = None

    @property
    def active(self) -> bool:
        return self.state in {"running", "stopping"}

    @property
    def uptime(self) -> float | None:
        if self.started_at is None:
            return None
        end = self.exited_at if self.exited_at is not None else time.time()
        return max(0.0, end - self.started_at)


class ProcManager:
    def __init__(self, *, max_log_bytes: int = 50 * 1024 * 1024) -> None:
        self.max_log_bytes = max_log_bytes
        self._children: dict[str, tuple[subprocess.Popen[bytes], str]] = {}
        paths.ensure_dirs()

    @staticmethod
    def _timestamp() -> str:
        return datetime.now().astimezone().isoformat(timespec="seconds")

    @contextmanager
    def _lock(self, tool_id: str) -> Iterator[None]:
        lock_path = paths.run_dir() / f"{tool_id}.lock"
        with lock_path.open("a+b") as handle:
            if os.name == "nt":
                handle.seek(0, os.SEEK_END)
                if handle.tell() == 0:
                    handle.write(b"\0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if os.name == "nt":
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _read_state(tool_id: str) -> dict[str, Any] | None:
        try:
            with paths.state_json(tool_id).open("r", encoding="utf-8") as handle:
                state = json.load(handle)
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return None
        return state if isinstance(state, dict) else None

    @staticmethod
    def _write_state(tool_id: str, state: dict[str, Any]) -> None:
        paths.ensure_dirs()
        destination = paths.state_json(tool_id)
        fd, temporary = tempfile.mkstemp(prefix=f".{tool_id}.", suffix=".tmp", dir=destination.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(state, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass

    @classmethod
    def _marker(cls, event: str, detail: str = "") -> bytes:
        suffix = f" {detail}" if detail else ""
        return f"\n--- [{cls._timestamp()}] LATTICE {event}{suffix} ---\n".encode()

    @classmethod
    def _append_marker(cls, tool_id: str, event: str, detail: str = "") -> None:
        try:
            paths.logs_dir().mkdir(parents=True, exist_ok=True)
            with paths.log_file(tool_id).open("ab") as handle:
                handle.write(cls._marker(event, detail))
        except OSError:
            # Process state must remain usable even when an optional marker
            # cannot be appended (for example, a full filesystem).
            return

    def _rotate_log(self, tool_id: str) -> None:
        log_path = paths.log_file(tool_id)
        try:
            oversized = log_path.stat().st_size >= self.max_log_bytes
        except FileNotFoundError:
            return
        if not oversized:
            return
        rotated = log_path.with_suffix(log_path.suffix + ".1")
        try:
            rotated.unlink()
        except FileNotFoundError:
            pass
        log_path.replace(rotated)

    @staticmethod
    def _resolve_shell(shell: str) -> str:
        expanded = os.path.expanduser(shell)
        separators = tuple(separator for separator in (os.path.sep, os.path.altsep) if separator)
        if os.path.isabs(expanded) or any(separator in expanded for separator in separators):
            path = Path(expanded)
            if not path.is_file() or not os.access(path, os.X_OK):
                raise ProcessError(f"Shell 不可执行：{shell}")
            return str(path)
        resolved = shutil.which(expanded)
        if resolved is None:
            raise ProcessError(f"找不到 Shell：{shell}")
        return resolved

    @staticmethod
    def _shell_argv(shell: str, command: str, *, windows: bool | None = None) -> list[str]:
        use_windows = os.name == "nt" if windows is None else windows
        executable = Path(shell).name.casefold()
        if use_windows and executable in {"cmd", "cmd.exe", "command.com"}:
            # The outer quotes preserve an executable path quoted inside the command
            # when cmd.exe applies its /S /C quote-stripping rules.
            return [shell, "/d", "/s", "/c", f'"{command}"']
        if use_windows and executable in {"powershell", "powershell.exe", "pwsh", "pwsh.exe"}:
            return [shell, "-NoLogo", "-NoProfile", "-Command", command]
        return [shell, "-c", command]

    @staticmethod
    def _taskkill_tree(pid: int, *, force: bool) -> bool:
        command = ["taskkill", "/PID", str(pid), "/T"]
        if force:
            command.append("/F")
        completed = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if completed.returncode == 0 or not proc_group_alive(pid):
            return True
        if force:
            action = "强制停止" if force else "停止"
            raise ProcessError(f"Windows 无法{action} PID {pid} 的进程树")
        return False

    def _finish_child(self, tool_id: str, state: dict[str, Any]) -> dict[str, Any]:
        owned = self._children.get(tool_id)
        if owned is None:
            return state
        child, run_id = owned
        return_code = child.poll()
        if return_code is None:
            return state
        self._children.pop(tool_id, None)
        state_run_id = state.get("run_id")
        same_run = state_run_id == run_id if isinstance(state_run_id, str) else state.get("pid") == child.pid
        if not same_run:
            return state
        if state.get("lifecycle") in {"stopped", "exited"}:
            if not isinstance(state.get("exit_code"), int):
                state["exit_code"] = return_code
        else:
            state["leader_exit_code"] = return_code
        self._write_state(tool_id, state)
        return state

    @staticmethod
    def _posix_group_matches(pid: object, pgid: object, starttime: object) -> bool:
        if os.name == "nt" or not isinstance(pid, int) or not isinstance(pgid, int):
            return False
        if not proc_alive(pid, starttime if isinstance(starttime, int) else None):
            return False
        try:
            return os.getpgid(pid) == pgid
        except (ProcessLookupError, PermissionError, OSError):
            return False

    def status(self, tool_id: str) -> ToolStatus:
        with self._lock(tool_id):
            return self._status_unlocked(tool_id)

    def _status_unlocked(self, tool_id: str) -> ToolStatus:
        state = self._read_state(tool_id)
        if not state:
            return ToolStatus(tool_id, "stopped")
        state = self._finish_child(tool_id, state)
        lifecycle = state.get("lifecycle", "running")
        pid = state.get("pid")
        pgid = state.get("pgid")
        started_at = state.get("started_at")
        starttime = state.get("starttime")
        leader_alive = proc_alive(pid, starttime) if isinstance(pid, int) else False
        group_validated = state.get("group_validated") is True
        if (
            lifecycle in {"running", "stopping"}
            and not group_validated
            and self._posix_group_matches(pid, pgid, starttime)
        ):
            # Migrate state written by older ToolDeck versions while the
            # original leader still proves ownership of the process group.
            state["group_validated"] = True
            group_validated = True
            self._write_state(tool_id, state)
        group_alive = (
            proc_group_alive(pgid)
            if (
                lifecycle in {"running", "stopping"}
                and not leader_alive
                and group_validated
                and isinstance(pgid, int)
            )
            else False
        )

        # A very short command can disappear from /proc between poll() and this
        # check. Give the owned Popen one more chance to collect its real code
        # instead of prematurely persisting an "unknown" exit.
        if not leader_alive and not group_alive and tool_id in self._children:
            state = self._finish_child(tool_id, state)
            if tool_id in self._children:
                current = "stopping" if lifecycle == "stopping" else "running"
                return ToolStatus(tool_id, current, pid=pid, started_at=started_at)
            lifecycle = state.get("lifecycle", lifecycle)
            group_alive = proc_group_alive(pgid) if group_validated and isinstance(pgid, int) else False

        if lifecycle in {"running", "stopping"} and (leader_alive or group_alive):
            current = "stopping" if lifecycle == "stopping" else "running"
            return ToolStatus(tool_id, current, pid=pid, started_at=started_at)

        if lifecycle in {"running", "stopping"}:
            lifecycle = "stopped" if lifecycle == "stopping" else "exited"
            leader_code = state.pop("leader_exit_code", None)
            state.update(
                lifecycle=lifecycle,
                exited_at=state.get("exited_at", time.time()),
                exit_code=leader_code if isinstance(leader_code, int) else state.get("exit_code"),
            )
            state.pop("stop_deadline", None)
            state.pop("group_validated", None)
            self._write_state(tool_id, state)
            detail = f"code={leader_code}" if isinstance(leader_code, int) else "code=unknown"
            self._append_marker(tool_id, "STOPPED" if lifecycle == "stopped" else "EXIT", detail)

        return ToolStatus(
            tool_id,
            lifecycle if lifecycle in {"stopped", "exited"} else "exited",
            pid=pid if isinstance(pid, int) else None,
            started_at=started_at if isinstance(started_at, (int, float)) else None,
            exited_at=state.get("exited_at"),
            exit_code=state.get("exit_code") if isinstance(state.get("exit_code"), int) else None,
            message=state.get("message") if isinstance(state.get("message"), str) else None,
        )

    def start(self, tool: ToolConfig) -> ToolStatus:
        with self._lock(tool.id):
            current = self._status_unlocked(tool.id)
            if current.active:
                raise ProcessError(f"{tool.name} 已在运行（PID {current.pid}）")
            cwd = Path(tool.cwd).expanduser()
            if not cwd.is_dir():
                raise ProcessError(f"工作目录不存在：{cwd}")
            shell = self._resolve_shell(tool.shell)
            try:
                self._rotate_log(tool.id)
                paths.logs_dir().mkdir(parents=True, exist_ok=True)
                log_path = paths.log_file(tool.id)
                with log_path.open("ab", buffering=0) as output:
                    output.write(self._marker("START", f"name={tool.name}"))
                    platform_options: dict[str, Any]
                    if os.name == "nt":
                        platform_options = {
                            "creationflags": (
                                getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                                | getattr(subprocess, "CREATE_NO_WINDOW", 0)
                            )
                        }
                    else:
                        platform_options = {"start_new_session": True}
                    child = subprocess.Popen(
                        self._shell_argv(shell, tool.cmd),
                        cwd=cwd,
                        env={**os.environ, **tool.env},
                        stdin=subprocess.DEVNULL,
                        stdout=output,
                        stderr=subprocess.STDOUT,
                        close_fds=True,
                        **platform_options,
                    )
            except (OSError, ValueError) as exc:
                raise ProcessError(f"启动失败：{exc}") from exc
            started_at = time.time()
            starttime = proc_starttime(child.pid)
            group_validated = self._posix_group_matches(child.pid, child.pid, starttime)
            run_id = secrets.token_hex(16)
            state: dict[str, Any] = {
                "pid": child.pid,
                "pgid": child.pid,
                "starttime": starttime,
                "started_at": started_at,
                "lifecycle": "running",
                "run_id": run_id,
            }
            if group_validated:
                state["group_validated"] = True
            self._children[tool.id] = (child, run_id)
            self._write_state(tool.id, state)
            return self._status_unlocked(tool.id)

    @staticmethod
    def _signal_number(name: str) -> signal.Signals:
        return signal.Signals[getattr(signal, f"SIG{name}").name]

    def stop_begin(self, tool: ToolConfig) -> ToolStatus:
        with self._lock(tool.id):
            current = self._status_unlocked(tool.id)
            if not current.active:
                return current
            state = self._read_state(tool.id)
            if state is None or current.pid is None:
                return ToolStatus(tool.id, "stopped")
            if current.state == "stopping":
                return current
            pgid = state.get("pgid")
            if os.name != "nt":
                if not isinstance(pgid, int) or pgid <= 1 or state.get("group_validated") is not True:
                    raise ProcessError(f"无法验证 {tool.name} 的进程组，已拒绝发送停止信号")
                signal_target = pgid
            else:
                signal_target = current.pid
            state["lifecycle"] = "stopping"
            state["stop_deadline"] = time.time() + tool.stop_timeout
            state["stop_signal"] = tool.stop_signal
            if os.name == "nt":
                state["group_validated"] = True
            self._write_state(tool.id, state)
            try:
                if os.name == "nt":
                    self._taskkill_tree(signal_target, force=tool.stop_signal == "KILL")
                else:
                    os.killpg(signal_target, self._signal_number(tool.stop_signal))
            except ProcessLookupError:
                pass
            except (PermissionError, ProcessError) as exc:
                state["lifecycle"] = "running"
                state.pop("stop_deadline", None)
                self._write_state(tool.id, state)
                if isinstance(exc, ProcessError):
                    raise
                raise ProcessError(f"无权停止 PID {signal_target}") from exc
            detail = "taskkill=/T" if os.name == "nt" else f"pgid={signal_target} signal=SIG{tool.stop_signal}"
            self._append_marker(tool.id, "STOP", detail)
            return self._status_unlocked(tool.id)

    def tick(self) -> None:
        paths.ensure_dirs()
        for state_path in paths.run_dir().glob("*.json"):
            tool_id = state_path.stem
            with self._lock(tool_id):
                state = self._read_state(tool_id)
                if not state:
                    continue
                current = self._status_unlocked(tool_id)
                if current.state != "stopping" or current.pid is None:
                    continue
                state = self._read_state(tool_id) or state
                deadline = state.get("stop_deadline")
                if not isinstance(deadline, (int, float)) or time.time() < deadline:
                    continue
                signal_target = current.pid if os.name == "nt" else state.get("pgid")
                if not isinstance(signal_target, int) or signal_target <= 1:
                    state["message"] = "进程组标识无效，无法强制停止"
                    self._write_state(tool_id, state)
                    continue
                try:
                    if os.name == "nt":
                        self._taskkill_tree(signal_target, force=True)
                        self._append_marker(tool_id, "KILL", "taskkill=/F timeout=expired")
                    else:
                        os.killpg(signal_target, signal.SIGKILL)
                        self._append_marker(tool_id, "KILL", f"pgid={signal_target} signal=SIGKILL timeout=expired")
                except ProcessLookupError:
                    pass
                except (PermissionError, ProcessError):
                    state["message"] = f"无权强制停止 PID {signal_target}"
                state["stop_deadline"] = time.time() + 1.0
                self._write_state(tool_id, state)
                self._status_unlocked(tool_id)

    def stop_blocking(self, tool: ToolConfig) -> ToolStatus:
        current = self.stop_begin(tool)
        if not current.active:
            return current
        hard_deadline = time.time() + tool.stop_timeout + 5.0
        while time.time() < hard_deadline:
            self.tick()
            current = self.status(tool.id)
            if not current.active:
                return current
            time.sleep(0.05)
        raise ProcessError(f"停止 {tool.name} 超时")

    def stop_all_begin(self, tools: dict[str, ToolConfig]) -> list[str]:
        failures: list[str] = []
        for tool in tools.values():
            try:
                self.stop_begin(tool)
            except ProcessError as exc:
                failures.append(f"{tool.name}: {exc}")
        return failures
