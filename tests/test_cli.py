from __future__ import annotations

import os
import shlex
import subprocess
import sys
import tempfile

from tooldeck import paths
from tooldeck.cli import main
from tooldeck.config import load_file


def python_command(code: str) -> str:
    parts = [sys.executable, "-c", code]
    return subprocess.list2cmdline(parts) if os.name == "nt" else shlex.join(parts)


def test_cli_add_list_start_stop_remove(capsys):
    assert main([
        "add",
        "demo",
        "--name",
        "Demo",
        "--group",
        "实验服务",
        "--cmd",
        python_command("import time; time.sleep(60)"),
        "--cwd",
        tempfile.gettempdir(),
        "--stop-timeout",
        "0.1",
    ]) == 0
    assert main(["list"]) == 0
    output = capsys.readouterr().out
    assert "Demo" in output
    assert "实验服务" in output
    assert main(["edit", "demo", "--group", "常驻服务"]) == 0
    assert load_file(paths.tool_toml("demo")).group == "常驻服务"
    assert main(["start", "demo"]) == 0
    assert main(["stop", "demo"]) == 0
    assert main(["remove", "demo"]) == 0


def test_cli_reports_unknown_tool(capsys):
    assert main(["start", "missing"]) == 1
    assert "不存在" in capsys.readouterr().err
