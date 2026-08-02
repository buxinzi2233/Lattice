# Lattice Installation

## Linux

Run `./install.sh` on a 64-bit Linux system. The installer prefers Python 3.12 and an existing `uv`; when missing it downloads a pinned `uv` and installs Python 3.12 for Lattice. It never modifies environments owned by registered tools.

Missing Qt system libraries are reported with Debian/Ubuntu, Fedora, or Arch commands. The script never runs privileged package installation. Recreate only Lattice's environment by removing `.venv` and rerunning the installer.

## Windows

Run in PowerShell:

    Set-ExecutionPolicy -Scope Process Bypass
    .\install.ps1 -StartMenuShortcut

Use `.\install.ps1 -Repair` to rebuild only the Lattice environment. The portable release does not require a system Python installation.

## Data directories

Linux configuration: `~/.config/tooldeck/`; state and logs: `~/.local/state/tooldeck/`. Windows configuration: `%APPDATA%\tooldeck\`; state and logs: `%LOCALAPPDATA%\tooldeck\`.
