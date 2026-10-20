"""界面组件：全部用矢量绘制，不依赖任何图片资源，保证半透明下依旧锐利。"""

from __future__ import annotations

from PyQt6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSize,
    Qt,
    QVariantAnimation,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QFontMetrics,
    QGuiApplication,
    QIcon,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QComboBox,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from .epub import Book
from .settings import THEMES, Settings


# ------------------------------------------------------------------ 颜色工具


def qcolor(value: str) -> QColor:
    c = QColor(value)
    return c if c.isValid() else QColor("#000000")


def rgba(c: QColor, alpha: float) -> str:
    return f"rgba({c.red()},{c.green()},{c.blue()},{int(max(0.0, min(1.0, alpha)) * 255)})"


def qca(c: QColor, alpha: float) -> QColor:
    """返回带透明度的颜色副本，供 QPen/QBrush 使用。"""
    out = QColor(c)
    out.setAlphaF(max(0.0, min(1.0, alpha)))
    return out


def mix(a: QColor, b: QColor, t: float) -> QColor:
    t = max(0.0, min(1.0, t))
    return QColor(
        int(a.red() + (b.red() - a.red()) * t),
        int(a.green() + (b.green() - a.green()) * t),
        int(a.blue() + (b.blue() - a.blue()) * t),
    )


class Palette:
    """由设置推导出的一套配色，切换主题时整体重算。"""

    def __init__(self, s: Settings):
        self.bg = qcolor(s.bg_color)
        self.fg = qcolor(s.text_color)
        light = self.bg.lightness() > 128
        self.light = light
        toward = QColor("#FFFFFF") if light else QColor("#000000")
        # 面板（目录 / 设置）只比纸面深一点点，避免看起来像蒙了一层灰
        self.panel = mix(self.bg, self.fg, 0.018 if light else 0.045)
        self.raised = mix(self.bg, self.fg, 0.055 if light else 0.10)
        self.border = mix(self.bg, self.fg, 0.16)
        self.hover = mix(self.bg, self.fg, 0.10)
        self.muted = mix(self.fg, self.bg, 0.42)
        self.faint = mix(self.fg, self.bg, 0.62)
        self.accent = QColor("#A9743F") if light else QColor("#8FA6C0")
        self.accent_soft = mix(self.bg, self.accent, 0.18)


