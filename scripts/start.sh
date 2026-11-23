#!/usr/bin/env bash
# SubVision AI — Linux & macOS (x86_64 / Apple Silicon ARM64) Otomatik Kurulum ve Başlatıcı

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

VENV_DIR="$REPO_ROOT/.venv"
MARKER_FILE="$VENV_DIR/.deps_installed"

# Python 3.10+ yorumlayıcısını bul
PYTHON_BIN=""
for candidate in python3.12 python3.11 python3.10 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
        if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
            PYTHON_BIN="$candidate"
            break
        fi
    fi
done

if [ -z "$PYTHON_BIN" ]; then
    echo "[HATA] Python 3.10 veya üzeri bulunamadı. Lütfen Python 3.10+ kurun."
    exit 1
fi

if [ ! -x "$VENV_DIR/bin/python" ]; then
    echo "[1/2] Sanal ortam (.venv) oluşturuluyor ($($PYTHON_BIN --version))..."
    "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

if [ ! -f "$MARKER_FILE" ]; then
    echo "[2/2] Bağımlılıklar kuruluyor (PyQt6, RapidOCR, CTranslate2)..."
    "$VENV_DIR/bin/python" -m pip install --upgrade pip >/dev/null 2>&1 || true
    "$VENV_DIR/bin/python" -m pip install --prefer-binary -r "$REPO_ROOT/requirements.txt"
    touch "$MARKER_FILE"
fi

echo "[OK] SubVision AI başlatılıyor..."
exec "$VENV_DIR/bin/python" "$REPO_ROOT/main.py" "$@"
