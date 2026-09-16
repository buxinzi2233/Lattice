from __future__ import annotations

import tempfile

import os
import venv
from pathlib import Path

import pytest

from tooldeck.application import APPLICATION_API_VERSION, ToolDeckApplication
from tooldeck.config import ConfigError, LaunchConfig, ToolConfig
from tooldeck.procs import ProcessError, ToolStatus


class RecordingRuntime:
    def __init__(self) -> None:
        self.statuses: dict[str, ToolStatus] = {}
        self.started: list[str] = []
        self.stopped: list[str] = []
        self.ticks = 0

    def tick(self) -> None:
        self.ticks += 1

    def status(self, tool_id: str) -> ToolStatus:
        return self.statuses.get(tool_id, ToolStatus(tool_id, "stopped"))

    def start(self, tool: ToolConfig) -> ToolStatus:
        self.started.append(tool.id)
        status = ToolStatus(tool.id, "running", pid=7000 + len(self.started))
        self.statuses[tool.id] = status
        return status

    def stop_begin(self, tool: ToolConfig) -> ToolStatus:
        self.stopped.append(tool.id)
        status = ToolStatus(tool.id, "stopping", pid=self.status(tool.id).pid)
        self.statuses[tool.id] = status
        return status

    def stop_blocking(self, tool: ToolConfig) -> ToolStatus:
        self.stopped.append(tool.id)
        status = ToolStatus(tool.id, "stopped")
        self.statuses[tool.id] = status
        return status

    def stop_all_begin(self, tools: dict[str, ToolConfig]) -> list[str]:
        for tool in tools.values():
            if self.status(tool.id).active:
                self.stop_begin(tool)
        return []


def test_application_coordinates_commands_without_frontend_types():
    runtime = RecordingRuntime()
    application = ToolDeckApplication(runtime=runtime)
    assert application.api_version == APPLICATION_API_VERSION == 2
    application.refresh_catalog()
    application.save_tool(ToolConfig("worker", "Worker", "sleep 1", tempfile.gettempdir()), overwrite=False)

    started = application.start("worker")
    assert started.pid == 7001
    assert runtime.started == ["worker"]

    snapshot = application.snapshot()
    assert snapshot.tools["worker"].name == "Worker"
    assert snapshot.statuses["worker"].state == "running"

    with pytest.raises(ProcessError, match="仍在运行"):
        application.delete_tool("worker")
    application.stop_blocking("worker")
    assert application.delete_tool("worker").id == "worker"


def test_application_owns_drafts_and_import_planning(tmp_path):
    application = ToolDeckApplication(runtime=RecordingRuntime())
    application.refresh_catalog()
    draft = application.new_draft()
    draft.update(id="demo", name="Demo", cwd=tempfile.gettempdir(), cmd="echo ready")
    application.save_draft(draft)
    assert application.tool_draft("demo")["name"] == "Demo"

    script = tmp_path / "quick start.py"
    script.write_text("print('ready')\n", encoding="utf-8")
    plan = application.plan_import(script)
    assert plan.kind == "draft"
    assert plan.draft is not None
    assert plan.draft["name"] == "quick start"
    assert str(script) in plan.draft["cmd"]
    assert plan.draft["setupRequired"] is True
    assert plan.analysis is not None
    with pytest.raises(ConfigError, match="启动程序 不可执行|解释器 不可执行"):
        application.save_draft(plan.draft)
    assert plan.draft["id"] not in application.catalog_snapshot().tools


def test_python_import_prefers_nearby_project_virtualenv(tmp_path):
    project = tmp_path / "comfyui-image"
    script = project / "ComfyUI" / "main.py"
    script.parent.mkdir(parents=True)
    script.write_text("print('ready')\n", encoding="utf-8")
    environment = project / "venv"
    venv.EnvBuilder(with_pip=False).create(environment)
    interpreter = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")

    application = ToolDeckApplication(runtime=RecordingRuntime())
    application.refresh_catalog()
    plan = application.plan_import(script)

    assert plan.draft is not None
    assert plan.draft["launch"]["argv"] == [str(interpreter), str(script)]
    assert plan.draft["cwd"] == str(script.parent)
    assert plan.draft["setupRequired"] is False


def test_application_preflight_blocks_invalid_tool_before_catalog_write(tmp_path):
    application = ToolDeckApplication(runtime=RecordingRuntime())
    application.refresh_catalog()

    with pytest.raises(ConfigError, match="工作目录不存在"):
        application.save_tool(ToolConfig("broken", "Broken", "echo ready", str(tmp_path / "missing")), overwrite=False)

    assert "broken" not in application.catalog_snapshot().tools


def test_application_rechecks_structured_entry_before_every_start(tmp_path):
    source = tmp_path / "worker.sh"
    source.write_text("#!/bin/sh\n", encoding="utf-8")
    source.chmod(0o755)
    runtime = RecordingRuntime()
    application = ToolDeckApplication(runtime=runtime)
    application.refresh_catalog()
    application.save_tool(
        ToolConfig(
            "worker",
            "Worker",
            str(source),
            str(tmp_path),
            launch=LaunchConfig("argv", "shell", str(source), (str(source),)),
        ),
        overwrite=False,
    )
    source.unlink()

    with pytest.raises(ConfigError, match="入口文件不存在"):
        application.start("worker")

    assert runtime.started == []


def test_status_query_reports_unreadable_state_when_a_port_fails():
    class FailingRuntime(RecordingRuntime):
        def status(self, tool_id: str) -> ToolStatus:
            raise OSError("state disk unavailable")

    application = ToolDeckApplication(runtime=FailingRuntime())
    application.refresh_catalog()
    application.save_tool(ToolConfig("worker", "Worker", "true", tempfile.gettempdir()), overwrite=False)
    previous = {"worker": ToolStatus("worker", "running", pid=4321)}

    result = application.inspect_statuses(previous_statuses=previous, tick=True)
    assert result.statuses["worker"].state == "error"
    assert result.statuses["worker"].message == "state disk unavailable"
    assert result.issues[0].tool_name == "Worker"
    assert "state disk unavailable" in result.issues[0].message
    assert application.runtime.ticks == 1
