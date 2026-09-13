"""Persistent ordering and collapse state for the Lattice tool index.

The layout file is deliberately separate from each tool TOML.  Tool TOMLs own
configuration (including the current group); this file only owns presentation
order and the user's collapsed-group preference.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, Mapping

SCHEMA_VERSION = 1


@dataclass
class LayoutState:
    group_order: list[str] = field(default_factory=list)
    tool_order: dict[str, list[str]] = field(default_factory=dict)
    collapsed_groups: set[str] = field(default_factory=set)

    def to_mapping(self) -> dict[str, object]:
        return {
            "version": SCHEMA_VERSION,
            "group_order": list(self.group_order),
            "tool_order": {key: list(value) for key, value in self.tool_order.items()},
            "collapsed_groups": sorted(self.collapsed_groups),
        }


def _normalise_group(value: object) -> str:
    return value if isinstance(value, str) else ""


def reconcile(
    tools: Mapping[str, object],
    state: LayoutState | None = None,
    *,
    group_for: Callable[[object], str] | None = None,
    sort_key: Callable[[tuple[str, object]], object] | None = None,
) -> LayoutState:
    """Reconcile a saved state with the currently loaded tool configs.

    Unknown groups/tools are removed. New entries are appended in a stable
    order, which makes a missing or repaired layout deterministic.
    """

    current = state or LayoutState()
    group_for = group_for or (lambda tool: getattr(tool, "group", "") or "")
    sort_key = sort_key or (lambda item: (str(getattr(item[1], "name", "")).casefold(), item[0].casefold()))
    by_group: dict[str, list[tuple[str, object]]] = {}
    for tool_id, tool in tools.items():
        by_group.setdefault(_normalise_group(group_for(tool)), []).append((tool_id, tool))
    for values in by_group.values():
        values.sort(key=sort_key)

    known_groups = set(by_group)
    ordered_groups = [group for group in current.group_order if group in known_groups]
    ordered_groups.extend(
        sorted(known_groups - set(ordered_groups), key=lambda group: (not bool(group), group.casefold()))
    )
    ordered_tools: dict[str, list[str]] = {}
    for group in ordered_groups:
        known_ids = {tool_id for tool_id, _ in by_group[group]}
        saved = [tool_id for tool_id in current.tool_order.get(group, []) if tool_id in known_ids]
        saved_set = set(saved)
        saved.extend(tool_id for tool_id, _ in by_group[group] if tool_id not in saved_set)
        ordered_tools[group] = saved
    return LayoutState(
        group_order=ordered_groups,
        tool_order=ordered_tools,
        collapsed_groups={group for group in current.collapsed_groups if group in known_groups},
    )


def _decode(raw: object) -> LayoutState:
    if not isinstance(raw, dict) or raw.get("version") != SCHEMA_VERSION:
        raise ValueError("不支持的 layout.json 版本")
    groups = raw.get("group_order")
    orders = raw.get("tool_order")
    collapsed = raw.get("collapsed_groups", [])
    if not isinstance(groups, list) or not all(isinstance(value, str) for value in groups):
        raise ValueError("group_order 必须是字符串数组")
    if not isinstance(orders, dict):
        raise ValueError("tool_order 必须是对象")
    parsed_orders: dict[str, list[str]] = {}
    for group, value in orders.items():
        if not isinstance(group, str) or not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ValueError("tool_order 内容无效")
        parsed_orders[group] = list(dict.fromkeys(value))
    if not isinstance(collapsed, list) or not all(isinstance(value, str) for value in collapsed):
        raise ValueError("collapsed_groups 必须是字符串数组")
    return LayoutState(list(dict.fromkeys(groups)), parsed_orders, set(collapsed))


def load(path: Path) -> LayoutState:
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return _decode(raw)
    except FileNotFoundError:
        return LayoutState()
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise LayoutError(f"无法读取布局 {path}：{exc}；请修复文件或使用重置布局操作") from exc


class LayoutError(ValueError):
    """The saved layout needs explicit repair; loading never replaces it."""


def repair(path: Path) -> Path:
    """Preserve the rejected file before an explicitly requested layout reset."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup = path.with_name(f"{path.name}.corrupt-{stamp}")
    path.rename(backup)
    return backup


def save(path: Path, state: LayoutState) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(state.to_mapping(), ensure_ascii=False, indent=2) + "\n"
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
    return path


def move_item(values: Iterable[str], item: str, index: int) -> list[str]:
    result = [value for value in values if value != item]
    result.insert(max(0, min(index, len(result))), item)
    return result
