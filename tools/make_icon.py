#!/usr/bin/env python3
"""渲染应用图标（1024px PNG），供 macOS .app 打包使用。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PyQt6.QtCore import QRectF, Qt  # noqa: E402
from PyQt6.QtGui import QColor, QLinearGradient, QPainter, QPen, QPixmap  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402


def render(size: int = 1024) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    # 背后一层半透明卡片，暗示“透出来的窗口”
    back = QRectF(size * 0.14, size * 0.14, size * 0.74, size * 0.74)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(74, 58, 40, 52))
    p.drawRoundedRect(back, size * 0.16, size * 0.16)

    # 前面一张纸
    r = QRectF(size * 0.1, size * 0.1, size * 0.72, size * 0.72)
    grad = QLinearGradient(r.topLeft(), r.bottomRight())
    grad.setColorAt(0.0, QColor("#FAF4E7"))
    grad.setColorAt(1.0, QColor("#E8DCC5"))
    p.setBrush(grad)
    p.drawRoundedRect(r, size * 0.18, size * 0.18)

    # 文字线条
    ink = QColor("#4A3A28")
    p.setBrush(ink)
    y = r.top() + size * 0.2
    widths = [0.42, 0.34, 0.4, 0.28, 0.36]
    for i, wf in enumerate(widths):
        h = size * (0.032 if i else 0.05)
        p.drawRoundedRect(QRectF(r.left() + size * 0.11, y, size * wf, h), h / 2, h / 2)
        y += h + size * 0.052

    p.end()
    return pm


def main() -> int:
    app = QApplication(sys.argv[:1])
    out = ROOT / "assets"
    out.mkdir(exist_ok=True)
    pm = render(1024)
    pm.save(str(out / "icon_1024.png"))
    # Windows 打包需要 .ico
    try:
        ico = render(256)
        ico.save(str(out / "icon.ico"), "ICO")
        print(out / "icon.ico")
    except Exception as exc:
        print("生成 .ico 失败：", exc)

    for s in (512, 256, 128, 64, 32, 16):
        pm.scaled(s, s, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation).save(
            str(out / f"icon_{s}.png")
        )
    print(out / "icon_1024.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
