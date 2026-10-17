#!/usr/bin/env bash
set -euo pipefail

if [[ "${OSTYPE:-}" != msys* && "${OSTYPE:-}" != cygwin* && "${OS:-}" != Windows_NT ]]; then
    echo "This script must be run on Windows (PowerShell, Git Bash, or WSL with Windows Python)."
    exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if command -v uv >/dev/null 2>&1; then
    if [[ "${CI:-}" == "true" ]]; then
        uv pip install --system -e ".[gui]"
        uv pip install --system pyinstaller
        PYTHON_FOR_PYINSTALLER=(python)
    elif [[ -n "${VIRTUAL_ENV:-}" ]]; then
        uv pip install -e ".[gui]"
        uv pip install pyinstaller
        PYTHON_FOR_PYINSTALLER=(python)
    else
        if [[ ! -d ".venv" ]]; then
            uv venv .venv
        fi
        uv pip install --python .venv/Scripts/python.exe -e ".[gui]"
        uv pip install --python .venv/Scripts/python.exe pyinstaller
        PYTHON_FOR_PYINSTALLER=(.venv/Scripts/python.exe)
    fi
else
    python -m pip install --upgrade pip
    python -m pip install -e ".[gui]"
    python -m pip install pyinstaller
    PYTHON_FOR_PYINSTALLER=(python)
fi

"${PYTHON_FOR_PYINSTALLER[@]}" -m PyInstaller \
    --noconfirm \
    --clean \
    --onedir \
    --windowed \
    --name OpenGlider \
    --collect-all openglider \
    --collect-all odfdo \
    --collect-all debugpy \
    --collect-all qtawesome \
    --collect-all pyqtgraph \
    --hidden-import PySide6 \
    scripts/launch_gui.py

echo "Windows application folder created at: $ROOT_DIR/dist/OpenGlider (run OpenGlider.exe inside)"
