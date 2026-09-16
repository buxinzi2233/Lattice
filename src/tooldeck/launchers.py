"""Declarative launch detection, setup execution, and shared preflight checks."""

from __future__ import annotations

import hashlib
import ipaddress
import os
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.parse
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from importlib import metadata
from pathlib import Path
from typing import Literal, Protocol

from . import paths
from .config import LaunchConfig, ReadinessConfig, ToolConfig
from .storage import exclusive_file_lock
from .util import proc_group_alive


ENTRY_POINT_GROUP = "tooldeck.launch_detectors"
CheckLevel = Literal["ok", "warning", "blocking"]


@dataclass(frozen=True, slots=True)
class LaunchCheck:
    code: str
    level: CheckLevel
    message: str


@dataclass(frozen=True, slots=True)
class SetupCommand:
    argv: tuple[str, ...]
    cwd: Path
    network: bool = False

    @property
    def display(self) -> str:
        return subprocess.list2cmdline(self.argv) if os.name == "nt" else shlex.join(self.argv)


@dataclass(frozen=True, slots=True)
class SetupPlan:
    detector: str
    project_root: Path
    environment_dir: Path
    commands: tuple[SetupCommand, ...]
    expected_paths: tuple[Path, ...]
    summary: str
    allow_existing_environment: bool = False

    @property
    def requires_network(self) -> bool:
        return any(command.network for command in self.commands)


@dataclass(frozen=True, slots=True)
class LaunchPlan:
    detector: str
    source: Path
    cwd: Path
    argv: tuple[str, ...]
    interpreter: str = ""
    managed_environment: bool = False
    readiness: ReadinessConfig = field(default_factory=ReadinessConfig)
    setup: SetupPlan | None = None
    checks: tuple[LaunchCheck, ...] = ()

    @property
    def command(self) -> str:
        return subprocess.list2cmdline(self.argv) if os.name == "nt" else shlex.join(self.argv)

    def launch_config(self) -> LaunchConfig:
        return LaunchConfig(
            mode="argv",
            detector=self.detector,
            source=str(self.source),
            argv=self.argv,
            interpreter=self.interpreter,
            managed_environment=self.managed_environment,
        )


@dataclass(frozen=True, slots=True)
class LaunchAnalysis:
    source: Path
    plan: LaunchPlan | None
    checks: tuple[LaunchCheck, ...]

    @property
    def blocking(self) -> bool:
        return self.plan is None or any(check.level == "blocking" for check in self.checks)


@dataclass(frozen=True, slots=True)
class PreflightReport:
    checks: tuple[LaunchCheck, ...]

    @property
    def blocking(self) -> bool:
        return any(check.level == "blocking" for check in self.checks)

    @property
    def blocking_messages(self) -> tuple[str, ...]:
        return tuple(check.message for check in self.checks if check.level == "blocking")


@dataclass(frozen=True, slots=True)
class PreparationResult:
    success: bool
    cancelled: bool
    return_code: int | None
    log_path: Path
    message: str


@dataclass(frozen=True, slots=True)
class DetectionContext:
    platform_name: str
    tooldeck_python: Path
    which: Callable[[str], str | None]


class LaunchDetector(Protocol):
    id: str
    priority: int

    def detect(self, source: Path, context: DetectionContext) -> LaunchPlan | None: ...


def _environment_root(executable: Path) -> Path | None:
    parent = executable.expanduser().absolute().parent
    for directory in (parent, parent.parent):
        if (directory / "pyvenv.cfg").is_file():
            return directory.resolve()
    return None


def _same_path(left: str | Path, right: str | Path) -> bool:
    """Compare Python environments before following executable symlinks."""
    left_path = Path(left).expanduser()
    right_path = Path(right).expanduser()
    left_environment = _environment_root(left_path)
    right_environment = _environment_root(right_path)
    if left_environment is not None or right_environment is not None:
        return left_environment == right_environment
    if left_path.exists() and right_path.exists():
        return os.path.samefile(left_path, right_path)
    return left_path.resolve() == right_path.resolve()


def _is_executable(path: Path, platform_name: str) -> bool:
    return path.is_file() and (platform_name == "nt" or os.access(path, os.X_OK))


