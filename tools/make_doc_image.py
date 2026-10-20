#!/usr/bin/env python3
"""生成带标注的界面布局说明图（用于文档与预览）。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PyQt6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PyQt6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter, QPen  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402


def font(size: int, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    families = QFontDatabase.families()
    name = next((f for f in ("PingFang SC", "Hiragino Sans GB", "Microsoft YaHei") if f in families), "")
    f = QFont(name) if name else QFont()
    f.setPointSize(size)
    f.setWeight(weight)
    return f


ANNOTATIONS = [
    # (标签中心 y, 目标 x, 目标 y, 标题, 说明)
    (88, 762, 88, "① 标题栏", "拖动移动窗口 · 目录 / 置顶 / 幽灵 / 设置 / 最小化 / 关闭"),
    (330, 762, 330, "② 正文区", "半透明纸面 · 字号 / 行距 / 栏宽 / 首行缩进可调"),
    (690, 762, 690, "③ 阅读栏", "栏宽 720px，窗口变宽只增加留白，不拉长行宽"),
    (918, 786, 918, "④ 状态栏", "当前章节与全书进度，顶部细线同步指示"),
]


def main() -> int:
    app = QApplication(sys.argv[:1])
    src_path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs" / "shots" / "read.png"
    src = QImage(str(src_path))
    if src.isNull():
        print(f"缺少底图：{src_path}")
        return 1

    pad_r, pad_b, pad_t = 356, 60, 76
    w = src.width() + pad_r
    h = src.height() + pad_b + pad_t
    canvas = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    canvas.fill(QColor("#12161d"))

    p = QPainter(canvas)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

    # 标题
    p.setPen(QPen(QColor("#E8E4DA")))
    p.setFont(font(17, QFont.Weight.DemiBold))
    p.drawText(QRectF(40, 22, 600, 30), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "GhostReader 界面布局")
    p.setPen(QPen(QColor("#7E8794")))
    p.setFont(font(10))
    p.drawText(
        QRectF(40, 50, 700, 20),
        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        "无边框半透明窗口 · 背景 88% 不透明度 · 文字默认完全不透明（可单独调淡）",
    )

    p.drawImage(0, pad_t, src)

    label_w = 316
    label_x = src.width() + 16
    for y_label, tx, ty, title, desc in ANNOTATIONS:
        top = pad_t + y_label - 26
        rect = QRectF(label_x, top, label_w, 52)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(240, 236, 226, 240))
        p.drawRoundedRect(rect, 9, 9)

        # 引线
        pen = QPen(QColor(200, 160, 110, 150), 1.2)
        p.setPen(pen)
        p.drawLine(QPointF(label_x - 1, top + 26), QPointF(tx, pad_t + ty))
        p.setBrush(QColor(200, 160, 110, 240))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(tx, pad_t + ty), 3.0, 3.0)

        p.setPen(QPen(QColor("#2B2318")))
        p.setFont(font(11, QFont.Weight.DemiBold))
        p.drawText(QRectF(label_x + 14, top + 7, label_w - 24, 18),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, title)
        p.setPen(QPen(QColor("#6C6252")))
        p.setFont(font(8))
        p.drawText(QRectF(label_x + 14, top + 26, label_w - 24, 20),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, desc)

    p.end()
    out = ROOT / "docs" / "layout.png"
    out.parent.mkdir(exist_ok=True)
    canvas.save(str(out))
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
