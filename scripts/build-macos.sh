#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip setuptools wheel
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m PyInstaller --noconfirm --clean photo-fit-picker.spec

STAGING_DIR="$(mktemp -d)"
trap 'rm -rf "$STAGING_DIR"' EXIT
cp -R "dist/拾影.app" "$STAGING_DIR/"
ln -s /Applications "$STAGING_DIR/Applications"
mkdir -p dist/release
hdiutil create \
    -volname "拾影" \
    -srcfolder "$STAGING_DIR" \
    -ov \
    -format UDZO \
    dist/release/PhotoFitPicker-macOS.dmg

echo "Build complete: dist/release/PhotoFitPicker-macOS.dmg"
