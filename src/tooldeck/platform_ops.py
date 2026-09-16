"""Platform-specific desktop actions without a dependency on Qt."""

from __future__ import annotations

import shutil
import sys
from collections.abc import Callable
from pathlib import Path

StartDetached = Callable[[str, list[str]], bool]
OpenDirectory = Callable[[Path], bool]


def reveal_path(
    path: Path,
    *,
    start_detached: StartDetached,
    open_directory: OpenDirectory,
    platform_name: str | None = None,
    which: Callable[[str], str | None] = shutil.which,
) -> bool:
    target = Path(path).resolve()
    platform = platform_name or sys.platform
    if platform == "win32":
        return start_detached("explorer.exe", [f"/select,{target}"])
    if platform == "darwin":
        return start_detached("open", ["-R", str(target)])

    reveal_commands = (
        ("thunar", ["--select", str(target)]),
        ("dolphin", ["--select", str(target)]),
        ("nautilus", ["--select", str(target)]),
        ("nemo", [str(target)]),
    )
    for program, arguments in reveal_commands:
        if which(program) and start_detached(program, arguments):
            return True
    return open_directory(target.parent)