def _environment_python(environment: Path, platform_name: str) -> Path:
    return environment / ("Scripts/python.exe" if platform_name == "nt" else "bin/python")


def _setup_incomplete_marker(environment: Path) -> Path:
    identity = os.path.normcase(str(environment.expanduser().resolve()))
    digest = hashlib.sha256(identity.encode("utf-8", errors="surrogatepass")).hexdigest()[:24]
    return paths.setup_state_dir() / f"{digest}.incomplete"


def _project_root(source: Path) -> Path:
    markers = (".venv", "venv", "pyproject.toml", "requirements.txt", "uv.lock", ".git")
    candidates = (source.parent, *source.parents[:5])
    return next((directory for directory in candidates if any((directory / marker).exists() for marker in markers)), source.parent)


def _resolve_program(value: str, context: DetectionContext) -> str | None:
    expanded = os.path.expanduser(value)
    path = Path(expanded)
    separators = tuple(separator for separator in (os.path.sep, os.path.altsep) if separator)
    if path.is_absolute() or any(separator in expanded for separator in separators):
        return str(path) if _is_executable(path, context.platform_name) else None
    return context.which(expanded)


def _shebang_parts(source: Path) -> tuple[str, ...] | None:
    try:
        first_line = source.open("r", encoding="utf-8", errors="replace").readline(4096).strip()
    except OSError:
        return None
    if not first_line.startswith("#!"):
        return None
    try:
        return tuple(shlex.split(first_line[2:].strip()))
    except ValueError:
        return ()


def _resolve_shebang_program(parts: tuple[str, ...] | None, context: DetectionContext) -> str | None:
    if not parts:
        return None
    if Path(parts[0]).name == "env" and len(parts) > 1:
        arguments = list(parts[1:])
        if arguments and arguments[0] in {"-S", "--split-string"}:
            arguments.pop(0)
        elif arguments and arguments[0].startswith("--split-string="):
            split_value = arguments.pop(0).split("=", 1)[1]
            try:
                arguments[:0] = shlex.split(split_value)
            except ValueError:
                return None
        while arguments and "=" in arguments[0] and not arguments[0].startswith("="):
            arguments.pop(0)
        return _resolve_program(arguments[0], context) if arguments else None
    return _resolve_program(parts[0], context)


def _shebang_program(source: Path, context: DetectionContext) -> str | None:
    return _resolve_shebang_program(_shebang_parts(source), context)


def _base_python(source: Path, context: DetectionContext) -> str | None:
    candidates = [_shebang_program(source, context)]
    candidates.extend(
        context.which(name)
        for name in (("python", "python3", "py") if context.platform_name == "nt" else ("python3", "python"))
    )
    if context.tooldeck_python == Path(sys.executable).absolute() and sys.prefix != sys.base_prefix:
        candidates.append(sys._base_executable)
    for candidate in candidates:
        if candidate and not _same_path(candidate, context.tooldeck_python):
            return candidate
    return None


