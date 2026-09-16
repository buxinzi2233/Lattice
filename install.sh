#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${LATTICE_PYTHON:-${TOOLDECK_PYTHON:-}}"
UV_VERSION="${LATTICE_UV_VERSION:-0.12.10}"
UV_BIN="$PROJECT_DIR/.local/uv"

detect_qt_packages() {
    if env -u QT_QPA_PLATFORMTHEME -u QT_QPA_PLATFORMTHEME_QT6 QT_QPA_PLATFORM=offscreen "$PROJECT_DIR/.venv/bin/python" - <<'PY' >/dev/null 2>&1
from PySide6.QtWidgets import QApplication
app = QApplication([])
PY
    then
        return 0
    fi
    echo "提示：系统 Qt 运行库可能缺失。Lattice 不会自动执行 sudo 安装。" >&2
    if command -v apt >/dev/null 2>&1; then
        echo "Debian/Ubuntu: sudo apt install libegl1 libgl1 libxcb-cursor0 libxkbcommon-x11-0" >&2
    elif command -v dnf >/dev/null 2>&1; then
        echo "Fedora: sudo dnf install mesa-libEGL mesa-libGL libxkbcommon-x11 xcb-util-cursor" >&2
    elif command -v pacman >/dev/null 2>&1; then
        echo "Arch: sudo pacman -S qt6-base qt6-wayland libxcb xcb-util-cursor" >&2
    fi
}

download_uv() {
    mkdir -p "$PROJECT_DIR/.local"
    arch="$(uname -m)"
    case "$arch" in
        x86_64|amd64) target="x86_64-unknown-linux-gnu" ;;
        aarch64|arm64) target="aarch64-unknown-linux-gnu" ;;
        *) echo "错误：不支持的 Linux 架构：$arch" >&2; exit 1 ;;
    esac
    case "$target" in
        x86_64-unknown-linux-gnu) expected_sha="017ce7ed02c967f1b0489f09162e19ee3df4586a44e681211d16206e007fce62" ;;
        aarch64-unknown-linux-gnu) expected_sha="e7f358efb0718bd8f98dc0c29fd0902323b590381ca765537063a2ca23ed34c7" ;;
    esac
    url="https://github.com/astral-sh/uv/releases/download/$UV_VERSION/uv-$target.tar.gz"
    tmp="$(mktemp -d)"
    trap 'rm -rf "$tmp"' EXIT
    curl -L --fail --connect-timeout 15 --max-time 120 -o "$tmp/uv.tar.gz" "$url"
    printf '%s  %s\n' "${LATTICE_UV_SHA256:-$expected_sha}" "$tmp/uv.tar.gz" | sha256sum -c -
    tar -xzf "$tmp/uv.tar.gz" -C "$tmp"
    found="$(find "$tmp" -type f -name uv | head -1)"
    install -m 0755 "$found" "$UV_BIN"
}

if ! command -v uv >/dev/null 2>&1; then
    if [ ! -x "$UV_BIN" ]; then
        download_uv
    fi
    PATH="$PROJECT_DIR/.local:$PATH"
fi
if [ -z "$PYTHON_BIN" ]; then
    if command -v python3.12 >/dev/null 2>&1; then
        PYTHON_BIN="$(command -v python3.12)"
    else
        uv python install 3.12
        PYTHON_BIN="$(uv python find 3.12)"
    fi
fi
if [ ! -x "$PYTHON_BIN" ]; then
    echo "错误：Python 不可执行：$PYTHON_BIN" >&2
    exit 1
fi

if [ ! -x "$PROJECT_DIR/.venv/bin/python" ]; then
    uv venv "$PROJECT_DIR/.venv" --python "$PYTHON_BIN"
fi
if [ -f "$PROJECT_DIR/uv.lock" ]; then
    uv sync --frozen --project "$PROJECT_DIR" --extra dev
else
    uv pip install --python "$PROJECT_DIR/.venv/bin/python" -e "$PROJECT_DIR[dev]"
fi
detect_qt_packages || true

mkdir -p "$HOME/.local/bin" "$HOME/.config/tooldeck/tools.d" "$HOME/.local/share/applications"
ln -sfn "$PROJECT_DIR/.venv/bin/tooldeck" "$HOME/.local/bin/tooldeck"
ln -sfn "$PROJECT_DIR/.venv/bin/tooldeck-gui" "$HOME/.local/bin/tooldeck-gui"

for seed in "$PROJECT_DIR"/seeds/*.toml; do
    destination="$HOME/.config/tooldeck/tools.d/$(basename "$seed")"
    if [ ! -e "$destination" ]; then
        cp "$seed" "$destination"
    fi
done

desktop="$HOME/.local/share/applications/tooldeck.desktop"
sed \
    -e "s|^Exec=.*|Exec=$PROJECT_DIR/.venv/bin/tooldeck-gui|" \
    -e "s|^TryExec=.*|TryExec=$PROJECT_DIR/.venv/bin/tooldeck-gui|" \
    -e "s|^Icon=.*|Icon=$PROJECT_DIR/src/tooldeck/gui/assets/lattice-mark.svg|" \
    "$PROJECT_DIR/packaging/tooldeck.desktop" > "$desktop"

echo "Lattice 已安装。运行：tooldeck-gui"
echo "配置目录：$HOME/.config/tooldeck/tools.d"
