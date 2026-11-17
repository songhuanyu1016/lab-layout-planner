#!/usr/bin/env bash
# ==========================================================================
#  Build LabLayoutPlanner.app (macOS)
#
#  Result:
#    dist/LabLayoutPlanner-mac/LabLayoutPlanner.app
#    dist/LabLayoutPlanner-mac/Library/        (component library, editable)
#
#  Keep the .app and the Library folder side by side.
# ==========================================================================
set -euo pipefail
cd "$(dirname "$0")"

PY=.venv/bin/python

if [ -x "$PY" ]; then
    echo "[1/5] Using existing virtual environment .venv"
else
    echo "[1/5] No .venv found - creating local virtual environment ..."
    BASEPY=""
    for c in python3.12 python3; do
        if command -v "$c" >/dev/null 2>&1; then BASEPY="$c"; break; fi
    done
    if [ -z "$BASEPY" ]; then
        echo "ERROR: Python 3 was not found. Install Python 3.12 from python.org" >&2
        exit 1
    fi
    echo "      using: $BASEPY"
    "$BASEPY" -m venv .venv
fi

echo "[2/5] Installing dependencies ..."
"$PY" -m pip install --upgrade pip >/dev/null
"$PY" -m pip install -r requirements.txt pyinstaller matplotlib pillow

echo "[3/5] Generating icon ..."
"$PY" assets/make_icon.py

echo "[4/5] Running PyInstaller (this can take several minutes) ..."
"$PY" -m PyInstaller --noconfirm --clean lab_layout.spec

echo "[5/5] Assembling dist/LabLayoutPlanner-mac ..."
OUT=dist/LabLayoutPlanner-mac
rm -rf "$OUT"
mkdir -p "$OUT"
ditto dist/LabLayoutPlanner.app "$OUT/LabLayoutPlanner.app"
cp -R Library "$OUT/Library"

echo
echo "Build complete: $(pwd)/$OUT/LabLayoutPlanner.app"
