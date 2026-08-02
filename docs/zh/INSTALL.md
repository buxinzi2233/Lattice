# Lattice 安装指南

## Linux

要求 64 位 Linux。运行 `./install.sh`；脚本优先使用 Python 3.12 和现有 `uv`，缺失时下载固定版本 `uv` 并用 `uv python install 3.12` 补齐 Lattice 自身依赖。脚本不会修改已登记工具的虚拟环境。

若 Qt 系统库缺失，安装器只输出 Debian/Ubuntu、Fedora 或 Arch 的建议命令，不会自动执行 `sudo`。修复源码环境可删除 `.venv` 后重跑安装器；配置、布局和日志不在仓库虚拟环境中，不受影响。

## Windows

在 PowerShell 中运行：

    Set-ExecutionPolicy -Scope Process Bypass
    .\install.ps1 -StartMenuShortcut

缺少 Python 3.12 或 `uv` 时脚本自动下载。修复模式使用 `.\install.ps1 -Repair`，只重建 Lattice 的 `.venv`。便携包可从 Release 解压后直接运行，不要求系统 Python。

## 数据位置

Linux 配置为 `~/.config/tooldeck/`，状态/日志为 `~/.local/state/tooldeck/`。Windows 配置为 `%APPDATA%\tooldeck\`，状态/日志为 `%LOCALAPPDATA%\tooldeck\`。
