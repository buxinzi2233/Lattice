"""Pure helpers for tool editor drafts and imported launch paths."""

from __future__ import annotations

import hashlib
import os
import re
import shlex
import shutil
import subprocess
import unicodedata
from collections.abc import Collection, Iterable, Mapping
from pathlib import Path
from typing import Any, TypedDict

from .config import ConfigError, ToolConfig, default_shell
from .launchers import LaunchAnalysis, analyze_launch


_VIRTUAL_ENV_NAMES = (".venv", "venv")
_VIRTUAL_ENV_SEARCH_DEPTH = 5


class ToolDraft(TypedDict):
    originalId: str
    id: str
    name: str
    group: str
    cwd: str
    cmd: str
    shell: str
    envText: str
    autostart: bool
    stopSignal: str
    stopTimeout: float
    launch: dict[str, Any] | None
    readiness: dict[str, Any]
    rawMode: bool
    source: str
    checks: list[dict[str, str]]
    setupRequired: bool
    setupSummary: str
    setupTarget: str
    setupNetwork: bool
    setupCommands: list[str]


def base_tool_id(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode().casefold()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")
    if slug:
        return slug[:64]
    if text:
        return f"tool-{hashlib.sha1(text.encode('utf-8')).hexdigest()[:8]}"
    return "tool"


def unique_tool_id(text: str, existing_ids: Collection[str]) -> str:
    base = base_tool_id(text)
    candidate = base
    number = 2
    while candidate in existing_ids:
        candidate = f"{base}-{number}"
        number += 1
    return candidate


def parse_env_assignments(values: Iterable[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in values:
        if "=" not in item:
            raise ConfigError(f"环境变量必须使用 KEY=VALUE 格式：{item}")
        key, value = item.split("=", 1)
        key = key.strip()
        if not key:
            raise ConfigError("环境变量名不能为空")
        result[key] = value
    return result


def parse_env_text(text: str) -> dict[str, str]:
    assignments: list[str] = []
    for number, raw_line in enumerate(text.splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ConfigError(f"环境变量第 {number} 行缺少 =")
        key, value = line.split("=", 1)
        if not key.strip():
            raise ConfigError(f"环境变量第 {number} 行的名称为空")
        assignments.append(f"{key.strip()}={value}")
    return parse_env_assignments(assignments)


def new_tool_draft(existing_ids: Collection[str], *, home: Path | None = None) -> ToolDraft:
    return {
        "originalId": "",
        "id": unique_tool_id("tool", existing_ids),
        "name": "",
        "group": "",
        "cwd": str(home or Path.home()),
        "cmd": "",
        "shell": default_shell(),
        "envText": "",
        "autostart": False,
        "stopSignal": "TERM",
        "stopTimeout": 10.0,
        "launch": None,
        "readiness": {
            "mode": "auto",
            "grace_seconds": 3.0,
            "timeout_seconds": 120.0,
            "health_url": "",
            "health_port": None,
        },
        "rawMode": False,
        "source": "",
        "checks": [],
        "setupRequired": False,
        "setupSummary": "",
        "setupTarget": "",
        "setupNetwork": False,
        "setupCommands": [],
    }


def tool_to_draft(tool: ToolConfig) -> ToolDraft:
    return {
        "originalId": tool.id,
        "id": tool.id,
        "name": tool.name,
        "group": tool.group,
        "cwd": tool.cwd,
        "cmd": tool.cmd,
        "shell": tool.shell,
        "envText": "\n".join(f"{key}={value}" for key, value in sorted(tool.env.items())),
        "autostart": tool.autostart,
        "stopSignal": tool.stop_signal,
        "stopTimeout": tool.stop_timeout,
        "launch": (
            {
                "mode": tool.launch.mode,
                "detector": tool.launch.detector,
                "source": tool.launch.source,
                "argv": list(tool.launch.argv),
                "interpreter": tool.launch.interpreter,
                "managed_environment": tool.launch.managed_environment,
            }
            if tool.launch is not None
            else None
        ),
        "readiness": {
            "mode": tool.readiness.mode,
            "grace_seconds": tool.readiness.grace_seconds,
            "timeout_seconds": tool.readiness.timeout_seconds,
            "health_url": tool.readiness.health_url,
            "health_port": tool.readiness.health_port,
        },
        "rawMode": tool.launch is None,
        "source": tool.launch.source if tool.launch is not None else "",
        "checks": [],
        "setupRequired": False,
        "setupSummary": "",
        "setupTarget": "",
        "setupNetwork": False,
        "setupCommands": [],
    }


def tool_from_draft(draft: Mapping[str, Any]) -> ToolConfig:
    launch_raw = None if bool(draft.get("rawMode", False)) else draft.get("launch")
    if launch_raw is not None and not isinstance(launch_raw, dict):
        raise ConfigError("launch 必须是对象")
    readiness_raw = draft.get("readiness", {})
    if not isinstance(readiness_raw, dict):
        raise ConfigError("readiness 必须是对象")
    return ToolConfig.from_mapping(
        str(draft.get("id", "")).strip(),
        {
            "name": str(draft.get("name", "")),
            "group": str(draft.get("group", "")),
            "cmd": str(draft.get("cmd", "")),
            "cwd": str(draft.get("cwd", "")),
            "shell": str(draft.get("shell", "")),
            "env": parse_env_text(str(draft.get("envText", ""))),
            "autostart": bool(draft.get("autostart", False)),
            "stop_signal": str(draft.get("stopSignal", "TERM")),
            "stop_timeout": float(draft.get("stopTimeout", 10.0)),
            "launch": launch_raw,
            "readiness": readiness_raw,
        },
    )


def _nearby_python(path: Path, platform_name: str) -> str | None:
    executable_paths = (
        (("Scripts", "python.exe"),)
        if platform_name == "nt"
        else (("bin", "python"), ("bin", "python3"))
    )
    for directory in path.parents[:_VIRTUAL_ENV_SEARCH_DEPTH]:
        for environment_name in _VIRTUAL_ENV_NAMES:
            environment = directory / environment_name
            for executable_path in executable_paths:
                candidate = environment.joinpath(*executable_path)
                if candidate.is_file() and (
                    platform_name == "nt" or os.access(candidate, os.X_OK)
                ):
                    return str(candidate)
    return None


def command_for_launch_path(
    path: Path,
    shell: str | None = None,
    *,
    platform_name: str | None = None,
    python_executable: str | None = None,
) -> tuple[str, str]:
    source = Path(path).expanduser().resolve()
    selected_platform = platform_name or os.name
    selected_shell = shell or default_shell(selected_platform)
    suffix = source.suffix.casefold()
    selected_python = (
        python_executable
        or (_nearby_python(source, selected_platform) if suffix == ".py" else None)
    )
    if suffix == ".py" and not selected_python:
        raise ConfigError("未找到项目 Python 环境；请通过启动检测流程准备环境")
    if selected_platform == "nt":
        if suffix == ".ps1":
            powershell = shutil.which("pwsh") or shutil.which("powershell") or "powershell.exe"
            escaped = str(source).replace("'", "''")
            return f"& '{escaped}'", powershell
        if suffix == ".exe":
            return f'start "" /wait {subprocess.list2cmdline([str(source)])}', default_shell("nt")
        if suffix in {".bat", ".cmd"}:
            return subprocess.list2cmdline([str(source)]), default_shell("nt")
        parts = [selected_python, str(source)] if suffix == ".py" else [str(source)]
        return subprocess.list2cmdline(parts), selected_shell
    if suffix == ".py":
        parts = [selected_python, str(source)]
    elif suffix == ".sh" and not os.access(source, os.X_OK):
        parts = [selected_shell, str(source)]
    else:
        parts = [str(source)]
    return shlex.join(parts), selected_shell


def launch_patch_for_analysis(
    analysis: LaunchAnalysis,
    existing_ids: Collection[str],
) -> dict[str, Any]:
    if analysis.blocking or analysis.plan is None:
        messages = [check.message for check in analysis.checks if check.level == "blocking"]
        raise ConfigError("；".join(messages) or "无法识别启动入口")
    plan = analysis.plan
    setup = plan.setup
    readiness = plan.readiness
    return {
        "name": plan.source.stem,
        "cwd": str(plan.cwd),
        "cmd": plan.command,
        "shell": default_shell(),
        "suggestedId": unique_tool_id(plan.source.stem, existing_ids),
        "source": str(plan.source),
        "launch": {
            "mode": "argv",
            "detector": plan.detector,
            "source": str(plan.source),
            "argv": list(plan.argv),
            "interpreter": plan.interpreter,
            "managed_environment": plan.managed_environment,
        },
        "readiness": {
            "mode": readiness.mode,
            "grace_seconds": readiness.grace_seconds,
            "timeout_seconds": readiness.timeout_seconds,
            "health_url": readiness.health_url,
            "health_port": readiness.health_port,
        },
        "rawMode": False,
        "checks": [
            {"code": check.code, "level": check.level, "message": check.message}
            for check in analysis.checks
        ],
        "setupRequired": setup is not None,
        "setupSummary": setup.summary if setup is not None else "",
        "setupTarget": str(setup.environment_dir) if setup is not None else "",
        "setupNetwork": setup.requires_network if setup is not None else False,
        "setupCommands": [command.display for command in setup.commands] if setup is not None else [],
    }


def launch_draft_for_path(
    path: Path,
    shell: str,
    existing_ids: Collection[str],
) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    analysis = analyze_launch(source)
    return launch_patch_for_analysis(analysis, existing_ids)