class PythonDetector:
    id = "python"
    priority = 100

    def _setup_plan(
        self,
        source: Path,
        context: DetectionContext,
        root: Path,
        environment: Path,
        checks: list[LaunchCheck],
        *,
        resume: bool,
        create_environment: bool,
    ) -> LaunchPlan:
        interpreter = _environment_python(environment, context.platform_name)
        uv = context.which("uv")
        use_uv = bool(uv and (root / "uv.lock").is_file() and (root / "pyproject.toml").is_file())
        commands: list[SetupCommand] = []
        if use_uv and uv is not None:
            commands.append(SetupCommand((uv, "sync", "--frozen", "--project", str(root)), root, network=True))
        else:
            if create_environment:
                base_python = _base_python(source, context)
                if base_python is None:
                    checks.append(LaunchCheck("missing-python", "blocking", "找不到可用于创建项目环境的系统 Python"))
                    return LaunchPlan(self.id, source, source.parent, (), checks=tuple(checks))
                base_argv = (
                    (base_python, "-3")
                    if context.platform_name == "nt" and Path(base_python).name.casefold() in {"py", "py.exe"}
                    else (base_python,)
                )
                commands.append(SetupCommand((*base_argv, "-m", "venv", str(environment)), root))
            requirements = root / "requirements.txt"
            if requirements.is_file():
                commands.append(
                    SetupCommand((str(interpreter), "-m", "pip", "install", "-r", str(requirements)), root, network=True)
                )
            elif (root / "pyproject.toml").is_file():
                commands.append(SetupCommand((str(interpreter), "-m", "pip", "install", str(root)), root, network=True))
        if resume:
            checks.append(LaunchCheck("environment-resume", "warning", f"上次环境准备未完成，需要继续：{environment}"))
            summary = "继续准备 ToolDeck 创建但尚未完成的 Python 环境"
        else:
            checks.append(LaunchCheck("environment-setup", "warning", f"需要创建项目环境：{environment}"))
            summary = "创建项目本地 Python 环境并安装可识别的依赖"
        setup = SetupPlan(
            self.id,
            root,
            environment,
            tuple(commands),
            (interpreter,),
            summary,
            allow_existing_environment=resume,
        )
        return LaunchPlan(
            self.id,
            source,
            source.parent,
            (str(interpreter), str(source)),
            str(interpreter),
            managed_environment=True,
            setup=setup,
            checks=tuple(checks),
        )

    def detect(self, source: Path, context: DetectionContext) -> LaunchPlan | None:
        if source.suffix.casefold() not in {".py", ".pyw"}:
            return None
        checks: list[LaunchCheck] = []
        candidates = (source.parent, *source.parents[:5])
        invalid_environments: list[Path] = []
        for directory in candidates:
            for name in (".venv", "venv"):
                environment = directory / name
                incomplete_marker = _setup_incomplete_marker(environment)
                if not environment.exists():
                    if incomplete_marker.is_file():
                        return self._setup_plan(
                            source,
                            context,
                            directory,
                            environment,
                            checks,
                            resume=True,
                            create_environment=True,
                        )
                    continue
                interpreter = _environment_python(environment, context.platform_name)
                if _is_executable(interpreter, context.platform_name):
                    if _same_path(interpreter, context.tooldeck_python):
                        checks.append(LaunchCheck("tooldeck-python", "blocking", "拒绝使用 ToolDeck 自身 Python 解释器"))
                        continue
                    if incomplete_marker.is_file():
                        return self._setup_plan(
                            source,
                            context,
                            directory,
                            environment,
                            checks,
                            resume=True,
                            create_environment=False,
                        )
                    checks.append(LaunchCheck("python-environment", "ok", f"使用项目环境：{interpreter}"))
                    return LaunchPlan(
                        self.id,
                        source,
                        source.parent,
                        (str(interpreter), str(source)),
                        str(interpreter),
                        checks=tuple(checks),
                    )
                if incomplete_marker.is_file():
                    return self._setup_plan(
                        source,
                        context,
                        directory,
                        environment,
                        checks,
                        resume=True,
                        create_environment=True,
                    )
                invalid_environments.append(environment)

        root = _project_root(source)
        environment = root / ".venv"
        if environment.exists():
            checks.append(
                LaunchCheck(
                    "invalid-environment",
                    "blocking",
                    f"现有环境缺少可用解释器，ToolDeck 不会覆盖：{environment}",
                )
            )
            return LaunchPlan(self.id, source, source.parent, (), checks=tuple(checks))
        if invalid_environments:
            checks.append(
                LaunchCheck(
                    "ignored-invalid-environment",
                    "warning",
                    "忽略了不完整的其他环境：" + ", ".join(str(path) for path in invalid_environments),
                )
            )
        return self._setup_plan(
            source,
            context,
            root,
            environment,
            checks,
            resume=False,
            create_environment=True,
        )


