from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from tooldeck import paths
from tooldeck.config import ConfigError, ToolConfig, default_shell, import_toml, load_all, load_file, save


def test_config_round_trip_preserves_script_and_unicode():
    tool = ToolConfig(
        id="demo.tool",
        name="演示工具",
        cmd="echo \"$HOME\"\nprintf '%s' \\\"你好\\\"",
        cwd="~/Projects/demo",
        shell="fish",
        env={"A_B": "带引号的'value\""},
        autostart=True,
        stop_signal="INT",
        stop_timeout=2.5,
        group="实验工具",
    )
    destination = save(tool)
    loaded = load_file(destination)
    assert loaded == dataclasses.replace(tool, cwd=str(Path(tool.cwd).expanduser()))


def test_load_all_reports_bad_file_without_hiding_good_file():
    save(ToolConfig("good", "Good", "sleep 1", "/tmp"))
    from tooldeck import paths

    paths.tool_toml("bad").write_text("name = [", encoding="utf-8")
    tools, issues = load_all()
    assert list(tools) == ["good"]
    assert len(issues) == 1
    assert issues[0].path.name == "bad.toml"


def test_import_validates_and_refuses_overwrite(tmp_path):
    source = tmp_path / "imported.toml"
    source.write_text('name="Imported"\ncmd="sleep 1"\ncwd="/tmp"\n', encoding="utf-8")
    assert import_toml(source).id == "imported"
    with pytest.raises(ConfigError, match="已存在"):
        import_toml(source)


@pytest.mark.parametrize("tool_id", ["", "bad id", "../escape", "-bad"])
def test_invalid_ids_are_rejected(tool_id):
    with pytest.raises(ConfigError):
        save(ToolConfig(tool_id, "Bad", "true", "/tmp"))


def test_nul_bytes_are_rejected_before_process_launch():
    with pytest.raises(ConfigError, match="NUL"):
        save(ToolConfig("nul", "Bad", "echo ok\x00oops", "/tmp"))


@pytest.mark.parametrize("group", ["line one\nline two", "x" * 65])
def test_invalid_group_names_are_rejected(group):
    with pytest.raises(ConfigError, match="group"):
        save(ToolConfig("bad-group", "Bad Group", "true", "/tmp", group=group))


def test_windows_defaults_use_comspec_and_appdata(tmp_path):
    appdata = tmp_path / "Roaming"
    local_appdata = tmp_path / "Local"
    environ = {"COMSPEC": r"C:\Windows\System32\cmd.exe", "APPDATA": str(appdata), "LOCALAPPDATA": str(local_appdata)}
    assert default_shell("nt", environ) == environ["COMSPEC"]
    assert paths._location(
        "XDG_CONFIG_HOME",
        "~/.config",
        "APPDATA",
        "AppData/Roaming",
        platform_name="nt",
        environ=environ,
        home=tmp_path,
    ) == appdata / "tooldeck"
    assert paths._location(
        "XDG_STATE_HOME",
        "~/.local/state",
        "LOCALAPPDATA",
        "AppData/Local",
        platform_name="nt",
        environ=environ,
        home=tmp_path,
    ) == local_appdata / "tooldeck"
