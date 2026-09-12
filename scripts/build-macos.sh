#!/usr/bin/env bash
set -euo pipefail

python3 -m pip install --upgrade pip
python3 -m pip install -e ".[dev]"
python3 -m PyInstaller --noconfirm --clean photo-fit-picker.spec

echo "Build complete: dist/拾影.app"