def ui_font(size: int = 12, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    families = QFontDatabase.families()
    for name in ("PingFang SC", "Hiragino Sans GB", "Microsoft YaHei UI", "Microsoft YaHei", "Noto Sans CJK SC"):
        if name in families:
            f = QFont(name)
            break
    else:
        f = QGuiApplication.font()
    f.setPointSize(size)
    f.setWeight(weight)
    return f


# ------------------------------------------------------------------ 矢量图标

_ICONS = ("menu", "pin", "sliders", "ghost", "close", "min", "plus", "minus",
          "chevron", "book", "search", "eye", "folder")


def paint_icon(p: QPainter, name: str, r: QRectF, color: QColor, width: float = 1.5) -> None:
    pen = QPen(color, width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    cx, cy = r.center().x(), r.center().y()
    w, h = r.width(), r.height()

    if name == "menu":
        for i, frac in enumerate((0.0, 0.34, 0.68)):
            y = r.top() + h * 0.22 + h * 0.28 * i
            p.drawLine(QPointF(r.left(), y), QPointF(r.left() + w * (0.9 if i != 2 else 0.62), y))
    elif name == "pin":
        # 置顶：顶部横线 + 向上箭头
        p.drawLine(QPointF(r.left() + w * 0.2, r.top() + h * 0.18),
                   QPointF(r.right() - w * 0.2, r.top() + h * 0.18))
        p.drawLine(QPointF(cx, r.bottom() - h * 0.12), QPointF(cx, r.top() + h * 0.40))
        p.drawLine(QPointF(cx, r.top() + h * 0.40), QPointF(cx - w * 0.22, r.top() + h * 0.60))
        p.drawLine(QPointF(cx, r.top() + h * 0.40), QPointF(cx + w * 0.22, r.top() + h * 0.60))
    elif name == "sliders":
        for i, (yy, frac) in enumerate(((0.26, 0.34), (0.5, 0.66), (0.74, 0.45))):
            y = r.top() + h * yy
            p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
            p.setBrush(color)
            p.drawEllipse(QPointF(r.left() + w * frac, y), width * 1.35, width * 1.35)
            p.setBrush(Qt.BrushStyle.NoBrush)
    elif name == "ghost":
        outer = QPainterPath()
        outer.addEllipse(QRectF(r.left() + w * 0.1, r.top() + h * 0.08, w * 0.78, h * 0.84))
        inner = QPainterPath()
        inner.addEllipse(QRectF(r.left() + w * 0.38, r.top() + h * 0.0, w * 0.72, h * 0.78))
        p.setBrush(color)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPath(outer.subtracted(inner))
        p.setPen(pen)
    elif name == "close":
        p.drawLine(QPointF(r.left() + w * 0.22, r.top() + h * 0.22), QPointF(r.right() - w * 0.22, r.bottom() - h * 0.22))
        p.drawLine(QPointF(r.right() - w * 0.22, r.top() + h * 0.22), QPointF(r.left() + w * 0.22, r.bottom() - h * 0.22))
    elif name == "min":
        p.drawLine(QPointF(r.left() + w * 0.2, cy), QPointF(r.right() - w * 0.2, cy))
    elif name == "plus":
        p.drawLine(QPointF(r.left() + w * 0.2, cy), QPointF(r.right() - w * 0.2, cy))
        p.drawLine(QPointF(cx, r.top() + h * 0.2), QPointF(cx, r.bottom() - h * 0.2))
    elif name == "minus":
        p.drawLine(QPointF(r.left() + w * 0.2, cy), QPointF(r.right() - w * 0.2, cy))
    elif name == "chevron":
        p.drawPolyline(
            [
                QPointF(r.left() + w * 0.35, r.top() + h * 0.25),
                QPointF(r.right() - w * 0.35, cy),
                QPointF(r.left() + w * 0.35, r.bottom() - h * 0.25),
            ]
        )
    elif name == "folder":
        path = QPainterPath()
        path.moveTo(r.left() + w * 0.10, r.top() + h * 0.30)
        path.lineTo(r.left() + w * 0.40, r.top() + h * 0.30)
        path.lineTo(r.left() + w * 0.50, r.top() + h * 0.42)
        path.lineTo(r.right() - w * 0.10, r.top() + h * 0.42)
        path.lineTo(r.right() - w * 0.10, r.bottom() - h * 0.18)
        path.lineTo(r.left() + w * 0.10, r.bottom() - h * 0.18)
        path.closeSubpath()
        p.drawPath(path)
    elif name == "book":
        p.drawRoundedRect(QRectF(r.left() + w * 0.12, r.top() + h * 0.12, w * 0.76, h * 0.76), 2, 2)
        p.drawLine(QPointF(cx, r.top() + h * 0.16), QPointF(cx, r.bottom() - h * 0.16))
    elif name == "search":
        p.drawEllipse(QPointF(cx - w * 0.06, cy - h * 0.06), w * 0.26, h * 0.26)
        p.drawLine(QPointF(cx + w * 0.16, cy + h * 0.16), QPointF(r.right() - w * 0.12, r.bottom() - h * 0.12))
    elif name == "eye":
        path = QPainterPath()
        path.moveTo(r.left(), cy)
        path.quadTo(QPointF(cx, r.top() + h * 0.08), QPointF(r.right(), cy))
        path.quadTo(QPointF(cx, r.bottom() - h * 0.08), QPointF(r.left(), cy))
        p.drawPath(path)
        p.drawEllipse(QPointF(cx, cy), w * 0.13, w * 0.13)


class IconButton(QAbstractButton):
    """无边框图标按钮，支持 hover / checked 两种状态底色。"""

    def __init__(self, icon: str, tooltip: str = "", size: int = 28, parent=None):
        super().__init__(parent)
        self.icon_name = icon
        self.setCheckable(False)
        self.setToolTip(tooltip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(size, size)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._pal: Palette | None = None
        self._color = QColor("#666666")

    def set_palette_colors(self, pal: Palette) -> None:
        self._pal = pal
        self._color = pal.muted
        self.update()

    def enterEvent(self, e):
        if self._pal:
            self._color = self._pal.fg
            self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        if self._pal:
            self._color = self._pal.accent if self.isChecked() else self._pal.muted
            self.update()
        super().leaveEvent(e)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(self.rect())
        if self._pal:
            if self.isChecked():
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(self._pal.accent_soft)
                p.drawRoundedRect(r.adjusted(1, 1, -1, -1), 7, 7)
            elif self.underMouse():
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(self._pal.hover)
                p.drawRoundedRect(r.adjusted(1, 1, -1, -1), 7, 7)
        pad = r.width() * 0.25
        paint_icon(p, self.icon_name, r.adjusted(pad, pad, -pad, -pad), self._color, 1.5)
        p.end()

    def setChecked(self, checked: bool) -> None:  # noqa: N802
        super().setChecked(checked)
        if self._pal:
            self._color = self._pal.accent if checked else self._pal.muted
        self.update()


class Switch(QAbstractButton):
    """胶囊开关，带滑块动画。"""

    toggledByUser = pyqtSignal(bool)

    def __init__(self, checked: bool = False, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(38, 22)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._pos = 1.0 if checked else 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(140)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._on_anim)
        self._pal: Palette | None = None
        self.toggled.connect(self._on_toggle)

    def set_palette_colors(self, pal: Palette) -> None:
        self._pal = pal
        self.update()

    def _on_toggle(self, on: bool):
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()
        self.toggledByUser.emit(on)

    def _on_anim(self, v):
        self._pos = float(v)
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        pal = self._pal or Palette(Settings())
        track_off = mix(pal.bg, pal.fg, 0.18)
        track_on = mix(pal.bg, pal.accent, 0.55)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(mix(track_off, track_on, self._pos))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        d = r.height() - 5
        x = r.left() + 2.5 + (r.width() - d - 5) * self._pos
        p.setBrush(QColor("#FFFFFF") if pal.light else QColor("#EDEDED"))
        p.drawEllipse(QRectF(x, r.top() + 2.5, d, d))
        p.end()


class WheelForwarder(QObject):
    """把滚轮事件从滑块/下拉转发给滚动区。

    QSlider 默认响应滚轮改值，面板里滚动时鼠标一停在滑块上就会误改参数，
    所以这里统一把滚轮转交给外层 QScrollArea。
    """

    def __init__(self, target):
        super().__init__(target)
        self.target = target

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.Wheel:
            QApplication.sendEvent(self.target, ev)
            return True
        return False


class Slider(QSlider):
    def __init__(self, minimum: int, maximum: int, value: int, parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setRange(minimum, maximum)
        self.setValue(value)
        self.setFixedHeight(20)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)


# ------------------------------------------------------------------ 复合控件


class Divider(QFrame):
    """分区细线，跟随主题变色。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(1)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

    def apply_palette(self, pal: Palette):
        self.setStyleSheet(f"background:{rgba(pal.fg, 0.14)};")


class SectionLabel(QLabel):
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setFont(ui_font(10, QFont.Weight.DemiBold))


class SliderRow(QWidget):
    valueChanged = pyqtSignal(int)

    def __init__(self, title: str, minimum: int, maximum: int, value: int,
                 suffix: str = "", fmt=None, parent=None):
        super().__init__(parent)
        self._suffix = suffix
        self._fmt = fmt
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(6)
        self.title = QLabel(title)
        self.title.setFont(ui_font(11))
        self.value_label = QLabel()
        self.value_label.setFont(ui_font(11, QFont.Weight.DemiBold))
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        head.addWidget(self.title)
        head.addStretch(1)
        head.addWidget(self.value_label)

        self.slider = Slider(minimum, maximum, value)
        lay.addLayout(head)
        lay.addWidget(self.slider)
        self.slider.valueChanged.connect(self._on_change)
        self._update_label(value)

    def _text(self, v: int) -> str:
        if self._fmt:
            return self._fmt(v)
        return f"{v}{self._suffix}"

    def _update_label(self, v: int):
        self.value_label.setText(self._text(v))

    def _on_change(self, v: int):
        self._update_label(v)
        self.valueChanged.emit(v)

    def set_value(self, v: int):
        self.slider.blockSignals(True)
        self.slider.setValue(int(v))
        self.slider.blockSignals(False)
        self._update_label(int(v))

    def value(self) -> int:
        return self.slider.value()

    def apply_palette(self, pal: Palette):
        self.title.setStyleSheet(f"color:{rgba(pal.muted,1)};")
        self.value_label.setStyleSheet(f"color:{rgba(pal.fg,0.9)};")
        groove = rgba(pal.fg, 0.14)
        self.slider.setStyleSheet(
            f"""
            QSlider::groove:horizontal {{ height: 3px; background: {groove}; border-radius: 2px; }}
            QSlider::sub-page:horizontal {{ background: {rgba(pal.accent,0.85)}; border-radius: 2px; }}
            QSlider::handle:horizontal {{
                background: {rgba(pal.bg if pal.light else pal.raised, 1)};
                border: 1.5px solid {rgba(pal.accent,0.9)};
                width: 10px; height: 10px; margin: -5px 0; border-radius: 6px;
            }}
            QSlider::handle:horizontal:hover {{ background: {rgba(pal.accent,1)}; }}
            """
        )


class SwitchRow(QWidget):
    toggledByUser = pyqtSignal(bool)

    def __init__(self, title: str, checked: bool, hint: str = "", parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        box = QVBoxLayout()
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(1)
        self.title = QLabel(title)
        self.title.setFont(ui_font(11))
        box.addWidget(self.title)
        self.hint = QLabel(hint)
        self.hint.setFont(ui_font(9))
        self.hint.setVisible(bool(hint))
        box.addWidget(self.hint)
        lay.addLayout(box, 1)
        self.switch = Switch(checked)
        lay.addWidget(self.switch, 0, Qt.AlignmentFlag.AlignVCenter)
        self.switch.toggledByUser.connect(self.toggledByUser)

    def isChecked(self) -> bool:  # noqa: N802
        return self.switch.isChecked()

    def setChecked(self, v: bool) -> None:  # noqa: N802
        self.switch.blockSignals(True)
        self.switch.setChecked(v)
        self.switch._pos = 1.0 if v else 0.0
        self.switch.blockSignals(False)
        self.switch.update()

    def apply_palette(self, pal: Palette):
        self.title.setStyleSheet(f"color:{rgba(pal.fg,0.92)};")
        self.hint.setStyleSheet(f"color:{rgba(pal.muted,0.9)};")
        self.switch.set_palette_colors(pal)


class ColorChips(QWidget):
    """一排预设文字颜色 + 自定义入口。"""

    picked = pyqtSignal(str)

    PRESETS = [
        "#1F1F1F", "#33291C", "#5B5148", "#7A7A7A",
        "#B9BCC2", "#F2EFE8", "#A33A2E", "#1F6FB2",
        "#2E7D5B", "#8A5A2B",
    ]

    def __init__(self, current: str, parent=None):
        super().__init__(parent)
        self.current = current.lower()
        from PyQt6.QtWidgets import QGridLayout

        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(7)
        grid.setVerticalSpacing(7)
        self._chips: list[QWidget] = []
        for i, color in enumerate(self.PRESETS):
            chip = _ColorDot(color, color.lower() == self.current)
            chip.clicked.connect(lambda c=color: self._pick(c))
            grid.addWidget(chip, i // 6, i % 6)
            self._chips.append(chip)
        self.custom = _ColorDot(self.current, False, label="+")
        self.custom.clicked.connect(self._pick_custom)
        grid.addWidget(self.custom, len(self.PRESETS) // 6, len(self.PRESETS) % 6)
        grid.setColumnStretch(6, 1)

    def _pick(self, color: str):
        self.current = color.lower()
        for chip in self._chips:
            chip.selected = chip.color.lower() == self.current
            chip.update()
        self.custom.selected = False
        self.custom.update()
        self.picked.emit(color)

    def _pick_custom(self):
        from PyQt6.QtWidgets import QColorDialog

        picked = QColorDialog.getColor(qcolor(self.current), self, "选择文字颜色")
        if picked.isValid():
            self.current = picked.name()
            self.picked.emit(self.current)
            for chip in self._chips:
                chip.selected = False
                chip.update()
            self.custom.color = self.current
            self.custom.selected = True
            self.custom.update()

    def set_color(self, color: str):
        self.current = color.lower()
        for chip in self._chips:
            chip.selected = chip.color.lower() == self.current
            chip.update()
        self.custom.selected = not any(c.selected for c in self._chips)
        self.custom.update()

    def apply_palette(self, pal: Palette):
        for chip in self._chips + [self.custom]:
            chip.ring = pal.fg
            chip.update()


class _ColorDot(QWidget):
    clicked = pyqtSignal()

    def __init__(self, color: str, selected: bool, label: str = ""):
        super().__init__()
        self.color = color
        self.selected = selected
        self.label = label
        self.ring = QColor("#888888")
        self.setFixedSize(22, 22)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(color)

    def mousePressEvent(self, _e):
        self.clicked.emit()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(3.5, 3.5, -3.5, -3.5)
        if self.selected:
            p.setPen(QPen(self.ring, 1.3))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(r.adjusted(-2.6, -2.6, 2.6, 2.6))
        c = qcolor(self.color)
        p.setPen(QPen(mix(c, QColor("#888888"), 0.45), 1))
        p.setBrush(c)
        p.drawEllipse(r)
        if self.label:
            p.setPen(QPen(mix(c, QColor("#000000" if c.lightness() > 128 else "#FFFFFF"), 0.55), 1.4))
            p.setFont(ui_font(9, QFont.Weight.DemiBold))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.label)
        p.end()


class ThemeChips(QWidget):
    picked = pyqtSignal(int)

    def __init__(self, index: int, parent=None):
        super().__init__(parent)
        self.index = index
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        self._chips: list[QWidget] = []
        for i, (bg, fg, name) in enumerate(THEMES):
            chip = _Chip(bg, fg, name, i == index)
            chip.clicked.connect(lambda i=i: self._pick(i))
            lay.addWidget(chip)
            self._chips.append(chip)
        lay.addStretch(1)

    def _pick(self, i: int):
        self.index = i
        for j, c in enumerate(self._chips):
            c.selected = j == i
            c.update()
        self.picked.emit(i)

    def apply_palette(self, pal: Palette):
        for c in self._chips:
            c.ring = pal.fg
            c.update()


class _Chip(QWidget):
    clicked = pyqtSignal()

    def __init__(self, bg: str, fg: str, name: str, selected: bool):
        super().__init__()
        self.bg = QColor(bg)
        self.fg = QColor(fg)
        self.name = name
        self.selected = selected
        self.ring = QColor("#888888")
        self.setFixedSize(30, 30)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(name)

    def mousePressEvent(self, e):
        self.clicked.emit()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(4, 4, -4, -4)
        if self.selected:
            p.setPen(QPen(self.ring, 1.4))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(r.adjusted(-3, -3, 3, 3))
        p.setPen(QPen(mix(self.bg, self.fg, 0.34), 1.1))
        p.setBrush(self.bg)
        p.drawEllipse(r)
        p.end()


# ------------------------------------------------------------------ 标题栏


class TitleBar(QWidget):
    tocClicked = pyqtSignal()
    openClicked = pyqtSignal()
    titleClicked = pyqtSignal()
    settingsClicked = pyqtSignal()
    ghostClicked = pyqtSignal()
    pinClicked = pyqtSignal()
    minimizeClicked = pyqtSignal()
    closeClicked = pyqtSignal()
    doubleClicked = pyqtSignal()

    HEIGHT = 40

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(self.HEIGHT)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self._drag_offset: QPoint | None = None

        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 0, 8, 0)
        lay.setSpacing(2)

        self.btn_open = IconButton("folder", "打开电子书 (⌘O)")
        self.btn_open.clicked.connect(self.openClicked)
        self.btn_toc = IconButton("menu", "目录 (⌘⇧L)")
        self.btn_toc.clicked.connect(self.tocClicked)
        self.title = QLabel("")
        self.title.setFont(ui_font(11, QFont.Weight.Medium))
        self.title.setMinimumWidth(40)
        self.title.setCursor(Qt.CursorShape.PointingHandCursor)
        self.title.setToolTip("点击切换最近打开的书")
        self.title.installEventFilter(self)
        self.title.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.btn_pin = IconButton("pin", "置顶 (⌘⇧T)", 28)
        self.btn_pin.setCheckable(True)
        self.btn_pin.clicked.connect(lambda: self.pinClicked.emit())
        self.btn_ghost = IconButton("ghost", "幽灵模式 (⌘⇧G)", 28)
        self.btn_ghost.setCheckable(True)
        self.btn_ghost.clicked.connect(lambda: self.ghostClicked.emit())
        self.btn_set = IconButton("sliders", "外观设置 (⌘⇧K)", 28)
        self.btn_set.clicked.connect(self.settingsClicked)
        self.btn_min = IconButton("min", "最小化", 28)
        self.btn_min.clicked.connect(self.minimizeClicked)
        self.btn_close = IconButton("close", "退出 (⌘Q)", 28)
        self.btn_close.clicked.connect(self.closeClicked)

        lay.addWidget(self.btn_toc)
        lay.addWidget(self.btn_open)
        lay.addSpacing(4)
        lay.addWidget(self.title, 1)
        lay.addWidget(self.btn_pin)
        lay.addWidget(self.btn_ghost)
        lay.addWidget(self.btn_set)
        lay.addSpacing(4)
        lay.addWidget(self.btn_min)
        lay.addWidget(self.btn_close)

    def set_palette_colors(self, pal: Palette):
        for b in (self.btn_toc, self.btn_open, self.btn_pin, self.btn_ghost, self.btn_set,
                  self.btn_min, self.btn_close):
            b.set_palette_colors(pal)
        self.title.setStyleSheet(f"color:{rgba(pal.muted,0.95)};")

    def eventFilter(self, obj, event):
        if obj is self.title and event.type() == QEvent.Type.MouseButtonPress:
            self.titleClicked.emit()
            return True
        return super().eventFilter(obj, event)

    def set_ghost_mode(self, on: bool):
        """幽灵模式下只留幽灵按钮，其余控件隐藏；整条淡化，鼠标移上去恢复。"""
        for item in (self.title, self.btn_open, self.btn_pin, self.btn_set,
                     self.btn_min, self.btn_close):
            item.setVisible(not on)
        # 目录和退出按钮必须保留，否则幽灵模式下没法选章节、也没法退出
        self.btn_toc.setVisible(True)
        self.btn_ghost.setVisible(True)
        self.setFixedHeight(26 if on else self.HEIGHT)
        if on:
            self._ghost_fade = True
            self._apply_fade()
        else:
            self._ghost_fade = False
            self.setGraphicsEffect(None)

    def _apply_fade(self):
        if not getattr(self, "_ghost_fade", False):
            return
        from PyQt6.QtWidgets import QGraphicsOpacityEffect

        eff = self.graphicsEffect()
        if not isinstance(eff, QGraphicsOpacityEffect):
            eff = QGraphicsOpacityEffect(self)
            self.setGraphicsEffect(eff)
        eff.setOpacity(0.95 if self.underMouse() else 0.38)

    def enterEvent(self, e):
        self._apply_fade()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._apply_fade()
        super().leaveEvent(e)

    def set_title(self, text: str, subtitle: str = ""):
        elided = QFontMetrics(self.title.font()).elidedText(text, Qt.TextElideMode.ElideMiddle, 460)
        self.title.setText(elided if not subtitle else f"{elided}  ·  {subtitle}")
        self.setToolTip(text)

    # 拖动窗口
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            handle = self.window().windowHandle()
            if handle is not None:
                handle.startSystemMove()
                e.accept()
                return
        super().mousePressEvent(e)

    def mouseDoubleClickEvent(self, e):
        self.doubleClicked.emit()


# ------------------------------------------------------------------ 目录面板


class TocPanel(QWidget):
    chapterPicked = pyqtSignal(int)

    WIDTH = 292

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._pal: Palette | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 12, 12)
        lay.setSpacing(10)

        head = QHBoxLayout()
        head.setSpacing(6)
        label = SectionLabel("目 录")
        self.count = QLabel("")
        self.count.setFont(ui_font(9))
        head.addWidget(label)
        head.addStretch(1)
        head.addWidget(self.count)
        lay.addLayout(head)

        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索章节")
        self.search.setFont(ui_font(11))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        lay.addWidget(self.search)

        self.list = QListWidget()
        self.list.setFont(ui_font(11))
        self.list.setFrameShape(QFrame.Shape.NoFrame)
        self.list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.list.setWordWrap(False)
        self.list.setUniformItemSizes(True)
        self.list.itemClicked.connect(self._on_pick)
        self.list.itemActivated.connect(self._on_pick)
        lay.addWidget(self.list, 1)

        self._label = label
        self._chapters: list[tuple[str, int]] = []
        self._ghost = False

    def eventFilter(self, obj, event):
        if obj is self.title and event.type() == QEvent.Type.MouseButtonPress:
            self.titleClicked.emit()
            return True
        return super().eventFilter(obj, event)

    def set_ghost_mode(self, on: bool):
        """幽灵模式下目录面板也透明，只留文字和细边框。"""
        if self._ghost == on:
            return
        self._ghost = on
        if self._pal:
            self.apply_palette(self._pal)

    def set_book(self, book: Book, current: int):
        self.list.clear()
        self._chapters = [(e.title, e.spine_index) for e in book.toc]
        for entry in book.toc:
            # 用全角空格表达层级，卷标与篇章一眼可分
            indent = "\u3000" * min(entry.level, 3)
            item = QListWidgetItem(f"{indent}{entry.title}")
            item.setData(Qt.ItemDataRole.UserRole, entry.spine_index)
            item.setData(Qt.ItemDataRole.UserRole + 1, entry.level)
            item.setToolTip(entry.title)
            self.list.addItem(item)
        self.count.setText(f"{len(book.toc)} 条")
        self.set_current(current)

    def set_current(self, index: int):
        for i in range(self.list.count()):
            item = self.list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == index:
                self.list.setCurrentItem(item)
                self.list.scrollToItem(item, QListWidget.ScrollHint.PositionAtCenter)
                break

    def _filter(self, text: str):
        text = text.strip()
        for i in range(self.list.count()):
            item = self.list.item(i)
            item.setHidden(bool(text) and text.lower() not in item.text().lower())

    def _on_pick(self, item: QListWidgetItem):
        self.chapterPicked.emit(int(item.data(Qt.ItemDataRole.UserRole)))

    def paintEvent(self, _e):
        """自绘面板底：QSS 的类选择器背景在这套无边框透明窗口里不可靠。"""
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pal = self._pal or Palette(Settings())
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if self._ghost:
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(qca(pal.fg, 0.16), 1))
        else:
            p.setBrush(pal.panel)
            p.setPen(QPen(qca(pal.fg, 0.10), 1))
        p.drawRoundedRect(r, 12, 12)
        p.end()

    def apply_palette(self, pal: Palette):
        self._pal = pal
        self.setStyleSheet("")
        self._label.setStyleSheet(f"color:{rgba(pal.muted,1)}; letter-spacing:1px;")
        self.count.setStyleSheet(f"color:{rgba(pal.faint,1)};")
        self.search.setStyleSheet(
            f"""
            QLineEdit {{ background:{rgba(pal.fg,0.045)}; border:none; border-radius:7px;
                         padding:6px 9px; color:{rgba(pal.fg,0.92)};
                         selection-background-color:{rgba(pal.accent,0.35)}; }}
            QLineEdit:focus {{ background:{rgba(pal.fg,0.09)}; }}
            QLineEdit::placeholder {{ color:{rgba(pal.muted, 0.85)}; }}
            """
        )
        self.list.setStyleSheet(
            f"""
            QListWidget {{ background: transparent; border: none; outline: none; }}
            QListWidget::item {{ color:{rgba(pal.fg,0.82)}; padding:7px 8px; border-radius:6px; }}
            QListWidget::item:hover {{ background:{rgba(pal.fg,0.07)}; }}
            QListWidget::item:selected {{ background:{rgba(pal.accent,0.18)}; color:{rgba(pal.fg,1)}; }}
            QScrollBar:vertical {{ background: transparent; width: 9px; margin: 2px 0; }}
            QScrollBar::handle:vertical {{ background:{rgba(pal.fg,0.28)}; border-radius:4px; min-height:30px; }}
            QScrollBar::add-line, QScrollBar::sub-line {{ height:0; }}
            QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
            """
        )


# ------------------------------------------------------------------ 设置面板


class SettingsPanel(QWidget):
    WIDTH = 316

    changed = pyqtSignal(str)          # 任意设置变化（参数为变更键）
    themePicked = pyqtSignal(int)
    resetClicked = pyqtSignal()

    def __init__(self, s: Settings, parent=None):
        super().__init__(parent)
        self.s = s
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._pal: Palette | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 12, 10)
        outer.setSpacing(8)
        outer.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        head = QHBoxLayout()
        head.addWidget(SectionLabel("外 观"))
        head.addStretch(1)
        self.hint = QLabel("实时生效")
        self.hint.setFont(ui_font(9))
        head.addWidget(self.hint)
        outer.addLayout(head)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.viewport().setAutoFillBackground(False)
        inner = QWidget()
        inner.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        # QScrollArea.setWidget() 会把内容控件设成 autoFillBackground=True，
        # 用系统默认灰盖住面板底色，必须显式关掉
        inner.setAutoFillBackground(False)
        self.body = QVBoxLayout(inner)
        self.body.setContentsMargins(0, 0, 14, 14)
        self.body.setSpacing(12)
        scroll.setWidget(inner)
        self._scroll = scroll
        self._inner = inner
        scroll.setMinimumHeight(90)
        scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        outer.addWidget(scroll, 1)

        # 主题
        self.body.addWidget(SectionLabel("主题"))
        self.themes = ThemeChips(s.theme_index)
        self.themes.picked.connect(self.themePicked)
        self.body.addWidget(self.themes)

        # 翻页方式
        self.body.addWidget(self._divider())
        self.body.addWidget(SectionLabel("翻页"))
        self.page_mode = QComboBox()
        self.page_mode.setFont(ui_font(11))
        for label, value in (
            ("整页翻页 · 像纸质书", "page"),
            ("连续滚动", "scroll"),
        ):
            self.page_mode.addItem(label, value)
        pi = self.page_mode.findData(s.page_mode)
        self.page_mode.setCurrentIndex(pi if pi >= 0 else 0)
        self.page_mode.currentIndexChanged.connect(lambda _: self._emit("page_mode"))
        self.body.addWidget(self.page_mode)

        # 字体
        self.body.addWidget(self._divider())
        self.body.addWidget(SectionLabel("字体"))
        self.font_box = QComboBox()
        self.font_box.setFont(ui_font(11))
        self.font_box.setMaxVisibleItems(14)
        for fam in self._font_choices():
            self.font_box.addItem(fam)
        idx = self.font_box.findText(s.font_family)
        if idx < 0:
            self.font_box.addItem(s.font_family)
            idx = self.font_box.count() - 1
        self.font_box.setCurrentIndex(idx)
        self.font_box.currentTextChanged.connect(lambda v: self._emit("font_family"))
        self.body.addWidget(self.font_box)

        self.font_size = SliderRow("字号", 11, 40, int(s.font_size), " pt")
        self.font_size.valueChanged.connect(lambda v: self._emit("font_size"))
        self.body.addWidget(self.font_size)

        self.line_height = SliderRow("行距", 120, 240, s.line_height, "%")
        self.line_height.valueChanged.connect(lambda v: self._emit("line_height"))
        self.body.addWidget(self.line_height)

        self.body.addWidget(SectionLabel("字体颜色"))
        self.text_colors = ColorChips(s.text_color)
        self.text_colors.picked.connect(lambda c: self._emit("text_color"))
        self.body.addWidget(self.text_colors)

        self.text_alpha = SliderRow("字体不透明度", 25, 100, int(s.text_alpha * 100), "%")
        self.text_alpha.valueChanged.connect(lambda v: self._emit("text_alpha"))
        self.body.addWidget(self.text_alpha)

        self.indent = SwitchRow("首行缩进", s.indent, "中文排版按两字缩进")
        self.indent.toggledByUser.connect(lambda v: self._emit("indent"))
        self.body.addWidget(self.indent)

        # 隐身
        self.body.addWidget(self._divider())
        self.body.addWidget(SectionLabel("隐身"))
        self.on_top = SwitchRow("窗口置顶", s.always_on_top, "始终浮在其他窗口之上")
        self.on_top.toggledByUser.connect(lambda v: self._emit("always_on_top"))
        self.body.addWidget(self.on_top)

        self.through = SwitchRow("点击穿透", s.click_through, "鼠标事件穿过窗口，需热键关闭")
        self.through.toggledByUser.connect(lambda v: self._emit("click_through"))
        self.body.addWidget(self.through)

        self.guard = SwitchRow("防录屏 / 截图", s.capture_guard, "屏幕共享与截图中隐藏本窗口")
        self.guard.toggledByUser.connect(lambda v: self._emit("capture_guard"))
        self.body.addWidget(self.guard)

        # 透明与窗口
        self.body.addWidget(self._divider())
        self.body.addWidget(SectionLabel("透明与窗口"))
        self.alpha = SliderRow("背景不透明度", 15, 100, int(s.bg_alpha * 100), "%")
        self.alpha.valueChanged.connect(lambda v: self._emit("bg_alpha"))
        self.body.addWidget(self.alpha)

        self.win_op = SliderRow("整窗不透明度", 30, 100, int(s.window_opacity * 100), "%")
        self.win_op.valueChanged.connect(lambda v: self._emit("window_opacity"))
        self.body.addWidget(self.win_op)

        self.backing = SwitchRow("低透明度自动补底", s.column_backing, "透明度越低，纸面自动越实")
        self.backing.toggledByUser.connect(lambda v: self._emit("column_backing"))
        self.body.addWidget(self.backing)

        self.width_slider = SliderRow("正文栏宽", 360, 1200, s.reading_width, " px")
        self.width_slider.valueChanged.connect(lambda v: self._emit("reading_width"))
        self.body.addWidget(self.width_slider)

        self.padding = SliderRow("页边距", 12, 120, s.padding, " px")
        self.padding.valueChanged.connect(lambda v: self._emit("padding"))
        self.body.addWidget(self.padding)

        # 上限取屏幕可用尺寸：超过屏幕没有意义，还会让窗口跑到看不见的地方
        avail = QGuiApplication.primaryScreen().availableGeometry()
        max_w = max(420, avail.width())
        max_h = max(340, avail.height())
        self.win_w = SliderRow("窗口宽度", 380, max_w, min(s.win_w, max_w), " px")
        self.win_w.valueChanged.connect(lambda v: self._emit("win_w"))
        self.body.addWidget(self.win_w)

        self.win_h = SliderRow("窗口高度", 300, max_h, min(s.win_h, max_h), " px")
        self.win_h.valueChanged.connect(lambda v: self._emit("win_h"))
        self.body.addWidget(self.win_h)

        self.body.addStretch(1)

        # 滑块与下拉不响应滚轮，统一交给面板滚动
        self._wheel_filter = WheelForwarder(scroll.viewport())
        for combo in self.findChildren(QComboBox):
            combo.installEventFilter(self._wheel_filter)
        for slider in self.findChildren(QSlider):
            slider.installEventFilter(self._wheel_filter)

        self.reset = _LinkButton("恢复默认外观")
        self.reset.clicked.connect(self.resetClicked)
        outer.addWidget(self.reset, 0, Qt.AlignmentFlag.AlignLeft)

    def _divider(self) -> Divider:
        d = Divider()
        d.setContentsMargins(0, 4, 0, 2)
        return d

    def _font_choices(self) -> list[str]:
        """常用中文字体排在前面，其余系统字体按字母序接在后面。"""
        families = set(QFontDatabase.families())
        preferred = [
            "Songti SC", "STSong", "Source Han Serif SC", "Noto Serif CJK SC", "SimSun",
            "Kaiti SC", "STKaiti", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei",
            "Heiti SC", "Avenir Next", "Georgia", "Times New Roman",
        ]
        out = [f for f in preferred if f in families]
        # 过滤掉纯符号/表情字体，它们没有汉字字形
        skip = ("emoji", "symbol", "wingdings", "webdings", "dingbat", "lastresort")
        rest = sorted(
            f for f in families
            if f not in out and not f.startswith(".") and not any(k in f.lower() for k in skip)
        )
        return out + rest

    def _emit(self, key: str):
        s = self.s
        if key == "font_family":
            s.font_family = self.font_box.currentText()
        elif key == "font_size":
            s.font_size = float(self.font_size.value())
        elif key == "line_height":
            s.line_height = self.line_height.value()
        elif key == "page_mode":
            s.page_mode = self.page_mode.currentData()
        elif key == "text_color":
            s.text_color = self.text_colors.current
        elif key == "text_alpha":
            s.text_alpha = self.text_alpha.value() / 100.0
        elif key == "indent":
            s.indent = self.indent.isChecked()
        elif key == "bg_alpha":
            s.bg_alpha = self.alpha.value() / 100.0
        elif key == "window_opacity":
            s.window_opacity = self.win_op.value() / 100.0
        elif key == "column_backing":
            s.column_backing = self.backing.isChecked()
        elif key == "reading_width":
            s.reading_width = self.width_slider.value()
        elif key == "padding":
            s.padding = self.padding.value()
        elif key == "win_w":
            s.win_w = self.win_w.value()
        elif key == "win_h":
            s.win_h = self.win_h.value()
        elif key == "always_on_top":
            s.always_on_top = self.on_top.isChecked()
        elif key == "click_through":
            s.click_through = self.through.isChecked()
        elif key == "capture_guard":
            s.capture_guard = self.guard.isChecked()
        s.clamp()
        self.changed.emit(key)

    def sync_from_settings(self):
        s = self.s
        self.font_size.set_value(int(s.font_size))
        self.line_height.set_value(s.line_height)
        self.text_alpha.set_value(int(s.text_alpha * 100))
        self.text_colors.set_color(s.text_color)
        pm = self.page_mode.findData(s.page_mode)
        self.page_mode.setCurrentIndex(pm if pm >= 0 else 0)
        self.alpha.set_value(int(s.bg_alpha * 100))
        self.win_op.set_value(int(s.window_opacity * 100))
        self.width_slider.set_value(s.reading_width)
        self.padding.set_value(s.padding)
        self.win_w.set_value(s.win_w)
        self.win_h.set_value(s.win_h)
        self.indent.setChecked(s.indent)
        self.backing.setChecked(s.column_backing)
        self.on_top.setChecked(s.always_on_top)
        self.through.setChecked(s.click_through)
        self.guard.setChecked(s.capture_guard)

    def paintEvent(self, _e):
        """自绘面板底，颜色完全由 Palette 决定。"""
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pal = self._pal or Palette(Settings())
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setBrush(pal.panel)
        p.setPen(QPen(qca(pal.fg, 0.10), 1))
        p.drawRoundedRect(r, 12, 12)
        p.end()

    def apply_palette(self, pal: Palette):
        self._pal = pal
        self.setStyleSheet(
            f"""
            QLabel {{ color: {rgba(pal.muted, 1)}; }}
            QScrollArea {{ background: transparent; border: none; }}
            QComboBox {{
                background: {rgba(pal.fg, 0.045)}; border: none; border-radius: 7px;
                padding: 6px 9px; color: {rgba(pal.fg, 0.92)}; min-height: 20px;
            }}
            QComboBox:hover {{ background: {rgba(pal.fg, 0.07)}; }}
            QComboBox::drop-down {{ border: none; width: 18px; }}
            QComboBox QAbstractItemView {{
                background: {rgba(pal.raised, 0.98)}; color: {rgba(pal.fg, 0.92)};
                border: 1px solid {rgba(pal.fg, 0.12)}; border-radius: 6px;
                selection-background-color: {rgba(pal.accent, 0.28)};
                outline: none; padding: 4px;
            }}
            QScrollBar:vertical {{ background: transparent; width: 9px; margin: 2px 0; }}
            QScrollBar::handle:vertical {{ background:{rgba(pal.fg,0.28)}; border-radius:4px; min-height:30px; }}
            QScrollBar::add-line, QScrollBar::sub-line {{ height:0; }}
            QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
            """
        )
        for child in self.findChildren(SliderRow):
            child.apply_palette(pal)
        for child in self.findChildren(SwitchRow):
            child.apply_palette(pal)
        for child in self.findChildren(Divider):
            child.apply_palette(pal)
        # QScrollArea 的 viewport 和内容控件默认会用自己的系统灰填充，
        # 把面板底色整个盖住。统一刷成面板色，比追求透明可靠得多。
        for target in (self._scroll.viewport(), self._inner):
            target.setAutoFillBackground(True)
            tp = target.palette()
            tp.setColor(QPalette.ColorRole.Window, pal.panel)
            tp.setColor(QPalette.ColorRole.Base, pal.panel)
            target.setPalette(tp)
        self.themes.apply_palette(pal)
        self.text_colors.apply_palette(pal)
        self.hint.setStyleSheet(f"color:{rgba(pal.faint,1)};")
        self.reset.apply_palette(pal)


class _LinkButton(QAbstractButton):
    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self.text = text
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFont(ui_font(10))
        self._pal: Palette | None = None
        self.setFixedHeight(22)
        fm = QFontMetrics(self.font())
        self.setFixedWidth(fm.horizontalAdvance(text) + 4)

    def apply_palette(self, pal: Palette):
        self._pal = pal
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pal = self._pal or Palette(Settings())
        color = pal.accent if self.underMouse() else pal.muted
        p.setPen(QPen(color))
        p.setFont(self.font())
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.text)
        p.end()


# ------------------------------------------------------------------ 提示气泡


class Toast(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFont(ui_font(11))
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setVisible(False)
        self._effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._effect)
        self._anim = QPropertyAnimation(self._effect, b"opacity", self)
        self._anim.setDuration(220)
        self._timer = None
        self._pal: Palette | None = None

    def apply_palette(self, pal: Palette):
        self._pal = pal
        self.setStyleSheet(
            f"background:{rgba(pal.raised, 0.96)}; color:{rgba(pal.fg,0.95)};"
            f"border:1px solid {rgba(pal.fg,0.12)}; border-radius:9px; padding:7px 14px;"
        )

    def show_message(self, text: str, msec: int = 1800):
        from PyQt6.QtCore import QTimer

        self.setText(text)
        self.adjustSize()
        self._reposition()
        self.setVisible(True)
        self.raise_()
        self._anim.stop()
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.start()
        if self._timer:
            self._timer.stop()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._fade_out)
        self._timer.start(msec)

    def _fade_out(self):
        self._anim.stop()
        self._anim.setStartValue(1.0)
        self._anim.setEndValue(0.0)
        self._anim.finished.connect(self._hide_once)
        self._anim.start()

    def _hide_once(self):
        try:
            self._anim.finished.disconnect(self._hide_once)
        except TypeError:
            pass
        self.setVisible(False)

    def _reposition(self):
        parent = self.parentWidget()
        if not parent:
            return
        x = (parent.width() - self.width()) // 2
        y = parent.height() - self.height() - 62
        self.move(max(8, x), max(8, y))


# ------------------------------------------------------------------ 托盘图标


def make_app_icon(pal: Palette | None = None) -> QIcon:
    pal = pal or Palette(Settings())
    icon = QIcon()
    for size in (16, 22, 32, 64, 128):
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(0.5, 0.5, size - 1, size - 1)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(mix(pal.bg, pal.fg, 0.12))
        p.drawRoundedRect(r, size * 0.24, size * 0.24)
        p.setPen(QPen(mix(pal.bg, pal.fg, 0.55), max(1.0, size * 0.06)))
        p.setBrush(Qt.BrushStyle.NoBrush)
        pad = size * 0.28
        p.drawLine(QPointF(size / 2, pad), QPointF(size / 2, size - pad))
        for dy in (-size * 0.14, size * 0.14):
            p.drawLine(QPointF(pad, size / 2 + dy), QPointF(size - pad, size / 2 + dy))
        p.end()
        icon.addPixmap(pm)
    return icon
