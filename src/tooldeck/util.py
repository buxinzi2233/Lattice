from __future__ import annotations

import os
import re
import unicodedata
from pathlib import Path

if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    _KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    _SYNCHRONIZE = 0x00100000
    _STILL_ACTIVE = 259
    _TH32CS_SNAPPROCESS = 0x00000002
    _INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

    class _FILETIME(ctypes.Structure):
        _fields_ = (("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD))

    class _PROCESSENTRY32W(ctypes.Structure):
        _fields_ = (
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        )

    _KERNEL32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    _KERNEL32.OpenProcess.restype = wintypes.HANDLE
    _KERNEL32.CloseHandle.argtypes = (wintypes.HANDLE,)
    _KERNEL32.CloseHandle.restype = wintypes.BOOL
    _KERNEL32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    _KERNEL32.GetExitCodeProcess.restype = wintypes.BOOL
    _KERNEL32.GetProcessTimes.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(_FILETIME),
        ctypes.POINTER(_FILETIME),
        ctypes.POINTER(_FILETIME),
        ctypes.POINTER(_FILETIME),
    )
    _KERNEL32.GetProcessTimes.restype = wintypes.BOOL
    _KERNEL32.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
    _KERNEL32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    _KERNEL32.Process32FirstW.argtypes = (wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W))
    _KERNEL32.Process32FirstW.restype = wintypes.BOOL
    _KERNEL32.Process32NextW.argtypes = (wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W))
    _KERNEL32.Process32NextW.restype = wintypes.BOOL

ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

# CSI、OSC（BEL 或 ST 结尾）以及其余单字符 ESC 序列
ANSI_RE = re.compile(
    r"\x1b\[[0-9;?]*[ -/]*[@-~]"
    r"|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"
    r"|\x1b[@-_]"
)


def valid_id(s: str) -> bool:
    return bool(ID_RE.match(s))


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


def collapse_cr(line: str) -> str:
    """进度条类输出会用 \r 反复重写一行，只保留最后一段。"""
    line = line.rstrip("\r\n")
    if "\r" in line:
        line = line.rsplit("\r", 1)[-1]
    return line


def fmt_duration(secs: float | int | None) -> str:
    if secs is None:
        return "—"
    secs = max(0, int(secs))
    d, r = divmod(secs, 86400)
    h, r = divmod(r, 3600)
    m, s = divmod(r, 60)
    if d:
        return f"{d}天{h}小时"
    if h:
        return f"{h}小时{m}分"
    if m:
        return f"{m}分{s:02d}秒"
    return f"{s}秒"


def short_home(path: str) -> str:
    candidate = Path(path).expanduser()
    try:
        relative = candidate.relative_to(Path.home())
    except ValueError:
        return str(candidate)
    return "~" if str(relative) == "." else str(Path("~") / relative)


def _proc_stat_fields(pid: int) -> list[str] | None:
    """comm 可能含空格/括号，从最后一个 ')' 之后切分。"""
    try:
        text = Path(f"/proc/{pid}/stat").read_text()
        return text[text.rindex(")") + 2:].split()
    except (OSError, ValueError):
        return None


def proc_starttime(pid: int) -> int | None:
    if os.name == "nt":
        if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
            return None
        handle = _KERNEL32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return None
        creation = _FILETIME()
        exit_time = _FILETIME()
        kernel = _FILETIME()
        user = _FILETIME()
        try:
            if not _KERNEL32.GetProcessTimes(
                handle,
                ctypes.byref(creation),
                ctypes.byref(exit_time),
                ctypes.byref(kernel),
                ctypes.byref(user),
            ):
                return None
            return (creation.dwHighDateTime << 32) | creation.dwLowDateTime
        finally:
            _KERNEL32.CloseHandle(handle)
    fields = _proc_stat_fields(pid)
    if fields is None or len(fields) < 20:
        return None
    try:
        return int(fields[19])
    except ValueError:
        return None


def proc_alive(pid: object, starttime: int | None = None) -> bool:
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= (0 if os.name == "nt" else 1):
        return False
    if os.name == "nt":
        handle = _KERNEL32.OpenProcess(
            _PROCESS_QUERY_LIMITED_INFORMATION | _SYNCHRONIZE,
            False,
            pid,
        )
        if not handle:
            return False
        exit_code = wintypes.DWORD()
        try:
            if not _KERNEL32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False
            if exit_code.value != _STILL_ACTIVE:
                return False
            return starttime is None or proc_starttime(pid) == starttime
        finally:
            _KERNEL32.CloseHandle(handle)
    fields = _proc_stat_fields(pid)
    if fields is None or fields[0] == "Z":
        return False
    if starttime is not None:
        if len(fields) < 20:
            return False
        try:
            if int(fields[19]) != starttime:
                return False
        except ValueError:
            return False
    return True


def proc_group_alive(pgid: object) -> bool:
    """Return whether a process group contains at least one non-zombie member."""
    if not isinstance(pgid, int) or isinstance(pgid, bool) or pgid <= (0 if os.name == "nt" else 1):
        return False
    if os.name == "nt":
        snapshot = _KERNEL32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
        if snapshot == _INVALID_HANDLE_VALUE:
            return False
        entry = _PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        parents: dict[int, int] = {}
        try:
            if not _KERNEL32.Process32FirstW(snapshot, ctypes.byref(entry)):
                return False
            while True:
                parents[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
                if not _KERNEL32.Process32NextW(snapshot, ctypes.byref(entry)):
                    break
        finally:
            _KERNEL32.CloseHandle(snapshot)
        if pgid in parents:
            return True
        for pid in parents:
            current = pid
            visited: set[int] = set()
            while current in parents and current not in visited:
                visited.add(current)
                current = parents[current]
                if current == pgid:
                    return True
        return False
    try:
        entries = Path("/proc").iterdir()
    except OSError:
        return False
    for entry in entries:
        if not entry.name.isdigit():
            continue
        fields = _proc_stat_fields(int(entry.name))
        if fields is None or len(fields) < 3 or fields[0] == "Z":
            continue
        try:
            if int(fields[2]) == pgid:
                return True
        except ValueError:
            continue
    return False


def disp_width(s: str) -> int:
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def pad(s: str, width: int) -> str:
    return s + " " * max(0, width - disp_width(s))


def active_posix_groups() -> set[int]:
    """Capture live POSIX groups once; processes disappearing during a scan are normal."""
    groups: set[int] = set()
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        fields = _proc_stat_fields(int(entry.name))
        if fields is not None and len(fields) >= 3 and fields[0] != "Z":
            groups.add(int(fields[2]))
    return groups
