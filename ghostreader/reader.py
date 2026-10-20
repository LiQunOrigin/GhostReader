"""阅读视图：把净化后的章节 HTML 排成可滚动的正文。

排版完全交给 Qt 富文本的 CSS（已验证支持 text-indent / line-height / margin /
font-size 等），因此改字号只需要换一份样式表并重排当前章节，不再逐块遍历文档。
"""

from __future__ import annotations

import re

from PyQt6.QtCore import (
    QEasingCurve,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRectF,
    Qt,
    QTimer,
    QUrl,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor,
    QPainter,
    QPalette,
    QLinearGradient,
    QFont,
    QImage,
    QPalette,
    QTextCursor,
    QTextDocument,
    QTextImageFormat,
)
from PyQt6.QtWidgets import QTextBrowser

from .epub import Book, Chapter
from .settings import Settings


class ReaderView(QTextBrowser):
    chapterLink = pyqtSignal(int)      # 点击了书内链接
    reachedEnd = pyqtSignal()          # 滚到本章末尾
    reachedStart = pyqtSignal()        # 在章首继续向上翻
    scrollFraction = pyqtSignal(float)

    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.s = settings
        self.book: Book | None = None
        self.chapter_index = 0
        self.placeholder = False
        self.ghost_mode = False
        self._html = ""
        self._anim: QPropertyAnimation | None = None
        self._pending_fraction: float | None = None
        self._wheel_accum = 0
        self._press_pos: QPoint | None = None
        self._restore_timer = QTimer(self)
        self._restore_timer.setSingleShot(True)
        self._restore_timer.setInterval(140)
        self._restore_timer.timeout.connect(self._restore_position)

        self.setObjectName("ReaderView")
        self.setFrameShape(QTextBrowser.Shape.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setOpenExternalLinks(False)
        self.setOpenLinks(False)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.viewport().setAutoFillBackground(False)
        self.setStyleSheet("QTextBrowser#ReaderView{background:transparent;border:none;}")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setViewportMargins(0, 6, 0, 6)
        self.anchorClicked.connect(self._on_anchor)
        self.verticalScrollBar().valueChanged.connect(self._on_scroll)

    # ------------------------------------------------------------ 书籍
    def set_book(self, book: Book) -> None:
        self.book = book
        self.chapter_index = 0

    @property
    def chapter(self) -> Chapter | None:
        if not self.book or not self.book.chapters:
            return None
        idx = max(0, min(self.chapter_index, len(self.book.chapters) - 1))
        return self.book.chapters[idx]

    def goto_chapter(self, index: int, fraction: float = 0.0, keep_focus: bool = True) -> None:
        if not self.book:
            return
        index = max(0, min(index, len(self.book.chapters) - 1))
        self.chapter_index = index
        self.placeholder = False
        ch = self.book.chapters[index]
        self._html = ch.html
        self._render()
        # setHtml 之后滚动条范围要等一次布局才更新，直接设置会被钳成 0
        self._pending_fraction = fraction
        QTimer.singleShot(0, self._restore_position)
        if keep_focus:
            self.setFocus(Qt.FocusReason.OtherFocusReason)

    # ------------------------------------------------------------ 排版
    def _css(self) -> str:
        s = self.s
        fam = s.font_family.replace('"', "")
        size = float(s.font_size)
        # pt → px 按 96dpi；行距用绝对像素，避免 Qt 把百分比当成“字体行高的倍数”
        body_px = size * 4.0 / 3.0
        lh_px = body_px * (s.line_height / 100.0)
        indent = body_px * 2 if s.indent else 0.0
        # 幽灵模式与普通模式共用同一套字体与颜色，不再单独配色
        tc = QColor(s.text_color)
        text = f"rgba({tc.red()},{tc.green()},{tc.blue()},{float(s.text_alpha):.2f})"
        para_gap = body_px * 0.35
        h1, h2, h3 = body_px * 1.55, body_px * 1.28, body_px * 1.12
        return f"""
        p, div, li, blockquote, td, th, span, em, i, strong, b, sub, sup, a, pre {{
            font-family: "{fam}"; font-size: {size:.1f}pt; color: {text};
            line-height: {lh_px:.1f}px;
        }}
        p {{ text-indent: {indent:.1f}px; margin: 0 0 {para_gap:.1f}px 0; }}
        div {{ text-indent: 0; margin: 0 0 {body_px * 0.18:.1f}px 0; }}
        li {{ text-indent: 0; margin: 0 0 {body_px * 0.15:.1f}px 0; }}
        blockquote {{
            text-indent: 0; margin: {body_px * 0.35:.1f}px 0 {body_px * 0.35:.1f}px {body_px * 1.1:.1f}px;
        }}
        h1 {{ font-family: "{fam}"; color: {text}; font-size: {h1 * 3 / 4:.1f}pt; font-weight: bold;
              line-height: {h1 * 1.38:.1f}px; margin: {body_px * 1.5:.1f}px 0 {body_px * 0.75:.1f}px 0;
              text-indent: 0; }}
        h2 {{ font-family: "{fam}"; color: {text}; font-size: {h2 * 3 / 4:.1f}pt; font-weight: bold;
              line-height: {h2 * 1.40:.1f}px; margin: {body_px * 1.2:.1f}px 0 {body_px * 0.6:.1f}px 0;
              text-indent: 0; }}
        h3 {{ font-family: "{fam}"; color: {text}; font-size: {h3 * 3 / 4:.1f}pt; font-weight: bold;
              line-height: {h3 * 1.45:.1f}px; margin: {body_px * 0.9:.1f}px 0 {body_px * 0.45:.1f}px 0;
              text-indent: 0; }}
        h4, h5, h6 {{ font-family: "{fam}"; color: {text}; font-size: {size:.1f}pt; font-weight: bold;
              line-height: {lh_px:.1f}px; margin: {body_px * 0.7:.1f}px 0 {body_px * 0.3:.1f}px 0;
              text-indent: 0; }}
        a {{ color: {text}; text-decoration: none; }}
        """

    def _render(self) -> None:
        doc = self.document()
        # 透明背景上用灰度抗锯齿：亚像素（LCD）抗锯齿会在字形边缘留下彩色描边，
        # 在幽灵模式下看着像加了粗边。
        base = QFont(self.s.font_family)
        base.setPointSizeF(float(self.s.font_size))
        if self.ghost_mode:
            # 幽灵模式：完全关闭抗锯齿，字形更细更锐，不会糊成一团
            base.setStyleStrategy(QFont.StyleStrategy.NoAntialias)
        else:
            base.setStyleStrategy(QFont.StyleStrategy.NoSubpixelAntialias)
        doc.setDefaultFont(base)
        doc.setDefaultStyleSheet(self._css())
        self.setHtml(f"<html><body>{self._html}</body></html>")
        # setHtml 会把 textWidth 重置成内容自然宽度，必须在这之后再绑定视口宽度，
        # 否则文字比可视区宽，右边一列会被裁掉。
        self._update_doc_margin()
        self._fit_images()
        self._restyle_scrollbar()
        self._restyle_selection()
        # 翻页模式不需要滚动条，留着反而会占宽度、挡住右边一列字
        if self.s.page_mode == "page":
            self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        else:
            self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

    def _apply_viewport_backing(self) -> None:
        """刷新幽灵模式的文字底衬。

        文字直接画在透明表面上时，抗锯齿只能拿白色当过渡色，在深色桌面上
        会形成一圈白边（看起来像描边）。垫一层底色能解决，但矩形底色本身
        会露出生硬的边（像多了一个框），所以这里改成径向渐变、四周淡出。
        """
        self.viewport().setAutoFillBackground(False)
        self.viewport().update()

    def paintEvent(self, event):
        # 先在视口上铺一层中心实、四周淡的纸色，再交给 QTextBrowser 画正文。
        # 底衬必须画在视口这一层：画在窗口层会被子控件盖住，抗锯齿照样按白色算。
        if self.ghost_mode and float(self.s.ghost_backing) > 0 and not self.placeholder:
            vp = self.viewport()
            w, h = vp.width(), vp.height()
            if w > 40 and h > 40:
                p = QPainter(vp)
                p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                c = QColor(self.s.bg_color)
                a = int(255 * float(self.s.ghost_backing))
                # 1) 铺满整块
                p.fillRect(vp.rect(), QColor(c.red(), c.green(), c.blue(), a))
                # 2) 四条边用 DestinationOut 擦成渐隐，避免出现生硬的矩形边
                feather = min(120.0, min(w, h) * 0.16)
                p.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationOut)
                clear = QColor(0, 0, 0, 255)
                keep = QColor(0, 0, 0, 0)

                def fade(x1, y1, x2, y2, rect):
                    g = QLinearGradient(x1, y1, x2, y2)
                    g.setColorAt(0.0, clear)
                    g.setColorAt(1.0, keep)
                    p.fillRect(rect, g)

                fade(0, 0, 0, feather, QRectF(0, 0, w, feather))
                fade(0, h, 0, h - feather, QRectF(0, h - feather, w, feather))
                fade(0, 0, feather, 0, QRectF(0, 0, feather, h))
                fade(w, 0, w - feather, 0, QRectF(w - feather, 0, feather, h))
                p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
                p.end()
        super().paintEvent(event)

    def set_ghost_mode(self, on: bool) -> None:
        """幽灵模式背景全透明，文字改用独立配色，保证在任何桌面上都看得清。"""
        if self.ghost_mode == on:
            return
        self.ghost_mode = on
        self._apply_viewport_backing()
        self.refresh_layout()

    def refresh_layout(self) -> None:
        """字体/字号/行距/配色变化后重排当前章节，并尽量停在原位置。

        setHtml 之后滚动条范围要等一次布局才更新，因此恢复位置必须放到
        事件循环的下一轮，否则会被钳制到 0。
        """
        if self.placeholder or not self._html:
            return
        frac = self.fraction()
        self._render()
        self._pending_fraction = frac
        QTimer.singleShot(0, self._restore_position)

    def apply_settings(self, refit: bool = True) -> None:
        self.refresh_layout()

    def on_resize(self) -> None:
        """窗口尺寸变化：只调整边距与图片，稍后再校正滚动位置。"""
        if self.placeholder or not self._html:
            self._update_doc_margin()
            return
        # 连续拖动窗口时保留最初的位置，避免被中间态的钳制值覆盖
        if self._pending_fraction is None:
            self._pending_fraction = self.fraction()
        self._update_doc_margin()
        self._fit_images()
        self._restore_timer.start()
        # QTextEdit 自己的 relayout 会把 textWidth 改成比视口宽的值（实测 712 → 878.9），
        # 导致右侧一列字被裁掉，所以下一帧再强制校正一次。
        QTimer.singleShot(0, self._enforce_width)

    def _enforce_width(self) -> None:
        if self.placeholder or not self._html:
            return
        vw = float(self.viewport().width())
        if abs(self.document().textWidth() - vw) > 1.0:
            self._update_doc_margin()
            self._fit_images()

    def _restore_position(self) -> None:
        if self._pending_fraction is None:
            return
        # 先让布局算完（滚动条范围才有值），否则位置会被钳到章首。
        # 注意不能用 adjustSize()：它会把 textWidth 改成内容自然宽度，
        # 导致文字比视口宽、右侧被裁。
        self.document().size()
        self._set_fraction(self._pending_fraction)
        self._pending_fraction = None

    def _update_doc_margin(self) -> None:
        """正文栏宽 + 自动居中：窗口变宽时留白增加，而不是把一行拉得太长。"""
        vw = max(200, self.viewport().width())
        # 关键：文档宽度必须显式跟随视口，否则 setHtml 之后 textWidth 会按内容
        # 自然宽度计算，文字比可视区宽，右边就被裁掉了。
        self.document().setTextWidth(float(vw))
        pad = self.s.padding
        col = min(float(self.s.reading_width), max(180.0, vw - 2 * pad))
        self.document().setDocumentMargin(max(float(pad), (vw - col) / 2.0))

    def _set_fraction(self, fraction: float) -> None:
        bar = self.verticalScrollBar()
        bar.setValue(int(bar.maximum() * max(0.0, min(1.0, fraction))))

    def _fit_images(self) -> None:
        """按正文宽度等比缩放插图。始终以原图尺寸为基准，避免多次缩放叠加。"""
        doc = self.document()
        max_w = max(120, self.viewport().width() - int(self.s.padding * 1.6))
        block = doc.begin()
        while block.isValid():
            it = block.begin()
            while not it.atEnd():
                frag = it.fragment()
                if frag.isValid() and frag.charFormat().isImageFormat():
                    fmt = frag.charFormat().toImageFormat()
                    if fmt.isValid():
                        nat_w, nat_h = fmt.width(), fmt.height()
                        res = doc.resource(
                            int(QTextDocument.ResourceType.ImageResource.value), QUrl(fmt.name())
                        )
                        if isinstance(res, QImage) and not res.isNull():
                            nat_w, nat_h = float(res.width()), float(res.height())
                        if nat_w > 0 and nat_h > 0:
                            scale = min(1.0, max_w / nat_w)
                            tw, th = nat_w * scale, nat_h * scale
                            if abs(fmt.width() - tw) > 1.0 or abs(fmt.height() - th) > 1.0:
                                scaled = QTextImageFormat(fmt)
                                scaled.setWidth(tw)
                                scaled.setHeight(th)
                                cursor = QTextCursor(doc)
                                cursor.setPosition(frag.position())
                                cursor.setPosition(
                                    frag.position() + frag.length(),
                                    QTextCursor.MoveMode.KeepAnchor,
                                )
                                cursor.setCharFormat(scaled)
                it += 1
            block = block.next()

    def _restyle_selection(self) -> None:
        pal = self.palette()
        hl = QColor(self.s.text_color)
        hl.setAlpha(48)
        pal.setColor(QPalette.ColorRole.Highlight, hl)
        pal.setColor(QPalette.ColorRole.HighlightedText, QColor(self.s.text_color))
        self.setPalette(pal)

    def _restyle_scrollbar(self) -> None:
        c = QColor(self.s.text_color)
        track = f"rgba({c.red()},{c.green()},{c.blue()},0)"
        handle = f"rgba({c.red()},{c.green()},{c.blue()},60)"
        handle_h = f"rgba({c.red()},{c.green()},{c.blue()},110)"
        self.verticalScrollBar().setStyleSheet(
            f"""
            QScrollBar:vertical {{ background: transparent; width: 10px; margin: 6px 2px; }}
            QScrollBar::handle:vertical {{ background: {handle}; border-radius: 3px; min-height: 40px; }}
            QScrollBar::handle:vertical:hover {{ background: {handle_h}; }}
            QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
            QScrollBar::add-page, QScrollBar::sub-page {{ background: {track}; }}
            """
        )

    # ------------------------------------------------------------ 占位页
    def show_placeholder(self, title: str, hint: str, foot: str = "") -> None:
        """未打开书籍时的引导页：独立内联排版，不受正文字号影响。"""
        self.placeholder = True
        self._html = ""
        s = self.s
        c = QColor(s.text_color)
        muted = f"rgba({c.red()},{c.green()},{c.blue()},0.62)"
        faint = f"rgba({c.red()},{c.green()},{c.blue()},0.40)"
        fam = s.font_family.replace('"', "")
        foot_html = (
            f'<p align="center" style="font-family:&quot;{fam}&quot;; font-size:9pt;'
            f' color:{faint}; margin-top:28px;">{foot}</p>'
            if foot
            else ""
        )
        self.document().setDefaultStyleSheet("")
        self._update_doc_margin()
        self.setHtml(
            "<html><body>"
            '<div align="center" style="margin-top:30%;">'
            f'<p align="center" style="font-family:&quot;{fam}&quot;; font-size:21pt;'
            f' color:{c.name()}; margin:0;">{title}</p>'
            f'<p align="center" style="font-family:&quot;{fam}&quot;; font-size:11pt;'
            f' color:{muted}; margin-top:16px;">{hint}</p>'
            f"{foot_html}"
            "</div></body></html>"
        )

    # ------------------------------------------------------------ 滚动
    def fraction(self) -> float:
        bar = self.verticalScrollBar()
        if bar.maximum() <= 0:
            return 0.0
        return bar.value() / bar.maximum()

    def scroll_by(self, dy: int, animate: bool = True) -> None:
        bar = self.verticalScrollBar()
        target = max(bar.minimum(), min(bar.maximum(), bar.value() + dy))
        if not animate:
            bar.setValue(target)
            return
        if self._anim:
            self._anim.stop()
        self._anim = QPropertyAnimation(bar, b"value", self)
        self._anim.setDuration(170)
        self._anim.setStartValue(bar.value())
        self._anim.setEndValue(target)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.start()

    def page(self, direction: int) -> None:
        """翻一页。整页模式下按「行」对齐，不会把一行切成两半。"""
        bar = self.verticalScrollBar()
        vp = self.viewport()
        if direction > 0 and bar.value() >= bar.maximum() - 2:
            self.reachedEnd.emit()
            return
        if direction < 0 and bar.value() <= 2:
            self.reachedStart.emit()
            return

        if self.s.page_mode != "page":
            self.scroll_by(direction * int(vp.height() * 0.86))
            return

        if direction > 0:
            # 视口底部那一行 → 翻到顶部
            cursor = self.cursorForPosition(QPoint(vp.width() // 2, vp.height() - 4))
        else:
            # 先退一屏，再把顶部那行对齐到视口顶部
            bar.setValue(max(0, bar.value() - vp.height()))
            cursor = self.cursorForPosition(QPoint(vp.width() // 2, 2))
        cursor.movePosition(QTextCursor.MoveOperation.StartOfLine)
        rect = self.cursorRect(cursor)
        target = bar.value() + rect.top()
        bar.setValue(max(0, min(bar.maximum(), target)))

    def jump(self, where: str) -> None:
        bar = self.verticalScrollBar()
        if where == "top":
            self.scroll_by(-bar.value())
        elif where == "bottom":
            self.scroll_by(bar.maximum() - bar.value())

    # ------------------------------------------------------------ 事件
    def _on_scroll(self, _value: int) -> None:
        self.scrollFraction.emit(self.fraction())

    def _on_anchor(self, url) -> None:
        s = url.toString()
        m = re.match(r"gr://chapter/(\d+)", s)
        if m:
            self.chapterLink.emit(int(m.group(1)))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.on_resize()

    def wheelEvent(self, event):
        if self.s.page_mode == "page" and not (
            event.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            self._wheel_accum += event.angleDelta().y()
            if abs(self._wheel_accum) >= 40:
                self.page(1 if self._wheel_accum < 0 else -1)
                self._wheel_accum = 0
            event.accept()
            return
        super().wheelEvent(event)

    def mousePressEvent(self, event):
        self._press_pos = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if self.s.page_mode != "page" or self._press_pos is None:
            return
        moved = (event.position().toPoint() - self._press_pos).manhattanLength()
        self._press_pos = None
        if moved > 10 or self.textCursor().hasSelection():
            return
        # 点左侧 1/3 上一页，右侧 1/3 下一页，中间留给选中文字
        x = event.position().x()
        w = self.viewport().width()
        if x < w * 0.32:
            self.page(-1)
        elif x > w * 0.68:
            self.page(1)

    def keyPressEvent(self, event):
        key = event.key()
        mods = event.modifiers()
        if mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier):
            super().keyPressEvent(event)
            return
        if key in (Qt.Key.Key_Space, Qt.Key.Key_PageDown, Qt.Key.Key_J):
            self.page(1)
            return
        if key in (Qt.Key.Key_PageUp, Qt.Key.Key_K):
            self.page(-1)
            return
        if key in (Qt.Key.Key_Down, Qt.Key.Key_Up):
            self.scroll_by(int(self.s.font_size * 2.4) * (1 if key == Qt.Key.Key_Down else -1))
            return
        if key == Qt.Key.Key_Home:
            self.jump("top")
            return
        if key == Qt.Key.Key_End:
            self.jump("bottom")
            return
        super().keyPressEvent(event)
