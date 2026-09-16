from __future__ import annotations

import ipaddress
import json
import logging
import math
import errno
import os
import re
import secrets
import shlex
import shutil
import signal
import socket
import subprocess
import time
from threading import Event, Lock

import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Literal, TypedDict, cast

from . import paths
from .config import ToolConfig
from .storage import FileLockTimeout, atomic_write_text, exclusive_file_lock
from .util import active_posix_groups, proc_alive, proc_group_alive, proc_starttime, strip_ansi


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class ProcessError(RuntimeError):
    """A lifecycle action failed without changing ownership guarantees."""


class StateFileError(ProcessError):
    """Persisted process state cannot safely be interpreted."""


class ProcessLockTimeout(ProcessError):
    """Another process held the tool lock beyond the bounded wait."""


ProcessLifecycle = Literal["running", "stopping", "stopped", "exited"]
ToolLifecycle = Literal["starting", "running", "unready", "stopping", "stopped", "exited", "error"]


class ProcessState(TypedDict, total=False):
    pid: int
    pgid: int
    starttime: int | None
    started_at: float
    exited_at: float
    exit_code: int | None
    leader_exit_code: int
    lifecycle: ProcessLifecycle
    run_id: str
    group_validated: bool
    stop_deadline: float
    stop_signal: str
    message: str
    readiness_state: Literal["starting", "ready", "unready"]
    readiness_mode: Literal["auto", "process", "http", "tcp"]
    readiness_grace_at: float
    readiness_deadline: float
    readiness_url: str
    readiness_port: int
    readiness_log_offset: int
    readiness_message: str
    ready_at: float
    next_probe_at: float


@dataclass(frozen=True, slots=True)
class ToolStatus:
    id: str
    state: ToolLifecycle
    pid: int | None = None
    started_at: float | None = None
    exited_at: float | None = None
    exit_code: int | None = None
    message: str | None = None
    ready_url: str | None = None

    @property
    def active(self) -> bool:
        return self.state in {"starting", "running", "unready", "stopping"}

    @property
    def uptime(self) -> float | None:
        if self.started_at is None:
            return None
        end = self.exited_at if self.exited_at is not None else time.time()
        return max(0.0, end - self.started_at)


