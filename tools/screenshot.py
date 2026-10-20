#!/usr/bin/env python3
"""离屏截图：把窗口合成到一张模拟桌面上，用来检查半透明下的真实观感。

    python tools/screenshot.py out.png --state settings --alpha 0.86
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["GHOSTREADER_NO_HOTKEY"] = "1"

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PyQt6.QtCore import QPoint, QRectF, Qt  # noqa: E402
from PyQt6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen, QPixmap  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from ghostreader.settings import Settings  # noqa: E402
from ghostreader.window import MainWindow  # noqa: E402


def desktop_mock(w: int, h: int) -> QPixmap:
    """模拟“桌面 + 编辑器”的真实背景，用来判断半透明下的可读性。"""
    pm = QPixmap(w, h)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    # 壁纸：深色渐变 + 两团柔光
    grad = QLinearGradient(0, 0, w, h)
    grad.setColorAt(0.0, QColor("#141a22"))
    grad.setColorAt(0.6, QColor("#1d2732"))
    grad.setColorAt(1.0, QColor("#2a3038"))
    p.fillRect(0, 0, w, h, grad)
    from PyQt6.QtGui import QRadialGradient
    for cx, cy, r, col in ((w * 0.18, h * 0.15, w * 0.5, QColor(90, 130, 180, 60)),
                           (w * 0.85, h * 0.9, w * 0.45, QColor(180, 140, 90, 45))):
        rg = QRadialGradient(cx, cy, r)
        rg.setColorAt(0.0, col)
        rg.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setBrush(rg)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))

    # 编辑器窗口
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(24, 27, 33, 240))
    p.drawRoundedRect(QRectF(70, 80, w - 200, h - 210), 10, 10)
    p.setBrush(QColor(32, 36, 43, 245))
    p.drawRoundedRect(QRectF(70, 80, w - 200, 32), 10, 10)
    # 侧栏
    p.setBrush(QColor(28, 31, 37, 240))
    p.drawRoundedRect(QRectF(70, 112, 120, h - 242), 0, 0)
    for i in range(9):
        p.setBrush(QColor(120, 130, 145, 70))
        p.drawRoundedRect(QRectF(84, 130 + i * 20, 80 - (i % 3) * 18, 5), 2, 2)

    # 代码行：细横条 + 行号，接近真实编辑器观感
    code_colors = [QColor(122, 162, 247, 130), QColor(158, 206, 106, 120),
                   QColor(224, 175, 104, 120), QColor(187, 154, 247, 120),
                   QColor(130, 140, 155, 90)]
    y = 132
    idx = 0
    while y < h - 200:
        p.setBrush(QColor(90, 100, 115, 60))
        p.drawRoundedRect(QRectF(198, y - 4, 14, 4), 2, 2)
        x = 226
        for k in range((idx * 5) % 4 + 1):
            c = code_colors[(idx + k) % len(code_colors)]
            width = 48 + ((idx * 41 + k * 67) % 170)
            p.setBrush(c)
            p.drawRoundedRect(QRectF(x, y - 4, width, 5), 2.5, 2.5)
            x += width + 16
        y += 21
        idx += 1
    p.end()
    return pm


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--state", default="read", choices=["read", "toc", "settings", "ghost", "empty", "dark"])
    ap.add_argument("--alpha", type=float, default=None)
    ap.add_argument("--width", type=int, default=760)
    ap.add_argument("--height", type=int, default=880)
    ap.add_argument("--font", type=float, default=None)
    ap.add_argument("--chapter", type=int, default=1)
    ap.add_argument("--book", default="")
    ap.add_argument("--toc", action="store_true")
    args = ap.parse_args()

    app = QApplication(sys.argv[:1])
    s = Settings()
    s.win_w, s.win_h = args.width, args.height
    s.win_x, s.win_y = 40, 40
    s.last_book = ""
    s.always_on_top = True
    if args.alpha is not None:
        s.bg_alpha = args.alpha
    if args.font is not None:
        s.font_size = args.font
    if args.state == "dark":
        s.theme_index = 3
        s.bg_color = "#1C1D21"
        s.text_color = "#C9CBCF"
        s.bg_alpha = args.alpha if args.alpha is not None else 0.9

    win = MainWindow(s)
    win.resize(args.width, args.height)
    if args.state != "empty":
        book = args.book or str(ROOT / "samples" / "night-reading.epub")
        win.open_book(book, silent=True)
        win.reader.goto_chapter(args.chapter, 0.0, keep_focus=False)
        win._update_status()
    win.show()
    app.processEvents()

    if args.state == "toc":
        win.toggle_toc()
    elif args.state == "settings":
        win.toggle_settings()
    elif args.state == "ghost":
        win.toggle_ghost()
        win._mouse_inside = True
        win._apply_opacity(animate=False)

    if args.toc:
        win.toggle_toc()

    # 让入场动画跑完再截图
    from PyQt6.QtCore import QEventLoop, QTimer
    loop = QEventLoop()
    QTimer.singleShot(450, loop.quit)
    loop.exec()
    app.processEvents()

    w, h = win.width(), win.height()
    shot = QPixmap(w, h)
    shot.fill(Qt.GlobalColor.transparent)
    win.render(shot, QPoint(0, 0))

    pad = 60
    canvas = desktop_mock(w + pad * 2, h + pad * 2)
    p = QPainter(canvas)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    op = win.windowOpacity()
    if op <= 0.02:   # offscreen 下 setWindowOpacity 不生效，幽灵模式按 1.0 合成
        op = 1.0
    p.setOpacity(max(0.05, min(1.0, op)))
    p.drawPixmap(pad, pad, shot)
    p.end()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(str(out))
    print(f"saved {out} ({canvas.width()}x{canvas.height()})")
    win.hotkeys.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
