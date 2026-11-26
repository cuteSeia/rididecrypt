from __future__ import annotations

import os
import subprocess
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer


ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "packaging"
ICONSET = ROOT / "build" / "RidiDecryptor.iconset"


def main() -> None:
    app = QGuiApplication([])
    svg = (ASSETS / "rididecryptor.svg").read_bytes()
    renderer = QSvgRenderer(svg)
    if not renderer.isValid():
        raise RuntimeError("아이콘 SVG를 읽을 수 없습니다")

    image = QImage(1024, 1024, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()
    if not image.save(str(ASSETS / "rididecryptor.png")):
        raise RuntimeError("아이콘 PNG를 저장할 수 없습니다")

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
        scaled = image.scaled(size, size, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
        if not scaled.save(str(ICONSET / filename)):
            raise RuntimeError(f"아이콘 크기 생성 실패: {filename}")

    subprocess.run(
        ["iconutil", "-c", "icns", str(ICONSET), "-o", str(ASSETS / "RidiDecryptor.icns")],
        check=True,
    )
    app.quit()


if __name__ == "__main__":
    main()
