"""XDG 路径解析。全部在调用时读取环境变量，便于测试重定向。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

APP = "tooldeck"


def _location(
    env_var: str,
    default: str,
    windows_env: str,
    windows_default: str,
    *,
    platform_name: str | None = None,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    selected_platform = platform_name or os.name
    selected_environ = environ if environ is not None else os.environ
    selected_home = home or Path.home()
    raw = selected_environ.get(env_var, "").strip()
    if raw:
        base = Path(raw)
    elif selected_platform == "nt":
        windows_raw = selected_environ.get(windows_env, "").strip()
        base = Path(windows_raw) if windows_raw else selected_home / windows_default
    else:
        base = Path(default).expanduser()
    return base.expanduser() / APP


def config_dir() -> Path:
    return _location("XDG_CONFIG_HOME", "~/.config", "APPDATA", "AppData/Roaming")


def tools_dir() -> Path:
    return config_dir() / "tools.d"


def state_dir() -> Path:
    return _location("XDG_STATE_HOME", "~/.local/state", "LOCALAPPDATA", "AppData/Local")


def run_dir() -> Path:
    return state_dir() / "run"


def logs_dir() -> Path:
    return state_dir() / "logs"


def setup_logs_dir() -> Path:
    return state_dir() / "setup"


def setup_state_dir() -> Path:
    return state_dir() / "setup-state"


def layout_json() -> Path:
    return config_dir() / "layout.json"


def themes_dir() -> Path:
    return config_dir() / "themes.d"


def catalog_journal_json() -> Path:
    return config_dir() / ".catalog-transaction.json"


def catalog_lock_file() -> Path:
    return config_dir() / ".catalog.lock"


def startup_cache_dir() -> Path:
    return state_dir() / "startup-cache"


def startup_state_json() -> Path:
    return state_dir() / "startup.json"


def ensure_dirs() -> None:
    for d in (tools_dir(), themes_dir(), run_dir(), logs_dir(), setup_logs_dir(), setup_state_dir()):
        d.mkdir(parents=True, exist_ok=True)


def tool_toml(tool_id: str) -> Path:
    return tools_dir() / f"{tool_id}.toml"


def state_json(tool_id: str) -> Path:
    return run_dir() / f"{tool_id}.json"


def log_file(tool_id: str) -> Path:
    return logs_dir() / f"{tool_id}.log"
