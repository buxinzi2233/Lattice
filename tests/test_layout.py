from __future__ import annotations

import json
import pytest

from tooldeck import paths
from tooldeck.config import ToolConfig, load_file, save
from tooldeck.gui.bridge import AppBridge
from tooldeck.layout import LayoutError, repair, LayoutState, load as load_layout, reconcile, save as save_layout



class FixedManager:
    def __init__(self) -> None:
        self.statuses = {}

    def tick(self) -> None:
        pass

    def status(self, tool_id: str):
        from tooldeck.procs import ToolStatus

        return self.statuses.get(tool_id, ToolStatus(tool_id, "stopped"))


def test_layout_missing_file_initializes_deterministically():
    tools = {
        "loose": ToolConfig("loose", "Loose", "true", "/tmp"),
        "beta": ToolConfig("beta", "Beta", "true", "/tmp", group="B"),
        "alpha": ToolConfig("alpha", "Alpha", "true", "/tmp", group="A"),
    }
    state = reconcile(tools, load_layout(paths.layout_json()))
    assert state.group_order == ["A", "B", ""]
    assert state.tool_order == {"A": ["alpha"], "B": ["beta"], "": ["loose"]}


def test_layout_atomic_save_and_corrupt_recovery_preserves_backup():
    state = LayoutState(["A"], {"A": ["one"]}, {"A"})
    save_layout(paths.layout_json(), state)
    assert json.loads(paths.layout_json().read_text(encoding="utf-8"))["version"] == 1
    paths.layout_json().write_text("{not valid", encoding="utf-8")
    with pytest.raises(LayoutError, match="无法读取布局"):
        load_layout(paths.layout_json())
    assert paths.layout_json().read_text(encoding="utf-8") == "{not valid"
    backup = repair(paths.layout_json())
    assert backup.read_text(encoding="utf-8") == "{not valid"
    assert load_layout(paths.layout_json()) == LayoutState()


def test_bridge_moves_tools_groups_and_collapses(qapp):
    save(ToolConfig("one", "One", "true", "/tmp", group="A"))
    save(ToolConfig("two", "Two", "true", "/tmp", group="A"))
    save(ToolConfig("three", "Three", "true", "/tmp", group="B"))
    bridge = AppBridge(manager=FixedManager(), auto_start_timers=False)

    assert bridge.moveTool("one", "A", 2) is True
    assert [bridge.model.get(row)["toolId"] for row in range(3)] == ["two", "one", "three"]
    assert bridge.moveTool("one", "B", 0) is True
    assert load_file(paths.tool_toml("one")).group == "B"
    assert [bridge.model.get(row)["toolId"] for row in range(3)] == ["two", "one", "three"]
    assert bridge.moveGroup("B", 0) is True
    assert [bridge.model.get(row)["toolId"] for row in range(3)] == ["one", "three", "two"]

    assert bridge.setGroupCollapsed("B", True) is True
    assert bridge.model.visibleCount == 3
    assert bridge.model.rowCount() == 3
    bridge.setSearchText("one")
    assert bridge.model.visibleCount == 1
    assert bridge.model.rowCount() == 2
    bridge.clearFilters()
    assert bridge.model.rowCount() == 3
    bridge.shutdown()


def test_reorder_disabled_during_filter(qapp):
    save(ToolConfig("one", "One", "true", "/tmp", group="A"))
    save(ToolConfig("two", "Two", "true", "/tmp", group="A"))
    bridge = AppBridge(manager=FixedManager(), auto_start_timers=False)
    bridge.setSearchText("one")
    assert bridge.reorderingAllowed is False
    assert bridge.moveTool("one", "A", 1) is False
    assert [bridge.model.get(row)["toolId"] for row in range(1)] == ["one"]
    bridge.shutdown()


def test_bridge_preserves_raw_group_keys_when_label_matches_ungrouped(qapp):
    save(ToolConfig("loose", "Loose", "true", "/tmp"))
    save(ToolConfig("named", "Named", "true", "/tmp", group="未分组"))
    bridge = AppBridge(manager=FixedManager(), auto_start_timers=False)

    headers = [
        bridge.model.getRow(row)
        for row in range(bridge.model.rowCount())
        if bridge.model.getRow(row)["rowType"] == "group"
    ]
    assert [(row["groupKey"], row["groupName"]) for row in headers] == [
        ("未分组", "未分组（自定义分组）"),
        ("", "未分组"),
    ]
    assert bridge.setGroupCollapsed("", True) is True
    assert bridge.setGroupCollapsed("未分组", False) is True
    assert bridge.moveTool("loose", "未分组", 1) is True
    assert load_file(paths.tool_toml("loose")).group == "未分组"
    bridge.shutdown()
