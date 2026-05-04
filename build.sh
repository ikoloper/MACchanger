#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if command -v uv >/dev/null 2>&1; then
  uv run pyinstaller --clean --noconfirm MACchanger.spec
else
  python3 -m PyInstaller --clean --noconfirm MACchanger.spec
fi

echo "Built dist/MACchanger.app"