class ShellDetector:
    id = "shell"
    priority = 90

    def detect(self, source: Path, context: DetectionContext) -> LaunchPlan | None:
        if source.suffix.casefold() != ".sh":
            return None
        shebang = _shebang_parts(source)
        interpreter = _resolve_shebang_program(shebang, context)
        if shebang is not None and interpreter is None:
            return LaunchPlan(
                self.id,
                source,
                source.parent,
                (),
                checks=(LaunchCheck("missing-shebang", "blocking", "脚本 shebang 指定的解释器不可用"),),
            )
        if interpreter is None:
            interpreter = context.which("bash") or context.which("sh")
        if interpreter is None:
            return LaunchPlan(
                self.id,
                source,
                source.parent,
                (),
                checks=(LaunchCheck("missing-shell", "blocking", "找不到可执行该脚本的 Bash 或 sh"),),
            )
        return LaunchPlan(
            self.id,
            source,
            source.parent,
            (interpreter, str(source)),
            interpreter,
            checks=(LaunchCheck("shell", "ok", f"使用脚本解释器：{interpreter}"),),
        )


class PowerShellDetector:
    id = "powershell"
    priority = 90

    def detect(self, source: Path, context: DetectionContext) -> LaunchPlan | None:
        if source.suffix.casefold() != ".ps1":
            return None
        interpreter = context.which("pwsh") or context.which("powershell")
        if interpreter is None:
            return LaunchPlan(
                self.id,
                source,
                source.parent,
                (),
                checks=(LaunchCheck("missing-powershell", "blocking", "找不到 PowerShell 或 pwsh"),),
            )
        return LaunchPlan(
            self.id,
            source,
            source.parent,
            (interpreter, "-NoLogo", "-NoProfile", "-File", str(source)),
            interpreter,
            checks=(LaunchCheck("powershell", "ok", f"使用 PowerShell：{interpreter}"),),
        )


class BatchDetector:
    id = "batch"
    priority = 90

    def detect(self, source: Path, context: DetectionContext) -> LaunchPlan | None:
        if source.suffix.casefold() not in {".bat", ".cmd"}:
            return None
        if context.platform_name != "nt":
            return LaunchPlan(
                self.id,
                source,
                source.parent,
                (),
                checks=(LaunchCheck("platform", "blocking", "BAT/CMD 只能在 Windows 上直接运行"),),
            )
        comspec = os.environ.get("COMSPEC")
        interpreter = _resolve_program(comspec, context) if comspec else None
        interpreter = interpreter or context.which("cmd.exe") or context.which("cmd")
        if interpreter is None:
            return LaunchPlan(
                self.id,
                source,
                source.parent,
                (),
                checks=(LaunchCheck("missing-cmd", "blocking", "找不到 Windows 命令解释器 cmd.exe"),),
            )
        return LaunchPlan(
            self.id,
            source,
            source.parent,
            (interpreter, "/d", "/s", "/c", f'call "{source}"'),
            interpreter,
            checks=(LaunchCheck("batch", "ok", f"使用命令解释器：{interpreter}"),),
        )


class ExecutableDetector:
    id = "executable"
    priority = 10

    def detect(self, source: Path, context: DetectionContext) -> LaunchPlan | None:
        suffix = source.suffix.casefold()
        if suffix == ".exe" and context.platform_name != "nt":
            return LaunchPlan(
                self.id,
                source,
                source.parent,
                (),
                checks=(LaunchCheck("platform", "blocking", "Windows EXE 不能在当前平台直接运行"),),
            )
        if suffix != ".exe" and not _is_executable(source, context.platform_name):
            return None
        return LaunchPlan(
            self.id,
            source,
            source.parent,
            (str(source),),
            checks=(LaunchCheck("executable", "ok", "已识别为本机可执行程序"),),
        )


BUILTIN_DETECTORS: tuple[LaunchDetector, ...] = (
    PythonDetector(),
    ShellDetector(),
    PowerShellDetector(),
    BatchDetector(),
    ExecutableDetector(),
)


