from __future__ import annotations

from pathlib import Path

import pytest

from tooldeck.config import ConfigError
from tooldeck.drafts import base_tool_id, parse_env_text, unique_tool_id
from tooldeck.groups import display_group_name
from tooldeck.platform_ops import reveal_path
from tooldeck.telemetry import parse_nvidia_smi


def test_draft_helpers_share_id_and_environment_rules():
    assert base_tool_id("Quick Start") == "quick-start"
    assert unique_tool_id("Quick Start", {"quick-start", "quick-start-2"}) == "quick-start-3"
    assert parse_env_text("# comment\nPORT=1234\nMODE=dev") == {"PORT": "1234", "MODE": "dev"}
    with pytest.raises(ConfigError, match="第 2 行缺少 ="):
        parse_env_text("PORT=1234\nBROKEN")


def test_group_display_disambiguates_reserved_label():
    assert display_group_name("") == "未分组"
    assert display_group_name("未分组") == "未分组（自定义分组）"


def test_platform_reveal_uses_injected_desktop_boundary(tmp_path):
    target = tmp_path / "worker.log"
    target.write_text("ready\n", encoding="utf-8")
    calls: list[tuple[str, list[str]]] = []

    assert reveal_path(
        target,
        start_detached=lambda program, arguments: calls.append((program, arguments)) or True,
        open_directory=lambda _path: False,
        platform_name="linux",
        which=lambda program: f"/usr/bin/{program}" if program == "dolphin" else None,
    )
    assert calls == [("dolphin", ["--select", str(target.resolve())])]


def test_nvidia_smi_parser_preserves_gpu_names_with_commas():
    sample = parse_nvidia_smi("72, 8192, 16384, NVIDIA, Test GPU\n")
    assert sample.utilization == 72
    assert sample.used_mib == 8192
    assert sample.total_mib == 16384
    assert sample.name == "NVIDIA, Test GPU"

    with pytest.raises(ValueError):
        parse_nvidia_smi("not enough fields")