class ProcManager:
    _AUTO_URL_DISCOVERY_SECONDS = 1.0
    _LOCAL_URL = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)

    def __init__(self, *, max_log_bytes: int = 50 * 1024 * 1024) -> None:
        self._closing = Event()
        self._probe_lock = Lock()
        self._probe_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="lattice-readiness")
        self._probes: dict[str, Future[None]] = {}
        self.max_log_bytes = max_log_bytes
        self._children: dict[str, tuple[subprocess.Popen[bytes], str]] = {}
        self._group_snapshot: set[int] | None = None
        self._snapshot_enabled = False
        paths.ensure_dirs()

    def close(self) -> None:
        with self._probe_lock:
            self._closing.set()
            self._probe_pool.shutdown(wait=False, cancel_futures=True)

    @contextmanager
    def snapshot_groups(self) -> Iterator[None]:
        self._snapshot_enabled = os.name != "nt"
        self._group_snapshot = None
        try:
            yield
        finally:
            self._snapshot_enabled = False
            self._group_snapshot = None

    def _group_alive(self, pgid: int) -> bool:
        if self._snapshot_enabled:
            if self._group_snapshot is None:
                self._group_snapshot = active_posix_groups()
            return pgid in self._group_snapshot
        return proc_group_alive(pgid)

    @staticmethod
    def _timestamp() -> str:
        return datetime.now().astimezone().isoformat(timespec="seconds")

    @contextmanager
    def _lock(self, tool_id: str) -> Iterator[None]:
        try:
            with exclusive_file_lock(paths.run_dir() / f"{tool_id}.lock", 2.0, self._closing):
                yield
        except FileLockTimeout as exc:
            raise ProcessLockTimeout(str(exc)) from exc

    @staticmethod
    def _read_state(tool_id: str) -> ProcessState | None:
        try:
            with paths.state_json(tool_id).open("r", encoding="utf-8") as handle:
                state = json.load(handle)
        except FileNotFoundError:
            return None
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise StateFileError(f"无法读取状态文件 {paths.state_json(tool_id)}：{exc}") from exc
        if not isinstance(state, dict):
            raise StateFileError(f"状态文件 {tool_id} 的顶层必须是对象")
        for key in ("pid", "pgid"):
            value = state.get(key)
            if type(value) is not int or value <= 1:
                raise StateFileError(f"状态文件 {tool_id} 的 {key} 必须是大于 1 的整数")
        if not isinstance(state.get("lifecycle"), str) or state["lifecycle"] not in {"running", "stopping", "stopped", "exited"}:
            raise StateFileError(f"状态文件 {tool_id} 的 lifecycle 无效")
        for key in ("started_at", "exited_at", "stop_deadline"):
            value = state.get(key)
            if (key == "started_at" or value is not None) and (
                type(value) not in {int, float} or not math.isfinite(value)
            ):
                raise StateFileError(f"状态文件 {tool_id} 的 {key} 必须是有限数字")
        for key in ("starttime", "exit_code", "leader_exit_code"):
            if state.get(key) is not None and type(state[key]) is not int:
                raise StateFileError(f"状态文件 {tool_id} 的 {key} 必须是整数或 null")
        if "group_validated" in state and type(state["group_validated"]) is not bool:
            raise StateFileError(f"状态文件 {tool_id} 的 group_validated 必须是布尔值")
        for key in ("readiness_grace_at", "readiness_deadline", "ready_at", "next_probe_at"):
            value = state.get(key)
            if value is not None and (type(value) not in {int, float} or not math.isfinite(value)):
                raise StateFileError(f"状态文件 {tool_id} 的 {key} 必须是有限数字")
        for key, allowed in (("readiness_state", {"starting", "ready", "unready"}), ("readiness_mode", {"auto", "process", "http", "tcp"})):
            if key in state and (not isinstance(state[key], str) or state[key] not in allowed):
                raise StateFileError(f"状态文件 {tool_id} 的 {key} 无效")
        for key in ("run_id", "readiness_url", "readiness_message", "message"):
            if key in state and not isinstance(state[key], str):
                raise StateFileError(f"状态文件 {tool_id} 的 {key} 必须是字符串")
        if "readiness_state" in state and not state.get("run_id"):
            raise StateFileError(f"状态文件 {tool_id} 的就绪状态缺少 run_id")
        if "readiness_port" in state and (type(state["readiness_port"]) is not int or not 1 <= state["readiness_port"] <= 65535):
            raise StateFileError(f"状态文件 {tool_id} 的 readiness_port 无效")
        if "readiness_log_offset" in state and (type(state["readiness_log_offset"]) is not int or state["readiness_log_offset"] < 0):
            raise StateFileError(f"状态文件 {tool_id} 的 readiness_log_offset 无效")
        return cast(ProcessState, state)

    @staticmethod
    def _write_state(tool_id: str, state: ProcessState) -> None:
        paths.ensure_dirs()
        payload = json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        atomic_write_text(paths.state_json(tool_id), payload)

    @staticmethod
    def _state_has_identity(state: ProcessState | None) -> bool:
        if state is None:
            return False
        pid = state.get("pid")
        lifecycle = state.get("lifecycle", "running")
        return (
            isinstance(pid, int)
            and not isinstance(pid, bool)
            and pid > (0 if os.name == "nt" else 1)
            and lifecycle in {"running", "stopping", "stopped", "exited"}
        )

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
        except OSError as exc:
            logging.getLogger(__name__).error(
                "process_log_marker_failed", extra={"tool_id": tool_id, "event": event, "error": str(exc)}
            )
            raise ProcessError(f"无法写入 {tool_id} 的 {event} 日志标记：{exc}") from exc

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
    def _log_tail(
        tool_id: str,
        *,
        max_bytes: int = 16 * 1024,
        max_lines: int = 20,
        start_offset: int | None = 0,
    ) -> str:
        try:
            with paths.log_file(tool_id).open("rb") as handle:
                handle.seek(0, os.SEEK_END)
                size = handle.tell()
                selected_offset = start_offset if isinstance(start_offset, int) and 0 <= start_offset <= size else 0
                handle.seek(max(selected_offset, size - max_bytes))
                payload = handle.read()
        except OSError:
            return ""
        if start_offset is None:
            marker_at = payload.rfind(b"LATTICE START ")
            if marker_at >= 0:
                payload = payload[marker_at:]
        text = payload.decode("utf-8", errors="replace")
        return "\n".join(text.splitlines()[-max_lines:]).strip()

    @classmethod
    def _detected_local_url(cls, tool_id: str, start_offset: int | None = 0) -> str:
        matches = cls._LOCAL_URL.findall(
            strip_ansi(
                cls._log_tail(
                    tool_id,
                    max_bytes=64 * 1024,
                    max_lines=200,
                    start_offset=start_offset,
                )
            )
        )
        for match in reversed(matches):
            selected = cls._normalized_local_url(match.rstrip(".,;:)"))
            if selected:
                return selected
        return ""

    @staticmethod
    def _normalized_local_url(value: str) -> str:
        try:
            parsed = urllib.parse.urlsplit(value)
        except ValueError:
            return ""
        if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
            return ""
        try:
            port = parsed.port
        except ValueError:
            return ""
        host = (parsed.hostname or "").casefold()
        if host == "0.0.0.0":
            normalized_host = "127.0.0.1"
        elif host == "localhost":
            normalized_host = "127.0.0.1"
        else:
            try:
                address = ipaddress.ip_address(host)
            except ValueError:
                return ""
            if not address.is_loopback:
                return ""
            normalized_host = f"[{address.compressed}]" if address.version == 6 else address.compressed
        netloc = normalized_host + (f":{port}" if port is not None else "")
        return urllib.parse.urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))

    @staticmethod
    def _probe_http(url: str) -> bool:
        selected = ProcManager._normalized_local_url(url)
        if not selected:
            return False
        request = urllib.request.Request(selected, headers={"User-Agent": "ToolDeck-readiness/1"})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
        try:
            with opener.open(request, timeout=0.35) as response:
                return 100 <= int(response.status) < 500
        except urllib.error.HTTPError as exc:
            return 100 <= exc.code < 500
        except (OSError, ValueError, urllib.error.URLError):
            return False

    @staticmethod
    def _probe_tcp(port: int) -> bool:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.25):
                return True
        except OSError:
            return False

    def _schedule_probe(self, tool_id: str, state: ProcessState, url: str, port: int | None) -> None:
        with self._probe_lock:
            if self._closing.is_set():
                return
            self._submit_probe(tool_id, state, url, port)

    def _submit_probe(self, tool_id: str, state: ProcessState, url: str, port: int | None) -> None:
        pending = self._probes.get(tool_id)
        if pending is not None:
            if not pending.done():
                return
            self._probes.pop(tool_id)
            pending.result()
        for completed_id, future in tuple(self._probes.items()):
            if future.done():
                future.result()
                self._probes.pop(completed_id)
        if len(self._probes) >= 4:
            return
        self._probes[tool_id] = self._probe_pool.submit(
            self._probe_and_record, tool_id, state["run_id"], url, port,
        )

    def _probe_and_record(self, tool_id: str, run_id: str, url: str, port: int | None) -> None:
        """Wait on the network outside the process lock; commit only to this run."""
        ready = self._probe_http(url) if url else self._probe_tcp(port) if port is not None else False
        if not ready or self._closing.is_set():
            return
        with self._lock(tool_id):
            state = self._read_state(tool_id)
            if state is None or state.get("run_id") != run_id or state.get("lifecycle") != "running":
                return
            if state.get("readiness_state") not in {"starting", "unready"}:
                return
            state.update(readiness_state="ready", ready_at=time.time(), readiness_message="已就绪")
            state.pop("next_probe_at", None)
            self._write_state(tool_id, state)
            self._append_marker(tool_id, "READY", f"url={url}" if url else f"port={port}")

    def _update_readiness(self, tool_id: str, state: ProcessState) -> ProcessState:
        readiness = state.get("readiness_state")
        if readiness not in {"starting", "unready"}:
            return state
        now = time.time()
        next_probe = state.get("next_probe_at")
        if isinstance(next_probe, (int, float)) and now < next_probe:
            return state
        mode = state.get("readiness_mode", "auto")
        url = state.get("readiness_url", "")
        port = state.get("readiness_port")
        detected_url = False
        if mode == "auto" and not url and not isinstance(port, int):
            log_offset = state.get("readiness_log_offset")
            url = self._detected_local_url(
                tool_id,
                log_offset if isinstance(log_offset, int) and not isinstance(log_offset, bool) else None,
            )
            if url:
                state["readiness_url"] = url
                detected_url = True
            else:
                grace_at = state.get("readiness_grace_at")
                started_at = state.get("started_at")
                discovery_at = max(
                    float(grace_at) if isinstance(grace_at, (int, float)) else now,
                    (
                        float(started_at) + self._AUTO_URL_DISCOVERY_SECONDS
                        if isinstance(started_at, (int, float))
                        else now
                    ),
                )
                if now < discovery_at:
                    state["next_probe_at"] = now + min(0.25, max(0.05, discovery_at - now))
                    self._write_state(tool_id, state)
                    return state
                state.update(readiness_state="ready", ready_at=now, readiness_message="进程已稳定运行")
                state.pop("next_probe_at", None)
                self._append_marker(tool_id, "READY", "mode=process")
                self._write_state(tool_id, state)
                return state

        grace_at = state.get("readiness_grace_at")
        if isinstance(grace_at, (int, float)) and now < grace_at:
            if detected_url:
                state["next_probe_at"] = float(grace_at)
                self._write_state(tool_id, state)
            return state

        ready = False
        detail = ""
        if mode == "process":
            ready = True
            detail = "mode=process"
        elif mode == "http" and url:
            self._schedule_probe(tool_id, state, url, None)
            detail = f"url={url}"
        elif mode == "tcp" and isinstance(port, int):
            self._schedule_probe(tool_id, state, "", port)
            detail = f"port={port}"
        elif mode == "auto" and url:
            self._schedule_probe(tool_id, state, url, None)
            detail = f"url={url}"
        elif mode == "auto" and isinstance(port, int):
            self._schedule_probe(tool_id, state, "", port)
            detail = f"port={port}"
        if ready:
            state.update(readiness_state="ready", ready_at=now, readiness_message="已就绪")
            state.pop("next_probe_at", None)
            self._append_marker(tool_id, "READY", detail)
            self._write_state(tool_id, state)
            return state

        deadline = state.get("readiness_deadline")
        if isinstance(deadline, (int, float)) and now >= deadline:
            message = "启动探测超时，进程仍在运行并将继续探测"
            changed = state.get("readiness_state") != "unready" or state.get("readiness_message") != message
            state.update(readiness_state="unready", readiness_message=message, next_probe_at=now + 5.0)
            if changed:
                self._append_marker(tool_id, "READINESS-TIMEOUT")
            self._write_state(tool_id, state)
        else:
            until_deadline = float(deadline) - now if isinstance(deadline, (int, float)) else 0.75
            state["next_probe_at"] = now + min(0.75, max(0.05, until_deadline))
            self._write_state(tool_id, state)
        return state

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
            return [shell, "/d", "/c", command]
        if use_windows and executable in {"powershell", "powershell.exe", "pwsh", "pwsh.exe"}:
            return [shell, "-NoLogo", "-NoProfile", "-Command", command]
        return [shell, "-c", command]

    @classmethod
    def _launch_spec(
        cls,
        shell: str,
        command: str,
        *,
        windows: bool | None = None,
    ) -> tuple[str | list[str], dict[str, Any]]:
        use_windows = os.name == "nt" if windows is None else windows
        executable = Path(shell).name.casefold()
        if use_windows and executable in {"cmd", "cmd.exe", "command.com"}:
            # subprocess builds cmd.exe's /C wrapper itself. Passing an argv
            # list here would apply C-runtime quoting rules that cmd does not use.
            return command, {"shell": True, "executable": shell}
        return cls._shell_argv(shell, command, windows=use_windows), {}

    @staticmethod
    def _taskkill_tree(pid: int, *, force: bool) -> bool:
        command = ["taskkill", "/PID", str(pid), "/T"]
        if force:
            command.append("/F")
        try:
            completed = subprocess.run(
                command, stdin=subprocess.DEVNULL, capture_output=True,
                timeout=3.0, check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ProcessError(f"Windows taskkill PID {pid} 失败（3 秒超时）：{exc}") from exc
        if completed.returncode == 0 or not proc_group_alive(pid):
            return True
        if force:
            action = "强制停止" if force else "停止"
            raise ProcessError(
                f"Windows 无法{action} PID {pid} 的进程树；退出码 {completed.returncode}；"
                f"输出 {completed.stdout!r}；错误 {completed.stderr!r}"
            )
        return False

    def _finish_child(self, tool_id: str, state: ProcessState) -> ProcessState:
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

    @classmethod
    def _rollback_started_child(cls, child: subprocess.Popen[bytes]) -> str | None:
        """Terminate an untracked process tree after startup persistence fails."""

        failures: list[str] = []
        if os.name == "nt":
            try:
                cls._taskkill_tree(child.pid, force=True)
            except (OSError, ProcessError) as exc:
                failures.append(str(exc))
        else:
            try:
                os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            except (PermissionError, OSError) as exc:
                failures.append(f"SIGTERM: {exc}")

            try:
                child.wait(timeout=0.25)
            except subprocess.TimeoutExpired:
                pass
            if proc_group_alive(child.pid):
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                except (PermissionError, OSError) as exc:
                    failures.append(f"SIGKILL: {exc}")

        if child.poll() is None:
            try:
                child.kill()
            except OSError as exc:
                failures.append(f"kill: {exc}")
        try:
            child.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            failures.append(f"PID {child.pid} 未退出")
        if os.name != "nt" and proc_group_alive(child.pid):
            failures.append(f"进程组 {child.pid} 仍存活")
        return "；".join(failures) or None

    def status(self, tool_id: str) -> ToolStatus:
        with self._lock(tool_id):
            try:
                return self._status_unlocked(tool_id)
            except OSError as exc:
                raise ProcessError(f"无法同步 {tool_id} 的运行状态：{exc}") from exc

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
            self._group_alive(pgid)
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
                current: ToolLifecycle
                if lifecycle == "stopping":
                    current = "stopping"
                elif state.get("readiness_state") == "starting":
                    current = "starting"
                elif state.get("readiness_state") == "unready":
                    current = "unready"
                else:
                    current = "running"
                return ToolStatus(tool_id, current, pid=pid, started_at=started_at)
            lifecycle = state.get("lifecycle", lifecycle)
            group_alive = self._group_alive(pgid) if group_validated and isinstance(pgid, int) else False

        if lifecycle in {"running", "stopping"} and (leader_alive or group_alive):
            if lifecycle == "stopping":
                current = "stopping"
            else:
                if state.get("readiness_state") not in {"starting", "ready", "unready"}:
                    state.update(
                        run_id=state.get("run_id") or secrets.token_hex(16),
                        readiness_state="ready",
                        readiness_mode="process",
                        ready_at=time.time(),
                        readiness_message="进程运行中",
                    )
                    self._write_state(tool_id, state)
                state = self._update_readiness(tool_id, state)
                readiness_state = state.get("readiness_state")
                current = "starting" if readiness_state == "starting" else "unready" if readiness_state == "unready" else "running"
            message = state.get("message") or state.get("readiness_message")
            return ToolStatus(
                tool_id,
                current,
                pid=pid,
                started_at=started_at,
                message=message if isinstance(message, str) else None,
                ready_url=state.get("readiness_url") if isinstance(state.get("readiness_url"), str) else None,
            )

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
            if lifecycle == "exited" and state.get("readiness_state") != "ready":
                code_text = str(leader_code) if isinstance(leader_code, int) else "unknown"
                tail = self._log_tail(tool_id)
                state["message"] = f"启动期间退出，退出码 {code_text}" + (f"\n\n{tail}" if tail else "")
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
            try:
                self._read_state(tool.id)
            except StateFileError as exc:
                raise StateFileError(f"{tool.name} 的运行状态文件损坏，已拒绝重复启动：{exc}") from exc
            try:
                current = self._status_unlocked(tool.id)
            except OSError as exc:
                raise ProcessError(f"无法同步 {tool.name} 的运行状态：{exc}") from exc
            if current.active:
                raise ProcessError(f"{tool.name} 已在运行（PID {current.pid}）")
            cwd = Path(tool.cwd).expanduser()
            if not cwd.is_dir():
                raise ProcessError(f"工作目录不存在：{cwd}")
            if tool.launch is None:
                shell = self._resolve_shell(tool.shell)
                launch_args, launch_options = self._launch_spec(shell, tool.cmd)
            else:
                if not tool.launch.argv:
                    raise ProcessError("结构化启动参数不能为空")
                launch_args = list(tool.launch.argv)
                launch_options = {}
            try:
                self._rotate_log(tool.id)
                paths.logs_dir().mkdir(parents=True, exist_ok=True)
                log_path = paths.log_file(tool.id)
                readiness_log_offset = 0
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
                    platform_options.update(launch_options)
                    display_command = (
                        subprocess.list2cmdline(launch_args)
                        if isinstance(launch_args, list) and os.name == "nt"
                        else shlex.join(launch_args)
                        if isinstance(launch_args, list)
                        else tool.cmd
                    )
                    output.write(self._marker("COMMAND", display_command))
                    readiness_log_offset = output.tell()
                    child = subprocess.Popen(
                        launch_args,
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
            group_validated = os.name == "nt" or self._posix_group_matches(child.pid, child.pid, starttime)
            run_id = secrets.token_hex(16)
            state: ProcessState = {
                "pid": child.pid,
                "pgid": child.pid,
                "starttime": starttime,
                "started_at": started_at,
                "lifecycle": "running",
                "run_id": run_id,
                "readiness_state": "starting",
                "readiness_mode": tool.readiness.mode,
                "readiness_grace_at": started_at + tool.readiness.grace_seconds,
                "readiness_deadline": started_at + tool.readiness.timeout_seconds,
                "readiness_log_offset": readiness_log_offset,
                "readiness_message": "正在等待启动就绪",
            }
            if tool.readiness.health_url:
                state["readiness_url"] = self._normalized_local_url(tool.readiness.health_url)
            if tool.readiness.health_port is not None:
                state["readiness_port"] = tool.readiness.health_port
            if group_validated:
                state["group_validated"] = True
            try:
                self._write_state(tool.id, state)
            except OSError as exc:
                rollback_error = self._rollback_started_child(child)
                self._children.pop(tool.id, None)
                detail = f"state={exc} rollback={'failed: ' + rollback_error if rollback_error else 'complete'}"
                self._append_marker(tool.id, "START-ROLLBACK", detail)
                message = f"启动状态无法保存，已清理并回滚新进程：{exc}"
                if rollback_error:
                    message += f"；进程树回滚异常：{rollback_error}"
                raise ProcessError(message) from exc
            self._children[tool.id] = (child, run_id)
            return self._status_unlocked(tool.id)

    @staticmethod
    def _signal_number(name: str) -> signal.Signals:
        return signal.Signals[getattr(signal, f"SIG{name}").name]

    def stop_begin(self, tool: ToolConfig) -> ToolStatus:
        with self._lock(tool.id):
            try:
                current = self._status_unlocked(tool.id)
            except OSError as exc:
                raise ProcessError(f"无法同步 {tool.name} 的运行状态：{exc}") from exc
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
            try:
                self._write_state(tool.id, state)
            except OSError as exc:
                raise ProcessError(f"无法保存 {tool.name} 的停止状态：{exc}") from exc
            try:
                if os.name == "nt":
                    self._taskkill_tree(signal_target, force=tool.stop_signal == "KILL")
                else:
                    os.killpg(signal_target, self._signal_number(tool.stop_signal))
            except ProcessLookupError:
                pass
            except (PermissionError, ProcessError, OSError) as exc:
                state["lifecycle"] = "running"
                state.pop("stop_deadline", None)
                try:
                    self._write_state(tool.id, state)
                except OSError as rollback_exc:
                    raise ProcessError(
                        f"停止信号失败且运行状态无法回滚：{exc}；回滚错误：{rollback_exc}"
                    ) from exc
                if isinstance(exc, ProcessError):
                    raise
                raise ProcessError(f"无法停止 PID {signal_target}：{exc}") from exc
            detail = "taskkill=/T" if os.name == "nt" else f"pgid={signal_target} signal=SIG{tool.stop_signal}"
            self._append_marker(tool.id, "STOP", detail)
            return self._status_unlocked(tool.id)

    def tick(self) -> None:
        paths.ensure_dirs()
        errors: list[str] = []
        for state_path in paths.run_dir().glob("*.json"):
            try:
                self._tick_tool(state_path.stem)
            except (ProcessError, OSError) as exc:
                errors.append(str(exc))
        if errors:
            raise ProcessError("\n".join(errors))

    def _tick_tool(self, tool_id: str) -> None:
        with self._lock(tool_id):
            state = self._read_state(tool_id)
            if not state:
                return
            current = self._status_unlocked(tool_id)
            if current.state != "stopping" or current.pid is None:
                return
            state = self._read_state(tool_id) or state
            deadline = state.get("stop_deadline")
            if not isinstance(deadline, (int, float)) or time.time() < deadline:
                return
            signal_target = current.pid if os.name == "nt" else state.get("pgid")
            if not isinstance(signal_target, int) or signal_target <= 1:
                state["message"] = "进程组标识无效，无法强制停止"
                self._write_state(tool_id, state)
                return
            try:
                if os.name == "nt":
                    self._taskkill_tree(signal_target, force=True)
                    self._append_marker(tool_id, "KILL", "taskkill=/F timeout=expired")
                else:
                    os.killpg(signal_target, signal.SIGKILL)
                    self._append_marker(tool_id, "KILL", f"pgid={signal_target} signal=SIGKILL timeout=expired")
            except ProcessLookupError:
                pass
            except (PermissionError, ProcessError) as exc:
                state["message"] = f"无法强制停止 PID {signal_target}：{exc}"
                self._write_state(tool_id, state)
                raise ProcessError(state["message"]) from exc
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