def _launch_plan_contract_error(plan: LaunchPlan, detector_id: str, source: Path) -> str | None:
    if plan.detector != detector_id:
        return "LaunchPlan.detector 必须与 detector.id 一致"
    if not isinstance(plan.source, Path) or not _same_path(plan.source, source):
        return "LaunchPlan.source 必须是用户选择的入口文件"
    if not isinstance(plan.cwd, Path):
        return "LaunchPlan.cwd 必须是 Path"
    if not isinstance(plan.argv, tuple) or any(not isinstance(value, str) or not value for value in plan.argv):
        return "LaunchPlan.argv 必须是非空字符串元组"
    if not isinstance(plan.interpreter, str) or not isinstance(plan.managed_environment, bool):
        return "LaunchPlan 解释器字段无效"
    if not isinstance(plan.readiness, ReadinessConfig):
        return "LaunchPlan.readiness 必须是 ReadinessConfig"
    if not isinstance(plan.checks, tuple) or any(
        not isinstance(check, LaunchCheck) or check.level not in {"ok", "warning", "blocking"}
        for check in plan.checks
    ):
        return "LaunchPlan.checks 必须是 LaunchCheck 元组"
    if not plan.argv and not any(check.level == "blocking" for check in plan.checks):
        return "没有阻断检查的 LaunchPlan.argv 不能为空"
    setup = plan.setup
    if setup is None:
        return None
    if not isinstance(setup, SetupPlan) or setup.detector != detector_id:
        return "LaunchPlan.setup 必须是同一检测器的 SetupPlan"
    if not isinstance(setup.project_root, Path) or not isinstance(setup.environment_dir, Path):
        return "SetupPlan 路径字段必须是 Path"
    if not isinstance(setup.commands, tuple) or any(
        not isinstance(command, SetupCommand)
        or not isinstance(command.argv, tuple)
        or not command.argv
        or any(not isinstance(value, str) or not value for value in command.argv)
        or not isinstance(command.cwd, Path)
        or not isinstance(command.network, bool)
        for command in setup.commands
    ):
        return "SetupPlan.commands 必须只包含声明式 SetupCommand"
    if not isinstance(setup.expected_paths, tuple) or any(not isinstance(path, Path) for path in setup.expected_paths):
        return "SetupPlan.expected_paths 必须是 Path 元组"
    if not isinstance(setup.summary, str) or not isinstance(setup.allow_existing_environment, bool):
        return "SetupPlan 元数据无效"
    return None


def discover_launch_detectors(
    *,
    entry_points_provider: Callable[[], object] | None = None,
) -> tuple[tuple[LaunchDetector, ...], tuple[LaunchCheck, ...]]:
    detectors: dict[str, LaunchDetector] = {detector.id: detector for detector in BUILTIN_DETECTORS}
    priorities = {detector.id: int(detector.priority) for detector in BUILTIN_DETECTORS}
    issues: list[LaunchCheck] = []
    provider = entry_points_provider or metadata.entry_points
    try:
        discovered = provider()
        selected: Iterable[object] = (
            discovered.select(group=ENTRY_POINT_GROUP)
            if hasattr(discovered, "select")
            else discovered.get(ENTRY_POINT_GROUP, ())
        )
    except Exception as exc:
        return tuple(detectors.values()), (LaunchCheck("plugin-discovery", "warning", f"启动检测器发现失败：{exc}"),)
    for entry_point in selected:
        name = str(getattr(entry_point, "name", "")).strip()
        if not name or name in detectors:
            continue
        try:
            loaded = entry_point.load()
            detector = loaded() if isinstance(loaded, type) else loaded
            detector_id = str(getattr(detector, "id", "")).strip()
            if detector_id != name or not callable(getattr(detector, "detect", None)):
                raise TypeError("入口名称必须与 detector.id 一致并提供 detect()")
            priority = getattr(detector, "priority", 0)
            if isinstance(priority, bool) or not isinstance(priority, int):
                raise TypeError("detector.priority 必须是整数")
            detectors[name] = detector
            priorities[name] = priority
        except Exception as exc:
            issues.append(LaunchCheck("plugin-load", "warning", f"检测器 {name} 未载入：{exc}"))
    ordered_ids = sorted(detectors, key=lambda detector_id: priorities[detector_id], reverse=True)
    return tuple(detectors[detector_id] for detector_id in ordered_ids), tuple(issues)


