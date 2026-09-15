from __future__ import annotations

import json
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Mapping

from . import paths
from .storage import atomic_write_bytes, atomic_write_text
from .util import valid_id


class ConfigError(ValueError):
    """A tool configuration is missing data or contains an invalid value."""


def default_shell(
    platform_name: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> str:
    selected_platform = platform_name or os.name
    selected_environ = environ if environ is not None else os.environ
    if selected_platform == "nt":
        return selected_environ.get("COMSPEC") or "cmd.exe"
    return "/bin/bash" if Path("/bin/bash").is_file() else "/bin/sh"


@dataclass(frozen=True, slots=True)
class ConfigIssue:
    path: Path
    message: str


LaunchMode = Literal["argv"]
ReadinessMode = Literal["auto", "process", "http", "tcp"]


@dataclass(frozen=True, slots=True)
class LaunchConfig:
    mode: LaunchMode
    detector: str
    source: str
    argv: tuple[str, ...]
    interpreter: str = ""
    managed_environment: bool = False


@dataclass(frozen=True, slots=True)
class ReadinessConfig:
    mode: ReadinessMode = "auto"
    grace_seconds: float = 3.0
    timeout_seconds: float = 120.0
    health_url: str = ""
    health_port: int | None = None


@dataclass(frozen=True, slots=True)
class ToolConfig:
    id: str
    name: str
    cmd: str
    cwd: str
    shell: str = field(default_factory=default_shell)
    env: dict[str, str] = field(default_factory=dict)
    autostart: bool = False
    stop_signal: str = "TERM"
    stop_timeout: float = 10.0
    group: str = ""
    launch: LaunchConfig | None = None
    readiness: ReadinessConfig = field(default_factory=ReadinessConfig)

    @classmethod
    def from_mapping(cls, tool_id: str, raw: dict[str, Any]) -> "ToolConfig":
        if not valid_id(tool_id):
            raise ConfigError("工具 ID 只能包含字母、数字、点、下划线和连字符")

        def required_text(key: str) -> str:
            value = raw.get(key)
            if not isinstance(value, str) or not value.strip():
                raise ConfigError(f"{key} 必须是非空字符串")
            if "\x00" in value:
                raise ConfigError(f"{key} 不能包含 NUL 字符")
            return value.strip() if key != "cmd" else value

        name = required_text("name")
        cmd = required_text("cmd")
        cwd = str(Path(required_text("cwd")).expanduser())

        group = raw.get("group", "")
        if not isinstance(group, str):
            raise ConfigError("group 必须是字符串")
        group = group.strip()
        if "\x00" in group or "\n" in group or "\r" in group:
            raise ConfigError("group 必须是单行文本")
        if len(group) > 64:
            raise ConfigError("group 不能超过 64 个字符")

        shell = raw.get("shell", default_shell())
        if not isinstance(shell, str) or not shell.strip() or "\x00" in shell:
            raise ConfigError("shell 必须是非空字符串")

        env_raw = raw.get("env", {})
        if not isinstance(env_raw, dict):
            raise ConfigError("env 必须是 TOML 表")
        env: dict[str, str] = {}
        for key, value in env_raw.items():
            if not isinstance(key, str) or not key or "=" in key or "\x00" in key:
                raise ConfigError(f"无效环境变量名：{key!r}")
            if not isinstance(value, (str, int, float, bool)):
                raise ConfigError(f"环境变量 {key} 的值必须是字符串或标量")
            text_value = str(value)
            if "\x00" in text_value:
                raise ConfigError(f"环境变量 {key} 的值不能包含 NUL 字符")
            env[key] = text_value

        autostart = raw.get("autostart", False)
        if not isinstance(autostart, bool):
            raise ConfigError("autostart 必须是 true 或 false")

        stop_signal = raw.get("stop_signal", "TERM")
        if not isinstance(stop_signal, str):
            raise ConfigError("stop_signal 必须是字符串")
        stop_signal = stop_signal.upper().removeprefix("SIG")
        if stop_signal not in {"TERM", "INT", "HUP", "QUIT", "KILL"}:
            raise ConfigError("stop_signal 仅支持 TERM、INT、HUP、QUIT 或 KILL")

        stop_timeout = raw.get("stop_timeout", 10.0)
        if isinstance(stop_timeout, bool) or not isinstance(stop_timeout, (int, float)):
            raise ConfigError("stop_timeout 必须是数字")
        stop_timeout = float(stop_timeout)
        if not 0 <= stop_timeout <= 3600:
            raise ConfigError("stop_timeout 必须在 0 到 3600 秒之间")

        launch_raw = raw.get("launch")
        launch: LaunchConfig | None = None
        if launch_raw is not None:
            if not isinstance(launch_raw, dict):
                raise ConfigError("launch 必须是 TOML 表")
            mode = launch_raw.get("mode", "argv")
            if mode != "argv":
                raise ConfigError("launch.mode 仅支持 argv")
            detector = launch_raw.get("detector")
            source = launch_raw.get("source")
            if not isinstance(detector, str) or not detector.strip() or "\x00" in detector:
                raise ConfigError("launch.detector 必须是非空字符串")
            if not isinstance(source, str) or not source.strip() or "\x00" in source:
                raise ConfigError("launch.source 必须是非空字符串")
            argv_raw = launch_raw.get("argv")
            if not isinstance(argv_raw, list) or not argv_raw:
                raise ConfigError("launch.argv 必须是非空字符串数组")
            argv: list[str] = []
            for argument in argv_raw:
                if not isinstance(argument, str) or not argument or "\x00" in argument:
                    raise ConfigError("launch.argv 只能包含非空且无 NUL 的字符串")
                argv.append(argument)
            interpreter = launch_raw.get("interpreter", "")
            if not isinstance(interpreter, str) or "\x00" in interpreter:
                raise ConfigError("launch.interpreter 必须是字符串")
            managed_environment = launch_raw.get("managed_environment", False)
            if not isinstance(managed_environment, bool):
                raise ConfigError("launch.managed_environment 必须是 true 或 false")
            launch = LaunchConfig(
                "argv",
                detector.strip(),
                str(Path(source).expanduser()),
                tuple(argv),
                interpreter.strip(),
                managed_environment,
            )

        readiness_raw = raw.get("readiness", {})
        if not isinstance(readiness_raw, dict):
            raise ConfigError("readiness 必须是 TOML 表")
        readiness_mode = readiness_raw.get("mode", "auto")
        if readiness_mode not in {"auto", "process", "http", "tcp"}:
            raise ConfigError("readiness.mode 仅支持 auto、process、http 或 tcp")

        def readiness_number(key: str, default: float, *, minimum: float, maximum: float) -> float:
            value = readiness_raw.get(key, default)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ConfigError(f"readiness.{key} 必须是数字")
            result = float(value)
            if not minimum <= result <= maximum:
                raise ConfigError(f"readiness.{key} 必须在 {minimum:g} 到 {maximum:g} 秒之间")
            return result

        grace_seconds = readiness_number("grace_seconds", 3.0, minimum=0.0, maximum=3600.0)
        timeout_seconds = readiness_number("timeout_seconds", 120.0, minimum=0.1, maximum=86400.0)
        health_url = readiness_raw.get("health_url", "")
        if not isinstance(health_url, str) or "\x00" in health_url:
            raise ConfigError("readiness.health_url 必须是字符串")
        health_url = health_url.strip()
        health_port_raw = readiness_raw.get("health_port")
        if health_port_raw is None:
            health_port = None
        elif isinstance(health_port_raw, bool) or not isinstance(health_port_raw, int):
            raise ConfigError("readiness.health_port 必须是整数")
        elif not 1 <= health_port_raw <= 65535:
            raise ConfigError("readiness.health_port 必须在 1 到 65535 之间")
        else:
            health_port = health_port_raw
        if readiness_mode == "http" and not health_url:
            raise ConfigError("readiness.mode=http 时必须设置 health_url")
        if readiness_mode == "tcp" and health_port is None:
            raise ConfigError("readiness.mode=tcp 时必须设置 health_port")
        readiness = ReadinessConfig(
            readiness_mode,
            grace_seconds,
            timeout_seconds,
            health_url,
            health_port,
        )

        return cls(
            id=tool_id,
            name=name,
            cmd=cmd,
            cwd=cwd,
            shell=shell.strip(),
            env=env,
            autostart=autostart,
            stop_signal=stop_signal,
            stop_timeout=stop_timeout,
            group=group,
            launch=launch,
            readiness=readiness,
        )


def load_file(path: Path, tool_id: str | None = None) -> ToolConfig:
    path = Path(path)
    selected_id = tool_id or path.stem
    try:
        with path.open("rb") as handle:
            raw = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(str(exc)) from exc
    if not isinstance(raw, dict):
        raise ConfigError("配置顶层必须是 TOML 表")
    return ToolConfig.from_mapping(selected_id, raw)


def load_all() -> tuple[dict[str, ToolConfig], list[ConfigIssue]]:
    paths.ensure_dirs()
    tools: dict[str, ToolConfig] = {}
    issues: list[ConfigIssue] = []
    for config_path in sorted(paths.tools_dir().glob("*.toml")):
        try:
            tool = load_file(config_path)
        except ConfigError as exc:
            issues.append(ConfigIssue(config_path, str(exc)))
            continue
        tools[tool.id] = tool
    return tools, issues


def _toml_string(value: str) -> str:
    # TOML basic strings share JSON's escaping rules for the characters used here.
    return json.dumps(value, ensure_ascii=False)


def _toml_command(value: str) -> str:
    # A literal multiline string keeps shell scripts readable and preserves $, \ and quotes.
    if "\n" in value and "'''" not in value and "\x00" not in value:
        return "'''" + value + "'''"
    return _toml_string(value)


def _toml_string_array(values: tuple[str, ...]) -> str:
    return "[" + ", ".join(_toml_string(value) for value in values) + "]"


def dumps(tool: ToolConfig) -> str:
    lines = [
        f"name = {_toml_string(tool.name)}",
        f"group = {_toml_string(tool.group)}",
        f"cmd = {_toml_command(tool.cmd)}",
        f"cwd = {_toml_string(tool.cwd)}",
        f"shell = {_toml_string(tool.shell)}",
        f"autostart = {'true' if tool.autostart else 'false'}",
        f"stop_signal = {_toml_string(tool.stop_signal)}",
        f"stop_timeout = {tool.stop_timeout:g}",
    ]
    if tool.env:
        lines.extend(("", "[env]"))
        for key, value in sorted(tool.env.items()):
            lines.append(f"{_toml_string(key)} = {_toml_string(value)}")
    if tool.launch is not None:
        lines.extend(
            (
                "",
                "[launch]",
                f"mode = {_toml_string(tool.launch.mode)}",
                f"detector = {_toml_string(tool.launch.detector)}",
                f"source = {_toml_string(tool.launch.source)}",
                f"argv = {_toml_string_array(tool.launch.argv)}",
                f"interpreter = {_toml_string(tool.launch.interpreter)}",
                f"managed_environment = {'true' if tool.launch.managed_environment else 'false'}",
            )
        )
    if tool.launch is not None or tool.readiness != ReadinessConfig():
        lines.extend(
            (
                "",
                "[readiness]",
                f"mode = {_toml_string(tool.readiness.mode)}",
                f"grace_seconds = {tool.readiness.grace_seconds:g}",
                f"timeout_seconds = {tool.readiness.timeout_seconds:g}",
                f"health_url = {_toml_string(tool.readiness.health_url)}",
            )
        )
        if tool.readiness.health_port is not None:
            lines.append(f"health_port = {tool.readiness.health_port}")
    return "\n".join(lines) + "\n"


def save(tool: ToolConfig, *, overwrite: bool = True) -> Path:
    # Revalidate dataclass instances constructed directly by callers.
    checked = ToolConfig.from_mapping(
        tool.id,
        {
            "name": tool.name,
            "cmd": tool.cmd,
            "cwd": tool.cwd,
            "shell": tool.shell,
            "env": tool.env,
            "autostart": tool.autostart,
            "stop_signal": tool.stop_signal,
            "stop_timeout": tool.stop_timeout,
            "group": tool.group,
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
        },
    )
    paths.ensure_dirs()
    destination = paths.tool_toml(checked.id)
    if destination.exists() and not overwrite:
        raise ConfigError(f"工具 {checked.id} 已存在")
    data = dumps(checked)
    return atomic_write_text(destination, data)


def delete(tool_id: str) -> None:
    if not valid_id(tool_id):
        raise ConfigError("无效工具 ID")
    try:
        paths.tool_toml(tool_id).unlink()
    except FileNotFoundError as exc:
        raise ConfigError(f"工具 {tool_id} 不存在") from exc


def import_toml(source: Path, *, overwrite: bool = False) -> ToolConfig:
    source = Path(source).expanduser().resolve()
    tool = load_file(source)
    paths.ensure_dirs()
    destination = paths.tool_toml(tool.id)
    if destination.exists() and not overwrite:
        raise ConfigError(f"工具 {tool.id} 已存在")
    try:
        atomic_write_bytes(destination, source.read_bytes())
    except OSError as exc:
        raise ConfigError(str(exc)) from exc
    return tool
