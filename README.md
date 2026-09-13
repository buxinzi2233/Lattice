# Lattice / 晶格中枢

Lattice is a Windows/Linux desktop process console for local AI tools and long-running scripts. It keeps each tool's command, working directory, environment, process-tree state, and persistent log in one operational interface.

Lattice 是面向 Windows/Linux 的本地进程控制台，用于统一管理 AI 工具和长时间运行脚本。现有兼容名称保持不变：Python 包、命令行入口以及配置目录仍使用 `tooldeck`。

## Guides / 指南

- [中文安装指南](docs/zh/INSTALL.md)
- [中文使用与故障排查](docs/zh/USAGE.md)
- [English installation guide](docs/en/INSTALL.md)
- [English usage and troubleshooting](docs/en/USAGE.md)
- [Copyright and safety notice / 版权与安全声明](NOTICE.md)

## Highlights / 主要功能

- Persistent group and tool ordering in `layout.json`, collapsible groups, same-group and cross-group drag/drop.
- Search/status filters temporarily expand matching groups and disable reordering without mutating saved layout.
- Validated process-group stopping on Linux and `taskkill /T` process-tree stopping on Windows.
- Persistent logs, stable live view, file-manager reveal, and display-only clearing.
- 80%-150% interface text scaling and bundled Fira Sans/Fira Sans Condensed/JetBrains Mono fonts.
- Optional 4.2-second Rhine Lab-inspired startup sequence: daily, always, or off; offline fallback; no audio or telemetry.
- Source install/repair scripts and a Windows portable build workflow.

## Quick Start / 快速开始

Linux:

    ./install.sh
    tooldeck-gui

Windows PowerShell:

    Set-ExecutionPolicy -Scope Process Bypass
    .\install.ps1 -StartMenuShortcut
    .\.venv\Scripts\tooldeck-gui.exe

CLI examples:

    tooldeck list
    tooldeck start comfyui
    tooldeck logs -f comfyui
    tooldeck stop comfyui

## Tool Configuration / 工具配置

Tool TOMLs live in `~/.config/tooldeck/tools.d/` on Linux and `%APPDATA%\tooldeck\tools.d\` on Windows. Example:

    name = "My Server"
    group = "Services"
    cmd = "python app.py"
    cwd = "~/Projects/my-server"
    shell = "/bin/bash"
    autostart = false
    stop_signal = "TERM"
    stop_timeout = 15

The `group` field owns group membership. `layout.json` only owns group order, tool order, and collapsed state. A corrupt layout is reported without overwriting the file; repair the reported file or move it aside before reloading the configuration.

## Development / 开发

    uv sync --frozen --extra dev
    QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software uv run pytest -q
    uv run ruff check src tests
    uv run pyside6-qmllint src/tooldeck/gui/qml/Main.qml src/tooldeck/gui/qml/components/*.qml

Lattice source code is MIT licensed. Official artwork, trademarks, character names, story text, quotes, and other third-party materials are excluded from that license and are not distributed in this repository or release archives.