def analyze_launch(
    source: Path,
    *,
    platform_name: str | None = None,
    tooldeck_python: Path | None = None,
    which: Callable[[str], str | None] = shutil.which,
    detectors: Iterable[LaunchDetector] | None = None,
    entry_points_provider: Callable[[], object] | None = None,
) -> LaunchAnalysis:
    selected = Path(source).expanduser().resolve()
    checks: list[LaunchCheck] = []
    if not selected.is_file():
        return LaunchAnalysis(selected, None, (LaunchCheck("source", "blocking", f"入口文件不存在：{selected}"),))
    context = DetectionContext(platform_name or os.name, (tooldeck_python or Path(sys.executable)).absolute(), which)
    if detectors is None:
        detected, plugin_issues = discover_launch_detectors(entry_points_provider=entry_points_provider)
        checks.extend(plugin_issues)
    else:
        detected = tuple(detectors)
    for detector in detected:
        try:
            detector_id = str(getattr(detector, "id", "?"))
        except Exception:
            detector_id = "?"
        try:
            plan = detector.detect(selected, context)
        except Exception as exc:
            checks.append(LaunchCheck("detector-error", "warning", f"检测器 {detector_id} 失败：{exc}"))
            continue
        if plan is not None:
            if not isinstance(plan, LaunchPlan):
                checks.append(
                    LaunchCheck(
                        "detector-contract",
                        "warning",
                        f"检测器 {detector_id} 返回了无效计划",
                    )
                )
                continue
            try:
                contract_error = _launch_plan_contract_error(plan, detector_id, selected)
            except Exception as exc:
                contract_error = f"契约验证失败：{exc}"
            if contract_error is not None:
                checks.append(
                    LaunchCheck(
                        "detector-contract",
                        "warning",
                        f"检测器 {detector_id} 返回了无效计划：{contract_error}",
                    )
                )
                continue
            checks.extend(plan.checks)
            return LaunchAnalysis(selected, plan, tuple(checks))
    checks.append(LaunchCheck("unsupported", "blocking", f"暂不支持此文件类型：{selected.name}"))
    return LaunchAnalysis(selected, None, tuple(checks))


def _program_check(value: str, label: str, *, platform_name: str, which: Callable[[str], str | None]) -> LaunchCheck:
    expanded = os.path.expanduser(value)
    path = Path(expanded)
    separators = tuple(separator for separator in (os.path.sep, os.path.altsep) if separator)
    if path.is_absolute() or any(separator in expanded for separator in separators):
        valid = _is_executable(path, platform_name)
    else:
        valid = which(expanded) is not None
    return LaunchCheck(label, "ok" if valid else "blocking", f"{label} 可用：{value}" if valid else f"{label} 不可执行：{value}")


def _loopback_health_url(value: str) -> bool:
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
        return False
    host = (parsed.hostname or "").casefold()
    if host in {"localhost", "0.0.0.0"}:
        return port is None or 1 <= port <= 65535
    try:
        return ipaddress.ip_address(host).is_loopback and (port is None or 1 <= port <= 65535)
    except ValueError:
        return False


