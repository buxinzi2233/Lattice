from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

import pytest

from tooldeck.config import ConfigError, LaunchConfig, ReadinessConfig, ToolConfig
from tooldeck.drafts import launch_patch_for_analysis
from tooldeck.launchers import (
    BatchDetector,
    ExecutableDetector,
    LaunchPlan,
    PowerShellDetector,
    ShellDetector,
    SetupCommand,
    SetupPlan,
    analyze_launch,
    discover_launch_detectors,
    execute_setup,
    preflight_tool,
    _setup_incomplete_marker,
)


def executable(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def test_python_detector_uses_nearby_environment_without_setup(tmp_path):
    source = tmp_path / "project" / "src" / "main.py"
    source.parent.mkdir(parents=True)
    source.write_text("print('ok')\n", encoding="utf-8")
    interpreter = executable(tmp_path / "project" / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python"))

    analysis = analyze_launch(source, tooldeck_python=tmp_path / "tooldeck-python", detectors=None)

    assert not analysis.blocking
    assert analysis.plan is not None
    assert analysis.plan.argv == (str(interpreter), str(source))
    assert analysis.plan.setup is None


def test_python_detector_never_falls_back_to_tooldeck_python_and_declares_setup(tmp_path):
    root = tmp_path / "project"
    source = root / "main.py"
    source.parent.mkdir()
    source.write_text("print('ok')\n", encoding="utf-8")
    (root / "requirements.txt").write_text("example==1\n", encoding="utf-8")
    tooldeck_python = executable(tmp_path / "tooldeck" / "python")
    system_python = executable(tmp_path / "system" / "python3")

    analysis = analyze_launch(
        source,
        tooldeck_python=tooldeck_python,
        which=lambda name: str(tooldeck_python) if name == "python" else str(system_python) if name == "python3" else None,
    )

    assert analysis.plan is not None
    assert analysis.plan.setup is not None
    assert analysis.plan.interpreter == str(root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python"))
    assert str(tooldeck_python) not in analysis.plan.argv
    assert analysis.plan.setup.commands[0].argv[0] == str(system_python)
    assert analysis.plan.setup.commands[1].network is True


def test_python_detector_refuses_to_overwrite_invalid_project_environment(tmp_path):
    root = tmp_path / "project"
    source = root / "main.py"
    source.parent.mkdir()
    source.write_text("print('ok')\n", encoding="utf-8")
    (root / ".venv").mkdir()

    analysis = analyze_launch(source, tooldeck_python=tmp_path / "tooldeck-python", which=lambda _name: "/usr/bin/python3")

    assert analysis.blocking
    assert analysis.plan is not None
    assert analysis.plan.setup is None
    assert any(check.code == "invalid-environment" for check in analysis.checks)


def test_python_detector_blocks_when_only_tooldeck_python_is_available(tmp_path):
    source = tmp_path / "project" / "main.py"
    source.parent.mkdir()
    source.write_text("print('ok')\n", encoding="utf-8")
    tooldeck_python = executable(tmp_path / "tooldeck" / "python")

    analysis = analyze_launch(
        source,
        tooldeck_python=tooldeck_python,
        which=lambda name: str(tooldeck_python) if name in {"python", "python3"} else None,
    )

    assert analysis.blocking
    assert any(check.code == "missing-python" for check in analysis.checks)


def test_python_detector_rejects_hardlink_to_tooldeck_python(tmp_path):
    source = tmp_path / "project" / "main.py"
    source.parent.mkdir()
    source.write_text("print('ok')\n", encoding="utf-8")
    tooldeck_python = executable(tmp_path / "tooldeck" / "python")
    alias = tmp_path / "system" / "python3"
    alias.parent.mkdir()
    alias.hardlink_to(tooldeck_python)

    analysis = analyze_launch(
        source,
        tooldeck_python=tooldeck_python,
        which=lambda name: str(alias) if name in {"python", "python3"} else None,
    )

    assert analysis.blocking
    assert any(check.code == "missing-python" for check in analysis.checks)


def test_python_detector_prefers_frozen_uv_sync_when_lock_is_present(tmp_path):
    root = tmp_path / "project with space"
    source = root / "启动.py"
    root.mkdir()
    source.write_text("print('ok')\n", encoding="utf-8")
    (root / "pyproject.toml").write_text("[project]\nname='demo'\nversion='0'\n", encoding="utf-8")
    (root / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    uv = executable(tmp_path / "bin" / "uv")
    python = executable(tmp_path / "bin" / "python3")

    analysis = analyze_launch(
        source,
        tooldeck_python=tmp_path / "tooldeck-python",
        which=lambda name: str(uv) if name == "uv" else str(python) if name == "python3" else None,
    )

    assert analysis.plan is not None and analysis.plan.setup is not None
    assert analysis.plan.setup.commands[0].argv == (
        str(uv),
        "sync",
        "--frozen",
        "--project",
        str(root),
    )
    assert analysis.plan.setup.requires_network is True


def test_python_detector_resumes_tooldeck_environment_after_incomplete_setup(tmp_path):
    root = tmp_path / "project"
    source = root / "main.py"
    root.mkdir()
    source.write_text("print('ok')\n", encoding="utf-8")
    (root / "requirements.txt").write_text("example==1\n", encoding="utf-8")
    system_python = executable(tmp_path / "system" / "python3")
    initial = analyze_launch(
        source,
        tooldeck_python=tmp_path / "tooldeck-python",
        which=lambda name: str(system_python) if name == "python3" else None,
    )
    assert initial.plan is not None and initial.plan.setup is not None
    marker = _setup_incomplete_marker(initial.plan.setup.environment_dir)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("incomplete\n", encoding="utf-8")
    interpreter = executable(root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python"))

    resumed = analyze_launch(
        source,
        tooldeck_python=tmp_path / "tooldeck-python",
        which=lambda name: str(system_python) if name == "python3" else None,
    )

    assert resumed.plan is not None and resumed.plan.setup is not None
    assert resumed.plan.setup.allow_existing_environment is True
    assert resumed.plan.setup.commands[0].argv[:4] == (
        str(interpreter),
        "-m",
        "pip",
        "install",
    )
    assert any(check.code == "environment-resume" for check in resumed.checks)


def test_shell_detector_handles_unicode_space_path_and_env_split_shebang(tmp_path):
    source = tmp_path / "脚本 目录" / "启动.sh"
    source.parent.mkdir()
    source.write_text("#!/usr/bin/env -S bash -e\necho ready\n", encoding="utf-8")

    analysis = analyze_launch(
        source,
        detectors=[ShellDetector()],
        tooldeck_python=tmp_path / "tooldeck-python",
        which=lambda name: "/bin/bash" if name == "bash" else None,
    )

    assert not analysis.blocking
    assert analysis.plan is not None
    assert analysis.plan.argv == ("/bin/bash", str(source))


def test_shell_detector_blocks_missing_shebang_interpreter(tmp_path):
    source = tmp_path / "run.sh"
    source.write_text("#!/missing/custom-shell\necho ready\n", encoding="utf-8")

    analysis = analyze_launch(
        source,
        detectors=[ShellDetector()],
        which=lambda name: "/bin/bash" if name == "bash" else None,
    )

    assert analysis.blocking
    assert any(check.code == "missing-shebang" for check in analysis.checks)


def test_native_executable_permission_and_platform_rules(tmp_path):
    native = tmp_path / "工具 with space"
    native.write_text("#!/bin/sh\n", encoding="utf-8")

    denied = analyze_launch(native, platform_name="posix", detectors=[ExecutableDetector()])
    native.chmod(0o755)
    allowed = analyze_launch(native, platform_name="posix", detectors=[ExecutableDetector()])
    windows_exe = tmp_path / "工具 with space.exe"
    windows_exe.write_bytes(b"")
    windows = analyze_launch(windows_exe, platform_name="nt", detectors=[ExecutableDetector()])

    if os.name != "nt":
        assert denied.blocking
    assert allowed.plan is not None and allowed.plan.argv == (str(native),)
    assert windows.plan is not None and windows.plan.argv == (str(windows_exe),)


def test_core_windows_detectors_build_argv_without_shell_strings(tmp_path):
    batch = tmp_path / "启动 tool.cmd"
    powershell = tmp_path / "启动 tool.ps1"
    program = tmp_path / "工具 app.exe"
    for path in (batch, powershell, program):
        path.write_text("", encoding="utf-8")

    batch_result = analyze_launch(batch, platform_name="nt", detectors=[BatchDetector()], which=lambda _name: r"C:\Windows\cmd.exe")
    ps_result = analyze_launch(powershell, platform_name="nt", detectors=[PowerShellDetector()], which=lambda _name: r"C:\PowerShell\pwsh.exe")
    exe_result = analyze_launch(program, platform_name="nt", detectors=[ExecutableDetector()])

    assert batch_result.plan is not None and str(batch) in batch_result.plan.argv[-1]
    assert ps_result.plan is not None and "-File" in ps_result.plan.argv
    assert exe_result.plan is not None and exe_result.plan.argv == (str(program),)


def test_windows_script_detectors_report_missing_interpreters(tmp_path, monkeypatch):
    monkeypatch.delenv("COMSPEC", raising=False)
    batch = tmp_path / "start.cmd"
    powershell = tmp_path / "start.ps1"
    batch.write_text("@echo off\n", encoding="utf-8")
    powershell.write_text("Write-Output ready\n", encoding="utf-8")

    batch_result = analyze_launch(batch, platform_name="nt", detectors=[BatchDetector()], which=lambda _name: None)
    ps_result = analyze_launch(powershell, platform_name="nt", detectors=[PowerShellDetector()], which=lambda _name: None)

    assert any(check.code == "missing-cmd" for check in batch_result.checks)
    assert any(check.code == "missing-powershell" for check in ps_result.checks)


def test_detector_plugin_failures_are_isolated():
    class EntryPoint:
        name = "broken"

        def load(self):
            raise RuntimeError("bad plugin")

    class EntryPoints(list):
        def select(self, **_kwargs):
            return self

    detectors, issues = discover_launch_detectors(entry_points_provider=lambda: EntryPoints([EntryPoint()]))

    assert any(detector.id == "python" for detector in detectors)
    assert any("broken" in issue.message for issue in issues)


def test_detector_plugin_with_invalid_priority_is_isolated():
    class BrokenDetector:
        id = "broken-priority"
        priority = "highest"

        def detect(self, _source, _context):
            return None

    class EntryPoint:
        name = "broken-priority"

        def load(self):
            return BrokenDetector()

    class EntryPoints(list):
        def select(self, **_kwargs):
            return self

    detectors, issues = discover_launch_detectors(entry_points_provider=lambda: EntryPoints([EntryPoint()]))

    assert all(detector.id != "broken-priority" for detector in detectors)
    assert any("priority" in issue.message for issue in issues)


def test_invalid_detector_result_cannot_bypass_launch_plan_contract(tmp_path):
    source = tmp_path / "custom.tool"
    source.write_text("data", encoding="utf-8")

    class InvalidDetector:
        id = "invalid"
        priority = 100

        def detect(self, _source, _context):
            return {"argv": ["unsafe"]}

    analysis = analyze_launch(source, detectors=[InvalidDetector()])

    assert analysis.blocking
    assert any(check.code == "detector-contract" for check in analysis.checks)


def test_malformed_declarative_setup_plan_is_isolated(tmp_path):
    source = tmp_path / "custom.tool"
    source.write_text("data", encoding="utf-8")

    class InvalidSetupDetector:
        id = "invalid-setup"
        priority = 100

        def detect(self, selected, _context):
            return LaunchPlan(
                self.id,
                selected,
                selected.parent,
                ("runner",),
                setup={"command": "not declarative"},
            )

    analysis = analyze_launch(source, detectors=[InvalidSetupDetector()])

    assert analysis.blocking
    assert any(check.code == "detector-contract" for check in analysis.checks)


def test_blocking_detector_result_cannot_become_a_draft(tmp_path):
    source = tmp_path / "project" / "main.py"
    source.parent.mkdir()
    source.write_text("print('ok')\n", encoding="utf-8")
    (source.parent / ".venv").mkdir()
    analysis = analyze_launch(source, which=lambda _name: "/usr/bin/python3")

    with pytest.raises(ConfigError, match="不会覆盖"):
        launch_patch_for_analysis(analysis, set())


def test_preflight_blocks_missing_source_and_tooldeck_interpreter(tmp_path):
    tooldeck_python = executable(tmp_path / "tooldeck" / "python")
    tool = ToolConfig(
        "demo",
        "Demo",
        "generated",
        str(tmp_path),
        launch=LaunchConfig(
            "argv",
            "python",
            str(tmp_path / "missing.py"),
            (str(tooldeck_python), str(tmp_path / "missing.py")),
            str(tooldeck_python),
        ),
    )

    report = preflight_tool(tool, tooldeck_python=tooldeck_python)

    assert report.blocking
    assert {check.code for check in report.checks if check.level == "blocking"} >= {"source", "tooldeck-python"}


def test_preflight_checks_argv_program_for_tooldeck_python_without_metadata(tmp_path):
    tooldeck_python = executable(tmp_path / "tooldeck" / "python")
    source = tmp_path / "main.py"
    source.write_text("print('ok')\n", encoding="utf-8")
    tool = ToolConfig(
        "demo",
        "Demo",
        "generated",
        str(tmp_path),
        launch=LaunchConfig("argv", "python", str(source), (str(tooldeck_python), str(source))),
    )

    report = preflight_tool(tool, tooldeck_python=tooldeck_python)

    assert any(check.code == "tooldeck-python" and check.level == "blocking" for check in report.checks)


def test_preflight_rejects_remote_health_endpoints(tmp_path):
    tool = ToolConfig(
        "remote-health",
        "Remote health",
        "echo ready",
        str(tmp_path),
        readiness=ReadinessConfig("http", health_url="https://example.com/health"),
    )

    report = preflight_tool(tool)

    assert any(check.code == "health-url" and check.level == "blocking" for check in report.checks)


@pytest.mark.parametrize(
    ("readiness", "code"),
    [
        (ReadinessConfig("http"), "health-url"),
        (ReadinessConfig("tcp"), "health-port"),
        (ReadinessConfig("tcp", health_port=70000), "health-port"),
    ],
)
def test_preflight_rejects_incomplete_readiness(readiness, code, tmp_path):
    tool = ToolConfig("bad-readiness", "Bad readiness", "echo ready", str(tmp_path), readiness=readiness)

    report = preflight_tool(tool)

    assert any(check.code == code and check.level == "blocking" for check in report.checks)


def test_setup_requires_confirmation_and_writes_disk_log(tmp_path):
    expected = tmp_path / "environment" / "ready"
    command = SetupCommand(
        (
            sys.executable,
            "-c",
            f"from pathlib import Path; p=Path({str(expected)!r}); p.parent.mkdir(); p.write_text('ok')",
        ),
        tmp_path,
    )
    plan = SetupPlan("test", tmp_path, expected.parent, (command,), (expected,), "test setup")
    denied_log = tmp_path / "denied.log"

    denied = execute_setup(plan, denied_log, confirmed=False)
    completed = execute_setup(plan, tmp_path / "setup.log", confirmed=True)

    assert denied.success is False
    assert not denied_log.exists()
    assert completed.success is True
    assert expected.read_text(encoding="utf-8") == "ok"
    assert "setup complete" in completed.log_path.read_text(encoding="utf-8")


def test_setup_refuses_environment_that_appeared_after_detection(tmp_path):
    environment = tmp_path / ".venv"
    environment.mkdir()
    marker = tmp_path / "command-ran"
    command = SetupCommand(
        (sys.executable, "-c", f"from pathlib import Path; Path({str(marker)!r}).write_text('bad')"),
        tmp_path,
    )
    plan = SetupPlan("python", tmp_path, environment, (command,), (environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python"),), "setup")

    result = execute_setup(plan, tmp_path / "existing.log", confirmed=True)

    assert result.success is False
    assert "不会覆盖" in result.message
    assert not marker.exists()
    assert result.log_path.is_file()


def test_setup_reports_dependency_command_failure(tmp_path):
    environment = tmp_path / ".venv"
    marker = _setup_incomplete_marker(environment)
    plan = SetupPlan(
        "python",
        tmp_path,
        environment,
        (SetupCommand((sys.executable, "-c", "import sys; print('install failed'); sys.exit(9)"), tmp_path, True),),
        (environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python"),),
        "dependency setup",
    )

    result = execute_setup(plan, tmp_path / "failed.log", confirmed=True)

    assert result.success is False
    assert result.return_code == 9
    assert "install failed" in result.log_path.read_text(encoding="utf-8")
    assert marker.is_file()


def test_setup_running_command_can_be_cancelled(tmp_path):
    environment = tmp_path / ".venv"
    cancelled = threading.Event()
    timer = threading.Timer(0.15, cancelled.set)
    plan = SetupPlan(
        "python",
        tmp_path,
        environment,
        (SetupCommand((sys.executable, "-c", "import time; time.sleep(60)"), tmp_path),),
        (environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python"),),
        "cancel running setup",
    )

    started_at = time.monotonic()
    timer.start()
    try:
        result = execute_setup(plan, tmp_path / "cancel-running.log", confirmed=True, cancel_event=cancelled)
    finally:
        timer.cancel()

    assert result.cancelled is True
    assert time.monotonic() - started_at < 5


def test_setup_reports_log_path_when_execution_starts(tmp_path):
    environment = tmp_path / ".venv"
    expected = environment / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    marker = _setup_incomplete_marker(environment)
    plan = SetupPlan(
        "python",
        tmp_path,
        environment,
        (
            SetupCommand(
                (
                    sys.executable,
                    "-c",
                    f"import venv; venv.EnvBuilder(with_pip=False).create({str(environment)!r})",
                ),
                tmp_path,
            ),
        ),
        (expected,),
        "started callback",
    )
    reported: list[Path] = []

    result = execute_setup(plan, tmp_path / "started.log", confirmed=True, started=reported.append)

    assert result.success is True
    assert reported == [result.log_path]
    assert not marker.exists()


def test_setup_does_not_inherit_parent_virtual_environment_targets(tmp_path, monkeypatch):
    environment = tmp_path / ".venv"
    expected = environment / "environment.txt"
    monkeypatch.setenv("VIRTUAL_ENV", "/wrong/venv")
    monkeypatch.setenv("UV_PROJECT_ENVIRONMENT", "/wrong/uv-environment")
    code = (
        "import os, venv; from pathlib import Path; "
        f"venv.EnvBuilder(with_pip=False).create({str(environment)!r}); "
        f"p=Path({str(expected)!r}); "
        "p.write_text(os.environ.get('VIRTUAL_ENV', '') + '|' + os.environ.get('UV_PROJECT_ENVIRONMENT', ''))"
    )
    plan = SetupPlan(
        "python",
        tmp_path,
        environment,
        (SetupCommand((sys.executable, "-c", code), tmp_path),),
        (expected,),
        "isolated environment",
    )

    result = execute_setup(plan, tmp_path / "isolated.log", confirmed=True)

    assert result.success is True
    assert expected.read_text(encoding="utf-8") == "|"


def test_setup_honors_preexisting_cancellation_without_writing_config(tmp_path):
    cancelled = threading.Event()
    cancelled.set()
    expected = tmp_path / "never"
    plan = SetupPlan(
        "test",
        tmp_path,
        tmp_path / ".venv",
        (SetupCommand((sys.executable, "-c", "pass"), tmp_path),),
        (expected,),
        "cancelled setup",
    )

    result = execute_setup(plan, tmp_path / "cancel.log", confirmed=True, cancel_event=cancelled)

    assert result.cancelled is True
    assert not expected.exists()


def test_structured_launch_and_readiness_values_are_preserved(tmp_path):
    source = executable(tmp_path / "run.sh")
    launch = LaunchConfig("argv", "shell", str(source), (str(source),))
    readiness = ReadinessConfig("tcp", 1.5, 45, health_port=8765)
    tool = ToolConfig("demo", "Demo", str(source), str(tmp_path), launch=launch, readiness=readiness)

    plan = LaunchPlan("shell", source, tmp_path, (str(source),))

    assert plan.launch_config().argv == (str(source),)
    assert tool.readiness.health_port == 8765
