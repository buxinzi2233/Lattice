"""Application service for the tool catalog shared by CLI and GUI.

Tool configuration and layout remain separate compatibility files. Mutations
that touch both are coordinated by a small recovery journal so callers never
have to sequence persistence themselves.
"""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterator

from . import paths
from .config import (
    ConfigError,
    ConfigIssue,
    ToolConfig,
    delete as delete_config,
    import_toml,
    load_all,
    load_file,
    save as save_config,
)
from .groups import normalize_group_key
from .layout import LayoutState, load as load_layout, move_item, reconcile, save as save_layout
from .storage import atomic_write_text, exclusive_file_lock, read_bytes, restore_bytes
from .util import valid_id

JOURNAL_VERSION = 1


class CatalogError(RuntimeError):
    """The catalog could not preserve a consistent persisted state."""


@dataclass(frozen=True, slots=True)
class CatalogSnapshot:
    tools: dict[str, ToolConfig]
    issues: tuple[ConfigIssue, ...]
    layout: LayoutState


class ToolCatalog:
    def __init__(self) -> None:
        self._tools: dict[str, ToolConfig] = {}
        self._issues: tuple[ConfigIssue, ...] = ()
        self._layout = LayoutState()
        self._loaded = False

    @property
    def tools(self) -> dict[str, ToolConfig]:
        self._ensure_loaded()
        return dict(self._tools)

    @property
    def issues(self) -> tuple[ConfigIssue, ...]:
        self._ensure_loaded()
        return self._issues

    @property
    def layout(self) -> LayoutState:
        self._ensure_loaded()
        return self._layout.copy()

    def snapshot(self) -> CatalogSnapshot:
        self._ensure_loaded()
        return CatalogSnapshot(dict(self._tools), self._issues, self._layout.copy())

    def refresh(self) -> CatalogSnapshot:
        with exclusive_file_lock(paths.catalog_lock_file()):
            return self._refresh_unlocked()

    def _refresh_unlocked(self) -> CatalogSnapshot:
        self._recover_pending_transaction()
        tools, issues = load_all()
        self._tools = tools
        self._issues = tuple(issues)
        self._layout = reconcile(tools, load_layout(paths.layout_json()))
        self._loaded = True
        return self.snapshot()

    @contextmanager
    def _mutation(self) -> Iterator[None]:
        with exclusive_file_lock(paths.catalog_lock_file()):
            self._refresh_unlocked()
            yield

    def find(self, tool_id: str) -> ToolConfig:
        self._ensure_loaded()
        try:
            return self._tools[tool_id]
        except KeyError as exc:
            raise ConfigError(f"工具 {tool_id} 不存在") from exc

    def save_tool(self, tool: ToolConfig, *, overwrite: bool = True) -> CatalogSnapshot:
        with self._mutation():
            checked = _validate_tool(tool)
            if not overwrite and checked.id in self._tools:
                raise ConfigError(f"工具 {checked.id} 已存在")
            updated_tools = dict(self._tools)
            updated_tools[checked.id] = checked
            updated_layout = reconcile(updated_tools, self._layout)
            self._persist_tool_and_layout(
                checked.id,
                lambda: save_config(checked, overwrite=overwrite),
                updated_layout,
            )
            self._tools = updated_tools
            self._layout = updated_layout
            self._issues = tuple(issue for issue in self._issues if issue.path != paths.tool_toml(checked.id))
            return self.snapshot()

    def delete_tool(self, tool_id: str) -> ToolConfig:
        with self._mutation():
            tool = self.find(tool_id)
            updated_tools = dict(self._tools)
            updated_tools.pop(tool_id)
            updated_layout = reconcile(updated_tools, self._layout)
            self._persist_tool_and_layout(tool_id, lambda: delete_config(tool_id), updated_layout)
            self._tools = updated_tools
            self._layout = updated_layout
            return tool

    def import_tool(self, source: Path, *, overwrite: bool = False) -> ToolConfig:
        source = Path(source).expanduser().resolve()
        with self._mutation():
            candidate = load_file(source)
            if not overwrite and candidate.id in self._tools:
                raise ConfigError(f"工具 {candidate.id} 已存在")
            updated_tools = dict(self._tools)
            updated_tools[candidate.id] = candidate
            updated_layout = reconcile(updated_tools, self._layout)
            self._persist_tool_and_layout(
                candidate.id,
                lambda: import_toml(source, overwrite=overwrite),
                updated_layout,
            )
            self._tools = updated_tools
            self._layout = updated_layout
            self._issues = tuple(issue for issue in self._issues if issue.path != paths.tool_toml(candidate.id))
            return candidate

    def move_tool(self, tool_id: str, target_group: str, target_index: int) -> bool:
        with self._mutation():
            if tool_id not in self._tools:
                return False
            target = str(normalize_group_key(target_group))
            if target not in self._layout.group_order:
                return False
            source = self._tools[tool_id].group
            source_saved = self._layout.tool_order.get(source, [])
            if tool_id not in source_saved:
                return False

            source_order = [item for item in source_saved if item != tool_id]
            target_order = [item for item in self._layout.tool_order.get(target, []) if item != tool_id]
            if source == target:
                original_index = source_saved.index(tool_id)
                if original_index < target_index:
                    target_index -= 1

            candidate_layout = self._layout.copy()
            candidate_layout.tool_order[source] = source_order
            candidate_layout.tool_order[target] = move_item(target_order, tool_id, target_index)
            if source == target:
                candidate_layout = reconcile(self._tools, candidate_layout)
                self._persist_layout(candidate_layout)
                return True

            updated_tool = replace(self._tools[tool_id], group=target)
            updated_tools = dict(self._tools)
            updated_tools[tool_id] = updated_tool
            candidate_layout = reconcile(updated_tools, candidate_layout)
            self._persist_tool_and_layout(
                tool_id,
                lambda: save_config(updated_tool),
                candidate_layout,
            )
            self._tools = updated_tools
            self._layout = candidate_layout
            return True

    def move_group(self, group: str, target_index: int) -> bool:
        with self._mutation():
            key = str(normalize_group_key(group))
            if key not in self._layout.group_order:
                return False
            candidate = self._layout.copy()
            candidate.group_order = move_item(candidate.group_order, key, target_index)
            self._persist_layout(candidate)
            return True

    def set_group_collapsed(self, group: str, collapsed: bool) -> bool:
        with self._mutation():
            key = str(normalize_group_key(group))
            if key not in self._layout.group_order:
                return False
            candidate = self._layout.copy()
            if collapsed:
                candidate.collapsed_groups.add(key)
            else:
                candidate.collapsed_groups.discard(key)
            self._persist_layout(candidate)
            return True

    def toggle_group(self, group: str) -> bool:
        with self._mutation():
            key = str(normalize_group_key(group))
            if key not in self._layout.group_order:
                return False
            candidate = self._layout.copy()
            if key in candidate.collapsed_groups:
                candidate.collapsed_groups.remove(key)
            else:
                candidate.collapsed_groups.add(key)
            self._persist_layout(candidate)
            return True

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self.refresh()

    def _persist_layout(self, candidate: LayoutState) -> None:
        save_layout(paths.layout_json(), candidate)
        self._layout = candidate

    def _persist_tool_and_layout(
        self,
        tool_id: str,
        write_tool: Callable[[], object],
        candidate_layout: LayoutState,
    ) -> None:
        record = self._prepare_journal(tool_id)
        try:
            write_tool()
            save_layout(paths.layout_json(), candidate_layout)
            record["phase"] = "committed"
            self._write_journal(record)
        except Exception as exc:
            try:
                self._restore_record(record)
                self._clear_journal()
            except OSError as rollback_exc:
                raise CatalogError(
                    f"目录写入失败且自动回滚失败：{exc}；回滚错误：{rollback_exc}"
                ) from exc
            raise
        self._clear_journal(required=False)

    def _prepare_journal(self, tool_id: str) -> dict[str, object]:
        record: dict[str, object] = {
            "version": JOURNAL_VERSION,
            "phase": "prepared",
            "tool_id": tool_id,
            "tool_before": _encode_bytes(read_bytes(paths.tool_toml(tool_id))),
            "layout_before": _encode_bytes(read_bytes(paths.layout_json())),
        }
        self._write_journal(record)
        return record

    @staticmethod
    def _write_journal(record: dict[str, object]) -> None:
        payload = json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        atomic_write_text(paths.catalog_journal_json(), payload)

    @staticmethod
    def _clear_journal(*, required: bool = True) -> None:
        try:
            paths.catalog_journal_json().unlink()
        except FileNotFoundError:
            pass
        except OSError:
            if required:
                raise

    def _recover_pending_transaction(self) -> None:
        journal = paths.catalog_journal_json()
        try:
            raw = json.loads(journal.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CatalogError(f"目录事务日志无法读取：{journal}") from exc
        record = self._validate_journal(raw)
        if record["phase"] == "committed":
            self._clear_journal(required=False)
            return
        try:
            self._restore_record(record)
            self._clear_journal()
        except OSError as exc:
            raise CatalogError(f"无法恢复未完成的目录事务：{exc}") from exc

    @staticmethod
    def _validate_journal(raw: object) -> dict[str, object]:
        if not isinstance(raw, dict) or raw.get("version") != JOURNAL_VERSION:
            raise CatalogError("目录事务日志版本无效")
        phase = raw.get("phase")
        tool_id = raw.get("tool_id")
        if phase not in {"prepared", "committed"} or not isinstance(tool_id, str) or not valid_id(tool_id):
            raise CatalogError("目录事务日志内容无效")
        _decode_bytes(raw.get("tool_before"))
        _decode_bytes(raw.get("layout_before"))
        return raw

    @staticmethod
    def _restore_record(record: dict[str, object]) -> None:
        tool_id = str(record["tool_id"])
        restore_bytes(paths.tool_toml(tool_id), _decode_bytes(record.get("tool_before")))
        restore_bytes(paths.layout_json(), _decode_bytes(record.get("layout_before")))


def _validate_tool(tool: ToolConfig) -> ToolConfig:
    return ToolConfig.from_mapping(
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


def _encode_bytes(payload: bytes | None) -> str | None:
    return None if payload is None else base64.b64encode(payload).decode("ascii")


def _decode_bytes(value: object) -> bytes | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise CatalogError("目录事务日志备份字段无效")
    try:
        return base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise CatalogError("目录事务日志备份内容无效") from exc
