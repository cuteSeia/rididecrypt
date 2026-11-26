#!/bin/sh
set -eu

PROJECT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$PROJECT_ROOT"

uv sync --group build
uv run python packaging/generate_icon.py
uv run pyinstaller \
    --clean \
    --noconfirm \
    --windowed \
    --name RidiDecryptor \
    --icon packaging/RidiDecryptor.icns \
    --osx-bundle-identifier com.caties.rididecryptor \
    --paths src \
    packaging/launcher.py

mkdir -p dist
rm -f dist/RidiDecryptor-macos-arm64.zip
ditto -c -k --sequesterRsrc --keepParent dist/RidiDecryptor.app dist/RidiDecryptor-macos-arm64.zip
