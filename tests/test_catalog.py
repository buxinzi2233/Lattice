from __future__ import annotations

import tempfile

import json
from dataclasses import replace

import pytest

from tooldeck import paths
from tooldeck.catalog import ToolCatalog
from tooldeck.config import ToolConfig, load_file, save
from tooldeck.layout import LayoutState, load as load_layout, save as save_layout


def test_catalog_keeps_ungrouped_and_literal_label_as_distinct_keys():
    save(ToolConfig("loose", "Loose", "true", tempfile.gettempdir()))
    save(ToolConfig("named", "Named", "true", tempfile.gettempdir(), group="未分组"))

    catalog = ToolCatalog()
    snapshot = catalog.refresh()

    assert snapshot.layout.group_order == ["未分组", ""]
    assert catalog.set_group_collapsed("", True) is True
    assert catalog.set_group_collapsed("未分组", False) is True
    persisted = load_layout(paths.layout_json())
    assert persisted.collapsed_groups == {""}


def test_cross_group_move_rolls_back_tool_when_layout_write_fails(monkeypatch):
    save(ToolConfig("one", "One", "true", tempfile.gettempdir(), group="A"))
    save(ToolConfig("two", "Two", "true", tempfile.gettempdir(), group="B"))
    original_layout = LayoutState(["A", "B"], {"A": ["one"], "B": ["two"]}, set())
    save_layout(paths.layout_json(), original_layout)
    original_layout_bytes = paths.layout_json().read_bytes()
    original_tool_bytes = paths.tool_toml("one").read_bytes()
    catalog = ToolCatalog()
    catalog.refresh()

    def fail_layout(*_args, **_kwargs):
        raise OSError("layout disk unavailable")

    monkeypatch.setattr("tooldeck.catalog.save_layout", fail_layout)
    with pytest.raises(OSError, match="layout disk unavailable"):
        catalog.move_tool("one", "B", 0)

    assert paths.tool_toml("one").read_bytes() == original_tool_bytes
    assert paths.layout_json().read_bytes() == original_layout_bytes
    assert load_file(paths.tool_toml("one")).group == "A"
    assert catalog.find("one").group == "A"
    assert not paths.catalog_journal_json().exists()


def test_refresh_recovers_a_prepared_catalog_transaction():
    original = ToolConfig("one", "One", "true", tempfile.gettempdir(), group="A")
    save(original)
    original_layout = LayoutState(["A"], {"A": ["one"]}, set())
    save_layout(paths.layout_json(), original_layout)
    catalog = ToolCatalog()
    catalog.refresh()
    catalog._prepare_journal("one")

    save(replace(original, group="B"))
    save_layout(paths.layout_json(), LayoutState(["B"], {"B": ["one"]}, {"B"}))

    recovered = ToolCatalog().refresh()
    assert recovered.tools["one"].group == "A"
    assert recovered.layout == original_layout
    assert not paths.catalog_journal_json().exists()


def test_catalog_add_edit_delete_reconciles_layout():
    catalog = ToolCatalog()
    catalog.refresh()
    catalog.save_tool(ToolConfig("one", "One", "true", tempfile.gettempdir(), group="A"), overwrite=False)
    assert load_layout(paths.layout_json()).tool_order == {"A": ["one"]}

    catalog.save_tool(ToolConfig("one", "One", "true", tempfile.gettempdir(), group="B"))
    assert load_layout(paths.layout_json()).tool_order == {"B": ["one"]}

    catalog.delete_tool("one")
    assert load_layout(paths.layout_json()) == LayoutState()
    assert not paths.tool_toml("one").exists()


def test_stale_catalog_instances_refresh_inside_mutation_lock():
    first = ToolCatalog()
    second = ToolCatalog()
    first.refresh()
    second.refresh()

    first.save_tool(ToolConfig("one", "One", "true", tempfile.gettempdir(), group="A"), overwrite=False)
    second.save_tool(ToolConfig("two", "Two", "true", tempfile.gettempdir(), group="B"), overwrite=False)

    persisted = load_layout(paths.layout_json())
    assert persisted.group_order == ["A", "B"]
    assert persisted.tool_order == {"A": ["one"], "B": ["two"]}


def test_committed_journal_is_cleaned_without_rolling_back():
    tool = ToolConfig("one", "One", "true", tempfile.gettempdir(), group="A")
    save(tool)
    save_layout(paths.layout_json(), LayoutState(["A"], {"A": ["one"]}, set()))
    paths.catalog_journal_json().write_text(
        json.dumps(
            {
                "version": 1,
                "phase": "committed",
                "tool_id": "one",
                "tool_before": None,
                "layout_before": None,
            }
        ),
        encoding="utf-8",
    )

    snapshot = ToolCatalog().refresh()
    assert snapshot.tools["one"] == tool
    assert not paths.catalog_journal_json().exists()