def preflight_tool(
    tool: ToolConfig,
    *,
    platform_name: str | None = None,
    tooldeck_python: Path | None = None,
    which: Callable[[str], str | None] = shutil.which,
) -> PreflightReport:
    selected_platform = platform_name or os.name
    selected_tooldeck_python = (tooldeck_python or Path(sys.executable)).absolute()
    checks: list[LaunchCheck] = []
    uses_tooldeck_python = False
    cwd = Path(tool.cwd).expanduser()
    checks.append(
        LaunchCheck("cwd", "ok" if cwd.is_dir() else "blocking", f"工作目录可用：{cwd}" if cwd.is_dir() else f"工作目录不存在：{cwd}")
    )
    if tool.launch is None:
        checks.append(_program_check(tool.shell, "Shell", platform_name=selected_platform, which=which))
    else:
        source = Path(tool.launch.source).expanduser()
        checks.append(
            LaunchCheck("source", "ok" if source.is_file() else "blocking", f"入口文件可用：{source}" if source.is_file() else f"入口文件不存在：{source}")
        )
        if not tool.launch.argv:
            checks.append(LaunchCheck("argv", "blocking", "结构化启动参数不能为空"))
        else:
            checks.append(_program_check(tool.launch.argv[0], "启动程序", platform_name=selected_platform, which=which))
            if _same_path(tool.launch.argv[0], selected_tooldeck_python):
                checks.append(LaunchCheck("tooldeck-python", "blocking", "拒绝使用 ToolDeck 自身 Python 解释器"))
                uses_tooldeck_python = True
        if tool.launch.interpreter:
            checks.append(_program_check(tool.launch.interpreter, "解释器", platform_name=selected_platform, which=which))
            if _same_path(tool.launch.interpreter, selected_tooldeck_python) and not uses_tooldeck_python:
                checks.append(LaunchCheck("tooldeck-python", "blocking", "拒绝使用 ToolDeck 自身 Python 解释器"))
        if tool.launch.detector == "batch" and selected_platform != "nt":
            checks.append(LaunchCheck("platform", "blocking", "BAT/CMD 配置不能在当前平台启动"))
        if tool.launch.detector == "executable" and source.suffix.casefold() == ".exe" and selected_platform != "nt":
            checks.append(LaunchCheck("platform", "blocking", "Windows EXE 配置不能在当前平台启动"))
    readiness = tool.readiness
    if readiness.mode not in {"auto", "process", "http", "tcp"}:
        checks.append(LaunchCheck("readiness-mode", "blocking", "未知的就绪检查方式"))
    if readiness.mode == "http" and not readiness.health_url:
        checks.append(LaunchCheck("health-url", "blocking", "HTTP 就绪检查缺少本地健康地址"))
    if readiness.mode == "tcp" and readiness.health_port is None:
        checks.append(LaunchCheck("health-port", "blocking", "TCP 就绪检查缺少本地端口"))
    if readiness.health_port is not None and (
        isinstance(readiness.health_port, bool)
        or not isinstance(readiness.health_port, int)
        or not 1 <= readiness.health_port <= 65535
    ):
        checks.append(LaunchCheck("health-port", "blocking", "TCP 就绪端口必须在 1 到 65535 之间"))
    if readiness.health_url and not _loopback_health_url(readiness.health_url):
        checks.append(LaunchCheck("health-url", "blocking", "健康检查只允许 localhost 或回环地址"))
    return PreflightReport(tuple(checks))


class SetupCancellationError(RuntimeError):
    """A setup process tree could not be terminated within its deadline."""


def _terminate_setup_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            command = ["taskkill", "/PID", str(process.pid), "/T", "/F"]
            result = subprocess.run(
                command, stdin=subprocess.DEVNULL, capture_output=True,
                timeout=3.0, check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if result.returncode != 0 and process.poll() is None:
                raise SetupCancellationError(
                    f"取消环境准备失败：{command!r}，退出码 {result.returncode}，"
                    f"stdout={result.stdout!r}，stderr={result.stderr!r}"
                )
        else:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=0.25)
            except subprocess.TimeoutExpired:
                pass
            if proc_group_alive(process.pid):
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        process.wait(timeout=1.0)
        if os.name != "nt" and proc_group_alive(process.pid):
            raise SetupCancellationError(f"取消环境准备失败：进程组 {process.pid} 仍存活")
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SetupCancellationError(f"无法终止环境准备进程树 PID {process.pid}：{exc}") from exc


def execute_setup(
    plan: SetupPlan,
    log_path: Path,
    *,
    confirmed: bool,
    cancel_event: threading.Event | None = None,
    progress: Callable[[int, int, str], None] | None = None,
    started: Callable[[Path], None] | None = None,
) -> PreparationResult:
    if not confirmed:
        return PreparationResult(False, False, None, log_path, "环境准备必须由用户明确确认")
    if cancel_event is not None and cancel_event.is_set():
        return PreparationResult(False, True, None, log_path, "环境准备已取消")
    lock_path = _setup_incomplete_marker(plan.environment_dir).with_suffix(".lock")
    with exclusive_file_lock(lock_path, 2.0, cancel_event):
        return _execute_setup_locked(plan, log_path, cancel_event, progress, started)


