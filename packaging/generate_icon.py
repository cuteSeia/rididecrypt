from __future__ import annotations

import subprocess
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "packaging"
ICONSET = ROOT / "build" / "RidiDecryptor.iconset"


def main() -> None:
    image = Image.open(ASSETS / "rididecryptor.png").convert("RGBA")

    ICONSET.mkdir(parents=True, exist_ok=True)
    variants = (
        ("icon_16x16.png", 16),
        ("icon_16x16@2x.png", 32),
        ("icon_32x32.png", 32),
        ("icon_32x32@2x.png", 64),
        ("icon_128x128.png", 128),
        ("icon_128x128@2x.png", 256),
        ("icon_256x256.png", 256),
        ("icon_256x256@2x.png", 512),
        ("icon_512x512.png", 512),
        ("icon_512x512@2x.png", 1024),
    )
    for filename, size in variants:
        scaled = image.resize((size, size), Image.Resampling.LANCZOS)
        scaled.save(ICONSET / filename, format="PNG")

    subprocess.run(
        ["iconutil", "-c", "icns", str(ICONSET), "-o", str(ASSETS / "RidiDecryptor.icns")],
        check=True,
    )
if __name__ == "__main__":
    main()
