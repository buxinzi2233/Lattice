"""Frontend-neutral command and query API for ToolDeck.

Frontends depend on this facade instead of sequencing catalog persistence and
process operations themselves. The API intentionally contains no Qt types so a
QML, web, TUI, or test adapter can share the same behavior.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import threading
from typing import Any, Literal

from . import paths
from .catalog import CatalogSnapshot, ToolCatalog
from .config import ConfigError, ToolConfig, load_file
from .drafts import (
    ToolDraft,
    command_for_launch_path,
    launch_patch_for_analysis,
    new_tool_draft,
    tool_from_draft,
    tool_to_draft,
)
from .launchers import (
    LaunchAnalysis,
    PreparationResult,
    PreflightReport,
    SetupPlan,
    analyze_launch as analyze_launch_path,
    execute_setup,
    preflight_tool as build_preflight_report,
)
from .ports import CatalogPort, RuntimePort
from .procs import ProcManager, ProcessError, ToolStatus

APPLICATION_API_VERSION = 2


@dataclass(frozen=True, slots=True)
class RuntimeIssue:
    tool_id: str
    tool_name: str
    message: str


@dataclass(frozen=True, slots=True)
class StatusSnapshot:
    statuses: dict[str, ToolStatus]
    issues: tuple[RuntimeIssue, ...] = ()


@dataclass(frozen=True, slots=True)
class ApplicationSnapshot:
    catalog: CatalogSnapshot
    runtime: StatusSnapshot

    @property
    def tools(self) -> dict[str, ToolConfig]:
        return dict(self.catalog.tools)

    @property
    def statuses(self) -> dict[str, ToolStatus]:
        return dict(self.runtime.statuses)


@dataclass(frozen=True, slots=True)
class ImportPlan:
    kind: Literal["config", "draft"]
    source: Path
    candidate: ToolConfig | None = None
    draft: ToolDraft | None = None
    overwrite_required: bool = False
    analysis: LaunchAnalysis | None = None


class ToolDeckApplication:
    """Coordinates the catalog and runtime through explicit ports."""

    api_version = APPLICATION_API_VERSION

    def __init__(
        self,
        *,
        catalog: CatalogPort | None = None,
        runtime: RuntimePort | None = None,
    ) -> None:
        self.catalog: CatalogPort = catalog or ToolCatalog()
        self.runtime: RuntimePort = runtime or ProcManager()

    def refresh(
        self,
        *,
        previous_statuses: Mapping[str, ToolStatus] | None = None,
    ) -> ApplicationSnapshot:
        catalog = self.catalog.refresh()
        runtime = self.inspect_statuses(catalog.tools, previous_statuses=previous_statuses)
        return ApplicationSnapshot(catalog, runtime)

    def refresh_catalog(self) -> CatalogSnapshot:
        return self.catalog.refresh()

    def snapshot(
        self,
        *,
        previous_statuses: Mapping[str, ToolStatus] | None = None,
    ) -> ApplicationSnapshot:
        catalog = self.catalog.snapshot()
        runtime = self.inspect_statuses(catalog.tools, previous_statuses=previous_statuses)
        return ApplicationSnapshot(catalog, runtime)

    def inspect_statuses(
        self,
        tools: Mapping[str, ToolConfig] | None = None,
        *,
        previous_statuses: Mapping[str, ToolStatus] | None = None,
        tick: bool = False,
    ) -> StatusSnapshot:
        if tick:
            self.runtime.tick()
        selected = dict(tools) if tools is not None else self.catalog.snapshot().tools
        statuses: dict[str, ToolStatus] = {}
        issues: list[RuntimeIssue] = []
        for tool_id, tool in selected.items():
            try:
                statuses[tool_id] = self.runtime.status(tool_id)
            except (ProcessError, OSError) as exc:
                statuses[tool_id] = ToolStatus(tool_id, "error", message=str(exc))
                issues.append(RuntimeIssue(tool_id, tool.name, str(exc)))
        return StatusSnapshot(statuses, tuple(issues))

    def find_tool(self, tool_id: str) -> ToolConfig:
        return self.catalog.find(tool_id)

    def start(self, tool_id: str) -> ToolStatus:
        tool = self.find_tool(tool_id)
        self._require_preflight(tool)
        return self.runtime.start(tool)

    def stop_begin(self, tool_id: str) -> ToolStatus:
        return self.runtime.stop_begin(self.find_tool(tool_id))

    def stop_blocking(self, tool_id: str) -> ToolStatus:
        return self.runtime.stop_blocking(self.find_tool(tool_id))

    def restart_blocking(self, tool_id: str) -> ToolStatus:
        tool = self.find_tool(tool_id)
        self._require_preflight(tool)
        self.runtime.stop_blocking(tool)
        return self.runtime.start(tool)

    def stop_all_begin(self) -> list[str]:
        return self.runtime.stop_all_begin(self.catalog.snapshot().tools)

    def start_autostart(self) -> tuple[RuntimeIssue, ...]:
        failures: list[RuntimeIssue] = []
        for tool in self.catalog.snapshot().tools.values():
            if not tool.autostart:
                continue
            try:
                if self.runtime.status(tool.id).active:
                    continue
                self._require_preflight(tool)
                self.runtime.start(tool)
            except (ConfigError, ProcessError, OSError) as exc:
                failures.append(RuntimeIssue(tool.id, tool.name, str(exc)))
        return tuple(failures)

    def save_tool(self, tool: ToolConfig, *, overwrite: bool = True) -> CatalogSnapshot:
        self._require_preflight(tool)
        return self.catalog.save_tool(tool, overwrite=overwrite)

    def save_draft(self, draft: Mapping[str, Any]) -> CatalogSnapshot:
        original_id = str(draft.get("originalId", "")).strip()
        tool = tool_from_draft(draft)
        if original_id and tool.id != original_id:
            raise ConfigError("已登记工具的 ID 不可更改")
        self._require_preflight(tool)
        return self.catalog.save_tool(tool, overwrite=bool(original_id))

    def delete_tool(self, tool_id: str, *, require_stopped: bool = True) -> ToolConfig:
        tool = self.find_tool(tool_id)
        if require_stopped and self.runtime.status(tool.id).active:
            raise ProcessError("工具仍在运行，请先停止该单元")
        return self.catalog.delete_tool(tool.id)

    def import_tool(self, source: Path, *, overwrite: bool = False) -> ToolConfig:
        candidate = load_file(source)
        self._require_preflight(candidate)
        return self.catalog.import_tool(source, overwrite=overwrite)

    def new_draft(self) -> ToolDraft:
        return new_tool_draft(self.catalog.snapshot().tools)

    def tool_draft(self, tool_id: str) -> ToolDraft:
        return tool_to_draft(self.find_tool(tool_id))

    def launch_draft(self, source: Path, shell: str | None = None) -> dict[str, Any]:
        analysis = self.analyze_launch(source)
        return launch_patch_for_analysis(analysis, self.catalog.snapshot().tools)

    def analyze_launch(self, source: Path) -> LaunchAnalysis:
        return analyze_launch_path(source)

    def preflight_tool(self, tool: ToolConfig) -> PreflightReport:
        return build_preflight_report(tool)

    def _require_preflight(self, tool: ToolConfig) -> PreflightReport:
        report = self.preflight_tool(tool)
        if report.blocking:
            raise ConfigError("；".join(report.blocking_messages))
        return report

    def prepare_environment(
        self,
        setup: SetupPlan,
        *,
        confirmed: bool,
        cancel_event: threading.Event | None = None,
        progress: Callable[[int, int, str], None] | None = None,
        started: Callable[[Path], None] | None = None,
    ) -> PreparationResult:
        paths.ensure_dirs()
        timestamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S-%f")
        safe_name = "".join(character if character.isalnum() or character in "-_" else "-" for character in setup.project_root.name)
        log_path = paths.setup_logs_dir() / f"{timestamp}-{safe_name or 'python'}.log"
        return execute_setup(
            setup,
            log_path,
            confirmed=confirmed,
            cancel_event=cancel_event,
            progress=progress,
            started=started,
        )

    def plan_import(self, source: Path, *, shell: str | None = None) -> ImportPlan:
        selected = Path(source).expanduser().resolve()
        if not selected.is_file():
            raise ConfigError(f"文件不存在：{selected}")
        tools = self.catalog.snapshot().tools
        if selected.suffix.casefold() == ".toml":
            candidate = load_file(selected)
            return ImportPlan(
                "config",
                selected,
                candidate=candidate,
                overwrite_required=candidate.id in tools,
            )
        analysis = self.analyze_launch(selected)
        patch = launch_patch_for_analysis(analysis, tools)
        draft = new_tool_draft(tools)
        draft.update(
            id=patch["suggestedId"],
            name=patch["name"],
            cwd=patch["cwd"],
            cmd=patch["cmd"],
            shell=patch["shell"],
            launch=patch["launch"],
            readiness=patch["readiness"],
            rawMode=False,
            source=patch["source"],
            checks=patch["checks"],
            setupRequired=patch["setupRequired"],
            setupSummary=patch["setupSummary"],
            setupTarget=patch["setupTarget"],
            setupNetwork=patch["setupNetwork"],
            setupCommands=patch["setupCommands"],
        )
        return ImportPlan("draft", selected, draft=draft, analysis=analysis)

    def move_tool(self, tool_id: str, target_group: str, target_index: int) -> bool:
        return self.catalog.move_tool(tool_id, target_group, target_index)

    def move_group(self, group: str, target_index: int) -> bool:
        return self.catalog.move_group(group, target_index)

    def set_group_collapsed(self, group: str, collapsed: bool) -> bool:
        return self.catalog.set_group_collapsed(group, collapsed)

    def toggle_group(self, group: str) -> bool:
        return self.catalog.toggle_group(group)

    def catalog_snapshot(self) -> CatalogSnapshot:
        return self.catalog.snapshot()

    @staticmethod
    def command_for_launch_path(
        source: Path,
        shell: str | None = None,
        *,
        platform_name: str | None = None,
        python_executable: str | None = None,
    ) -> tuple[str, str]:
        return command_for_launch_path(
            source,
            shell,
            platform_name=platform_name,
            python_executable=python_executable,
        )

    @staticmethod
    def data_path(kind: Literal["config", "state", "logs"]) -> Path:
        return {
            "config": paths.config_dir(),
            "state": paths.state_dir(),
            "logs": paths.logs_dir(),
        }[kind]

    @staticmethod
    def tools_directory() -> Path:
        paths.ensure_dirs()
        return paths.tools_dir()

    @staticmethod
    def log_path(tool_id: str) -> Path:
        return paths.log_file(tool_id)

    def log_tail(self, tool_id: str, *, lines: int = 20, max_bytes: int = 16 * 1024) -> str:
        path = self.log_path(tool_id)
        try:
            with path.open("rb") as handle:
                handle.seek(0, 2)
                size = handle.tell()
                handle.seek(max(0, size - max_bytes))
                payload = handle.read()
        except OSError:
            return ""
        return "\n".join(payload.decode("utf-8", errors="replace").splitlines()[-lines:]).strip()