def _execute_setup_locked(
    plan: SetupPlan,
    log_path: Path,
    cancel_event: threading.Event | None,
    progress: Callable[[int, int, str], None] | None,
    started: Callable[[Path], None] | None,
) -> PreparationResult:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    total = len(plan.commands)
    with log_path.open("ab", buffering=0) as output:
        output.write(f"ToolDeck setup: {plan.summary}\nTarget: {plan.environment_dir}\n".encode())
        if started is not None:
            started(log_path)
        incomplete_marker = _setup_incomplete_marker(plan.environment_dir) if plan.detector == "python" else None
        marker_existed = bool(incomplete_marker and incomplete_marker.is_file())
        if plan.environment_dir.exists() and not (plan.allow_existing_environment and marker_existed):
            message = f"目标环境已经存在，ToolDeck 不会覆盖：{plan.environment_dir}"
            output.write((message + "\n").encode())
            return PreparationResult(False, False, None, log_path, message)
        if incomplete_marker is not None:
            try:
                incomplete_marker.parent.mkdir(parents=True, exist_ok=True)
                incomplete_marker.write_text(
                    f"target={plan.environment_dir}\nlog={log_path}\n",
                    encoding="utf-8",
                )
            except OSError as exc:
                message = f"无法记录环境准备状态：{exc}"
                output.write((message + "\n").encode())
                return PreparationResult(False, False, None, log_path, message)
        child_environment = dict(os.environ)
        isolated_names = {"virtual_env", "uv_project_environment", "pythonhome", "__pyvenv_launcher__"}
        for name in tuple(child_environment):
            if name.casefold() in isolated_names:
                child_environment.pop(name, None)
        for index, command in enumerate(plan.commands, 1):
            if cancel_event is not None and cancel_event.is_set():
                return PreparationResult(False, True, None, log_path, "环境准备已取消")
            display = command.display
            output.write(f"\n[{index}/{total}] $ {display}\n".encode())
            if progress is not None:
                progress(index, total, display)
            options: dict[str, object] = {}
            if os.name == "nt":
                options["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0)
            else:
                options["start_new_session"] = True
            try:
                process = subprocess.Popen(
                    list(command.argv),
                    cwd=command.cwd,
                    stdin=subprocess.DEVNULL,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                    env=child_environment,
                    close_fds=True,
                    **options,
                )
            except OSError as exc:
                output.write(f"launch failed: {exc}\n".encode())
                return PreparationResult(False, False, None, log_path, f"无法执行环境准备：{exc}")
            while process.poll() is None:
                if cancel_event is not None and cancel_event.is_set():
                    try:
                        _terminate_setup_process(process)
                    except SetupCancellationError as exc:
                        output.write((str(exc) + "\n").encode())
                        return PreparationResult(False, False, process.returncode, log_path, str(exc))
                    output.write(b"cancelled\n")
                    return PreparationResult(False, True, process.returncode, log_path, "环境准备已取消")
                time.sleep(0.1)
            if process.returncode != 0:
                output.write(f"failed with code {process.returncode}\n".encode())
                return PreparationResult(False, False, process.returncode, log_path, f"环境准备失败，退出码 {process.returncode}")
        missing = [path for path in plan.expected_paths if not path.is_file()]
        if missing:
            message = "环境准备完成但缺少预期文件：" + ", ".join(str(path) for path in missing)
            output.write((message + "\n").encode())
            return PreparationResult(False, False, 0, log_path, message)
        if plan.detector == "python":
            interpreter = _environment_python(plan.environment_dir, os.name)
            try:
                validation = subprocess.run(
                    [str(interpreter), "-I", "-X", "utf8", "-c", "import sys; print(sys.prefix)"],
                    stdin=subprocess.DEVNULL, capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=3.0, check=False,
                    env=child_environment,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                return PreparationResult(False, False, None, log_path, f"项目解释器验证失败：{exc}")
            if validation.returncode != 0 or Path(validation.stdout.strip()).resolve() != plan.environment_dir.resolve():
                message = f"项目解释器身份验证失败：{interpreter}，退出码 {validation.returncode}，stdout={validation.stdout!r}，stderr={validation.stderr!r}"
                output.write((message + "\n").encode())
                return PreparationResult(False, False, validation.returncode, log_path, message)
        if incomplete_marker is not None:
            try:
                incomplete_marker.unlink(missing_ok=True)
            except OSError as exc:
                message = f"环境已准备，但无法提交完成状态：{exc}"
                output.write((message + "\n").encode())
                return PreparationResult(False, False, 0, log_path, message)
        output.write(b"setup complete\n")
    return PreparationResult(True, False, 0, log_path, "环境准备完成")
