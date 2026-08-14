#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Linux" ]]; then
    echo "This script must be run on Linux."
    exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APPLICATIONS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICONS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/64x64/apps"
DESKTOP_FILE="$APPLICATIONS_DIR/openglider.desktop"

mkdir -p "$APPLICATIONS_DIR" "$ICONS_DIR"

install -m 0644 "$ROOT_DIR/openglider/gui/openglider.png" "$ICONS_DIR/openglider.png"

launcher_path=""
if command -v openglider >/dev/null 2>&1; then
    launcher_path="$(command -v openglider)"
elif [[ -x "$ROOT_DIR/.venv/bin/openglider" ]]; then
    launcher_path="$ROOT_DIR/.venv/bin/openglider"
elif [[ -x "$ROOT_DIR/../venv/bin/openglider" ]]; then
    launcher_path="$ROOT_DIR/../venv/bin/openglider"
fi

if [[ -z "$launcher_path" ]]; then
    echo "Could not find an openglider executable."
    echo "Install OpenGlider first (for example: uv pip install -e .) and rerun this script."
    exit 1
fi

cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=OpenGlider
Comment=Paraglider design and simulation
Exec=$launcher_path
TryExec=$launcher_path
Icon=openglider
Categories=Science;Engineering;
Keywords=glider;paraglider;design;simulation;
Terminal=false
StartupNotify=true
StartupWMClass=openglider
EOF

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$APPLICATIONS_DIR" || true
fi

if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f -t "${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor" || true
fi

echo "Installed OpenGlider desktop entry to $DESKTOP_FILE"
echo "Installed OpenGlider icon to $ICONS_DIR/openglider.png"
echo "Launcher executable: $launcher_path"