"""主窗口：无边框半透明书窗，承载阅读、目录、设置与全部隐身交互。"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from PyQt6.QtCore import (
    QEasingCurve,
    QEvent,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
)
from PyQt6.QtGui import (
    QAction,
    QColor,
    QCursor,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPen,
    QShortcut,
)
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QMenu,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from . import documents, epub
from .epub import Book
from .reader import ReaderView
from .settings import THEMES, Settings
from .stealth import (
    GlobalHotkeys,
    accessibility_trusted,
    set_capture_guard,
    set_click_through,
)
from .widgets import (
    Palette,
    SettingsPanel,
    TitleBar,
    Toast,
    TocPanel,
    make_app_icon,
    mix,
    qca,
    qcolor,
    rgba,
    ui_font,
)

MARGIN = 10      # 窗口边缘留白：既给光边留位置，也作为拖拽缩放的判定区
RADIUS = 14
EDGE = 6


def hotkey_labels() -> dict[str, str]:
    mac = sys.platform == "darwin"
    m = "⌘" if mac else "Ctrl+"
    s = "⇧" if mac else "Shift+"
    return {
        "toggle": f"{m}{s}H",
        "ghost": f"{m}{s}G",
        "through": f"{m}{s}J",
        "top": f"{m}{s}T",
        "toc": f"{m}{s}L",
        "settings": f"{m}{s}K",
        "open": f"{m}O",
        "font_up": f"{m}{s}=",
        "font_down": f"{m}{s}-",
        "alpha_up": f"{m}{s}↑",
        "alpha_down": f"{m}{s}↓",
        "width_up": f"{m}{s}→",
        "width_down": f"{m}{s}←",
        "hide": "Esc",
    }


def qt_sequence(name: str) -> str:
    # macOS 上 Qt 会把 Ctrl 映射为 Command，正好与系统习惯一致
    return {
        "toggle": "Ctrl+Shift+H",
        "ghost": "Ctrl+Shift+G",
        "through": "Ctrl+Shift+J",
        "top": "Ctrl+Shift+T",
        "toc": "Ctrl+Shift+L",
        "settings": "Ctrl+Shift+K",
        "open": "Ctrl+O",
        "font_up": "Ctrl+Shift+=",
        "font_down": "Ctrl+Shift+-",
        "alpha_up": "Ctrl+Shift+Up",
        "alpha_down": "Ctrl+Shift+Down",
        "width_up": "Ctrl+Shift+Right",
        "width_down": "Ctrl+Shift+Left",
        "hide": "Esc",
    }[name]


def pynput_hotkeys() -> dict[str, str]:
    mac = sys.platform == "darwin"
    mod = "<cmd>" if mac else "<ctrl>"
    return {
        "toggle": f"{mod}+<shift>+h",
        "ghost": f"{mod}+<shift>+g",
        "through": f"{mod}+<shift>+j",
        "top": f"{mod}+<shift>+t",
    }


class StatusBar(QWidget):
    """底部状态条：章节名 + 进度，顶端一条 2px 进度线。"""

    HEIGHT = 26

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(self.HEIGHT)
        self.progress = 0.0
        self.left = ""
        self.right = ""
        self._pal = Palette(Settings())

    def set_state(self, left: str, right: str, progress: float):
        self.left = left
        self.right = right
        self.progress = max(0.0, min(1.0, progress))
        self.update()

    def apply_palette(self, pal: Palette):
        self._pal = pal
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pal = self._pal
        w, h = self.width(), self.height()

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(qca(mix(pal.bg, pal.fg, 0.10), 0.9))
        p.drawRoundedRect(QRectF(2, 0, w - 4, 2), 1, 1)
        if self.progress > 0:
            p.setBrush(qca(pal.accent, 0.75))
            p.drawRoundedRect(QRectF(2, 0, max(3.0, (w - 4) * self.progress), 2), 1, 1)

        f = ui_font(9)
        p.setFont(f)
        fm = QFontMetrics(f)
        p.setPen(QPen(qca(pal.muted, 0.95)))
        left = fm.elidedText(self.left, Qt.TextElideMode.ElideRight, int(w * 0.62))
        p.drawText(
            QRectF(4, 2, w * 0.62, h - 4),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            left,
        )
        p.setPen(QPen(qca(pal.faint, 0.95)))
        p.drawText(
            QRectF(w * 0.6, 2, w * 0.4 - 4, h - 4),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            self.right,
        )
        p.end()


class MainWindow(QWidget):
    def __init__(self, settings: Settings | None = None):
        super().__init__(None, Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.s = settings or Settings.load()
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setWindowTitle("GhostReader")
        self.setAcceptDrops(True)
        self.setMinimumSize(QSize(380, 300))
        self.setMouseTracking(True)

        self.book: Book | None = None
        self.pal = Palette(self.s)
        self._ghost = False
        self._mouse_inside = True   # 幽灵模式下由光标位置决定显示/隐没
        self._resizing_edge = Qt.Edge(0)
        self._resize_origin = QPoint()
        self._resize_geo = QRect()
        self._op_anim: QPropertyAnimation | None = None
        self._toc_open = False
        self._settings_open = False
        self._toc_anim: QPropertyAnimation | None = None
        self._set_anim: QPropertyAnimation | None = None

        self._ensure_font_available()
        self._build_ui()
        self._build_shortcuts()
        self._build_tray()
        self._restore_geometry()
        self._apply_all()
        self._start_timers()

        self.hotkeys = GlobalHotkeys(pynput_hotkeys(), self)
        self.hotkeys.fired.connect(self._on_global_hotkey)
        self.hotkeys.status.connect(self._on_hotkey_status)
        if os.environ.get("GHOSTREADER_NO_HOTKEY") != "1":
            self.hotkeys.start()

        if self.s.last_book and Path(self.s.last_book).is_file():
            self.open_book(self.s.last_book, silent=True)

    # ------------------------------------------------------------ 构建
    def _ensure_font_available(self):
        from PyQt6.QtGui import QFontDatabase

        families = set(QFontDatabase.families())
        if self.s.font_family in families:
            return
        for name in (
            "Songti SC", "STSong", "Source Han Serif SC", "Noto Serif CJK SC",
            "SimSun", "PingFang SC", "Microsoft YaHei", "Georgia",
        ):
            if name in families:
                self.s.font_family = name
                return

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(MARGIN + 14, MARGIN + 4, MARGIN + 14, MARGIN + 6)
        root.setSpacing(0)

        self.title_bar = TitleBar(self)
        self.title_bar.tocClicked.connect(self.toggle_toc)
        self.title_bar.openClicked.connect(self.choose_book)
        self.title_bar.titleClicked.connect(self.show_recent_menu)
        self.title_bar.settingsClicked.connect(self.toggle_settings)
        self.title_bar.ghostClicked.connect(self.toggle_ghost)
        self.title_bar.pinClicked.connect(self.toggle_on_top)
        self.title_bar.minimizeClicked.connect(self.showMinimized)
        self.title_bar.closeClicked.connect(self.quit_app)
        self.title_bar.doubleClicked.connect(self.toggle_ghost)
        root.addWidget(self.title_bar)

        self.reader = ReaderView(self.s, self)
        self.reader.chapterLink.connect(self.goto_chapter)
        self.reader.reachedEnd.connect(
            lambda: self.goto_chapter(self.reader.chapter_index + 1, quiet=True)
        )
        self.reader.reachedStart.connect(self._goto_previous_chapter)
        self.reader.scrollFraction.connect(self._on_scroll)
        root.addWidget(self.reader, 1)

        self.status = StatusBar(self)
        root.addWidget(self.status)

        self.toc = TocPanel(self)
        self.toc.chapterPicked.connect(self._on_toc_pick)
        self.toc.hide()

        self.panel = SettingsPanel(self.s, self)
        self.panel.changed.connect(self._on_setting_changed)
        self.panel.themePicked.connect(self._on_theme)
        self.panel.resetClicked.connect(self.reset_appearance)
        self.panel.hide()

        self.toast = Toast(self)
        self._show_empty()

    def _build_shortcuts(self):
        binds = {
            "toggle": self.toggle_visibility,
            "ghost": self.toggle_ghost,
            "through": self.toggle_click_through,
            "top": self.toggle_on_top,
            "toc": self.toggle_toc,
            "settings": self.toggle_settings,
            "open": self.choose_book,
            "font_up": lambda: self._bump_font(1),
            "font_down": lambda: self._bump_font(-1),
            "alpha_up": lambda: self._bump_alpha(0.05),
            "alpha_down": lambda: self._bump_alpha(-0.05),
            "width_up": lambda: self._bump_width(40),
            "width_down": lambda: self._bump_width(-40),
            "hide": self.toggle_visibility,
        }
        self._shortcuts = []
        for name, slot in binds.items():
            sc = QShortcut(QKeySequence(qt_sequence(name)), self)
            sc.setContext(Qt.ShortcutContext.ApplicationShortcut)
            sc.activated.connect(slot)
            self._shortcuts.append(sc)
        quit_sc = QShortcut(QKeySequence("Ctrl+Q"), self)
        quit_sc.setContext(Qt.ShortcutContext.ApplicationShortcut)
        quit_sc.activated.connect(self.quit_app)
        self._shortcuts.append(quit_sc)

    def _build_tray(self):
        self.tray = QSystemTrayIcon(make_app_icon(self.pal), self)
        self.tray.setToolTip("GhostReader · 幽灵阅读器")
        menu = QMenu()
        self.act_toggle = QAction("隐藏窗口", self)
        self.act_toggle.triggered.connect(self.toggle_visibility)
        act_open = QAction("打开 EPUB…", self)
        act_open.triggered.connect(self.choose_book)
        self.act_ghost = QAction("幽灵模式", self)
        self.act_ghost.setCheckable(True)
        self.act_ghost.triggered.connect(lambda: self.toggle_ghost())
        self.act_top = QAction("窗口置顶", self)
        self.act_top.setCheckable(True)
        self.act_top.setChecked(self.s.always_on_top)
        self.act_top.triggered.connect(lambda: self.toggle_on_top())
        self.act_through = QAction("点击穿透", self)
        self.act_through.setCheckable(True)
        self.act_through.setChecked(self.s.click_through)
        self.act_through.triggered.connect(lambda: self.toggle_click_through())
        act_reset = QAction("重置窗口位置", self)
        act_reset.triggered.connect(self.reset_window_position)
        act_settings = QAction("外观设置", self)
        act_settings.triggered.connect(self.toggle_settings)
        act_quit = QAction("退出", self)
        act_quit.triggered.connect(self.quit_app)
        menu.addAction(self.act_toggle)
        menu.addAction(act_open)
        menu.addSeparator()
        menu.addAction(self.act_ghost)
        menu.addAction(self.act_top)
        menu.addAction(self.act_through)
        menu.addAction(act_settings)
        menu.addAction(act_reset)
        menu.addSeparator()
        menu.addAction(act_quit)
        self._tray_menu = menu
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray)
        self.tray.show()

    def _restore_geometry(self):
        """恢复窗口位置，并保证它一定落在某块屏幕的可见区域内。"""
        screens = QGuiApplication.screens() or [QGuiApplication.primaryScreen()]
        primary = QGuiApplication.primaryScreen() or screens[0]
        avail = primary.availableGeometry()

        w = int(min(self.s.win_w, avail.width() - 40))
        h = int(min(self.s.win_h, avail.height() - 100))
        x, y = int(self.s.win_x), int(self.s.win_y)

        # 保存的位置必须有一半落在某块屏幕里，否则视为无效（比如拔掉了外接屏）
        rect = QRect(x, y, w, h)
        visible = x >= 0 and y >= 0 and any(
            sc.availableGeometry().intersects(rect) for sc in screens
        )
        if not visible:
            x = avail.right() - w - 48
            y = avail.top() + max(40, (avail.height() - h) // 2)

        # 再夹到当前所在屏幕内，避免标题栏跑到菜单栏后面
        for sc in screens:
            av = sc.availableGeometry()
            if av.contains(QPoint(x + w // 2, y + h // 2)):
                x = max(av.left(), min(x, av.right() - w))
                y = max(av.top(), min(y, av.bottom() - h))
                break
        self.setGeometry(x, y, w, h)

    def reset_window_position(self):
        """窗口被拖到屏幕外时的一键救援。"""
        avail = QGuiApplication.primaryScreen().availableGeometry()
        w = int(min(self.s.win_w, avail.width() - 40))
        h = int(min(self.s.win_h, avail.height() - 100))
        x = avail.right() - w - 48
        y = avail.top() + max(40, (avail.height() - h) // 2)
        self.setGeometry(x, y, w, h)
        self.show_window()
        self.toast.show_message("窗口已回到屏幕内", 1600)

    def _start_timers(self):
        self._idle_timer = QTimer(self)
        self._idle_timer.setInterval(110)
        self._idle_timer.timeout.connect(self._tick_idle)
        self._idle_timer.start()

        self._status_timer = QTimer(self)
        self._status_timer.setSingleShot(True)
        self._status_timer.setInterval(80)
        self._status_timer.timeout.connect(self._refresh_status_throttled)

        self._save_timer = QTimer(self)
        self._save_timer.setInterval(20000)
        self._save_timer.timeout.connect(self._persist)
        self._save_timer.start()

    # ------------------------------------------------------------ 绘制
    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pal = self.pal
        outer = QRectF(self.rect()).adjusted(MARGIN, MARGIN, -MARGIN, -MARGIN)
        path = QPainterPath()
        path.addRoundedRect(outer, RADIUS, RADIUS)

        if self._ghost:
            # 幽灵模式：不画任何背景，只留子控件（正文）绘制。
            # 注意不能用 CompositionMode_Source 清屏——会把子控件一起抹掉。
            p.end()
            return

        # 1) 外圈：用户设定的背景不透明度
        bg = qcolor(self.s.bg_color)
        bg.setAlphaF(self.s.bg_alpha)
        p.fillPath(path, bg)

        # 2) 内层纸面：透明度越低自动越实，保证文字可读；高透明度时与底色一致，
        #    因此不会出现“色块”接缝，只留一圈很窄的半透明光边。
        if self.s.column_backing:
            boost = max(0.0, 0.80 - self.s.bg_alpha) * 0.9
            if boost > 0.005:
                inner = outer.adjusted(4, 4, -4, -4)
                ipath = QPainterPath()
                ipath.addRoundedRect(inner, RADIUS - 2, RADIUS - 2)
                c = qcolor(self.s.bg_color)
                c.setAlphaF(min(0.95, self.s.bg_alpha + boost))
                p.fillPath(ipath, c)

        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(qca(pal.fg, 0.10 if pal.light else 0.16), 1))
        p.drawRoundedRect(outer.adjusted(0.5, 0.5, -0.5, -0.5), RADIUS, RADIUS)

        # 右下角缩放手柄：三条斜线，提示这里可以拖
        pen = QPen(qca(pal.fg, 0.26 if self.underMouse() else 0.18), 1.2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        bx, by = outer.right() - 6, outer.bottom() - 6
        for i in range(3):
            p.drawLine(QPointF(bx - 4 * i, by), QPointF(bx, by - 4 * i))
        p.end()

    # ------------------------------------------------------------ 主题
    def _apply_all(self, reflow: bool = True):
        self.pal = Palette(self.s)
        self.title_bar.set_palette_colors(self.pal)
        self.status.apply_palette(self.pal)
        self.toc.apply_palette(self.pal)
        self.panel.apply_palette(self.pal)
        self.toast.apply_palette(self.pal)
        if reflow:
            self.reader.apply_settings()
        self.title_bar.btn_pin.setChecked(self.s.always_on_top)
        self.title_bar.btn_ghost.setChecked(self._ghost)
        self.act_top.setChecked(self.s.always_on_top)
        self.act_ghost.setChecked(self._ghost)
        self.act_through.setChecked(self.s.click_through)
        self._apply_window_flags()
        self._apply_opacity(animate=False)
        self._layout_panels()
        self.update()

    def _apply_window_flags(self):
        """只有置顶状态真的变化时才重建窗口。

        每次 setWindowFlag 都会让 macOS 重新走一遍窗口显示流程，位置可能被
        系统“级联”到别处，所以这里必须判重，并在重建后恢复原几何。
        """
        want = bool(self.s.always_on_top)
        current = bool(self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
        if current != want:
            # setWindowFlag 会先把窗口隐藏，所以可见性必须在调用之前记下来
            was_visible = self.isVisible()
            geo = self.geometry()
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, want)
            # 重建窗口后重新确认透明属性，否则可能退回不透明底色
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            if was_visible:
                self.show()
                self.setGeometry(geo)
                self.raise_()
        if self.s.capture_guard:
            QTimer.singleShot(60, lambda: set_capture_guard(self, True))

    def _apply_opacity(self, animate: bool = True):
        if self._ghost:
            # 鼠标在窗口里：整窗 1.0（文字可见，背景本就透明）
            # 鼠标移开：整窗 0.0，完全看不见
            target = 1.0 if self._mouse_inside else 0.0
        else:
            target = self.s.window_opacity
        target = max(0.0, min(1.0, target))
        if not animate:
            self.setWindowOpacity(target)
            return
        if self._op_anim:
            self._op_anim.stop()
        self._op_anim = QPropertyAnimation(self, b"windowOpacity", self)
        self._op_anim.setDuration(80 if self._ghost else 190)
        self._op_anim.setStartValue(self.windowOpacity())
        self._op_anim.setEndValue(target)
        self._op_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._op_anim.start()

    # ------------------------------------------------------------ 面板
    def _layout_panels(self):
        top = MARGIN + 4 + (self.title_bar.height() if self.title_bar.isVisible() else 0)
        bottom = self.height() - MARGIN - 6 - (self.status.height() if self.status.isVisible() else 0)
        h = max(120, bottom - top - 8)
        self.toc.setGeometry(MARGIN + 8, top + 4, TocPanel.WIDTH, h)
        self.panel.setGeometry(
            self.width() - MARGIN - 8 - SettingsPanel.WIDTH, top + 4, SettingsPanel.WIDTH, h
        )
        if self.toast.isVisible():
            self.toast._reposition()

    def _slide(self, widget: QWidget, show: bool, from_left: bool):
        anim_attr = "_toc_anim" if from_left else "_set_anim"
        current = getattr(self, anim_attr)
        if current:
            current.stop()
        # 先把面板摆回窗口内的标准位置，再取几何。
        # 否则第二次打开时「当前位置」还是上次滑出屏幕外的坐标，动画终点也在屏幕外。
        self._layout_panels()
        start = widget.geometry()
        end = QRect(start)
        offset = SettingsPanel.WIDTH + 24
        end.moveLeft(-offset if from_left else self.width() + offset)
        if show:
            widget.setGeometry(end)
            widget.show()
            widget.raise_()
        anim = QPropertyAnimation(widget, b"geometry", self)
        anim.setDuration(200)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.setStartValue(widget.geometry() if show else start)
        anim.setEndValue(start if show else end)
        if not show:
            anim.finished.connect(widget.hide)
        anim.start()
        setattr(self, anim_attr, anim)

    def toggle_toc(self):
        self._toc_open = not self._toc_open
        if self._toc_open:
            self._settings_open = False
            self.panel.hide()
            self.toc.set_current(self.reader.chapter_index)
        self._slide(self.toc, self._toc_open, from_left=True)

    def toggle_settings(self):
        self._settings_open = not self._settings_open
        if self._settings_open:
            self._toc_open = False
            self.toc.hide()
            self.panel.sync_from_settings()
        self._slide(self.panel, self._settings_open, from_left=False)

    def _close_panels(self) -> bool:
        closed = False
        if self._toc_open:
            self.toggle_toc()
            closed = True
        if self._settings_open:
            self.toggle_settings()
            closed = True
        return closed

    # ------------------------------------------------------------ 书籍
    def choose_book(self):
        start = str(Path(self.s.last_book).parent) if self.s.last_book else str(Path.home())
        path, _ = QFileDialog.getOpenFileName(
            self,
            "打开电子书",
            start,
            documents.FILE_FILTER,
        )
        if path:
            self.open_book(path)

    def show_recent_menu(self):
        """点书名弹出最近打开的书，切换书不用再走文件对话框。"""
        menu = QMenu(self)
        recents = [p for p in self.s.recent if Path(p).is_file()]
        if recents:
            for p in recents[:10]:
                act = menu.addAction(Path(p).stem)
                act.setData(p)
                if p == self.s.last_book:
                    act.setCheckable(True)
                    act.setChecked(True)
        else:
            empty = menu.addAction("（暂无最近打开的书）")
            empty.setEnabled(False)
        menu.addSeparator()
        menu.addAction(f"打开文件…  {hotkey_labels()['open']}", self.choose_book)
        chosen = menu.exec(QCursor.pos())
        if chosen is not None and chosen.data():
            self.open_book(chosen.data())

    def open_book(self, path: str, silent: bool = False):
        try:
            book = documents.open_document(path)
        except Exception as exc:
            self.toast.show_message(f"打开失败：{exc}", 3200)
            return
        old = self.book
        self.book = book
        self.reader.set_book(book)
        self.s.last_book = str(Path(path).resolve())
        self.s.push_recent(self.s.last_book)
        self.title_bar.set_title(book.title, book.author)
        self.toc.set_book(book, 0)
        self._apply_all()
        idx, frac = self.s.get_progress()
        self.reader.goto_chapter(idx, frac, keep_focus=True)
        self._update_status()
        if old:
            epub.cleanup(old)
        self._persist()
        if not silent:
            self.toast.show_message(f"已打开《{book.title}》")

    def goto_chapter(self, index: int, quiet: bool = False):
        if not self.book:
            return
        if index >= len(self.book.chapters):
            if not quiet:
                self.toast.show_message("已经是最后一节了", 1200)
            return
        if index < 0:
            index = 0
        self.reader.goto_chapter(index, 0.0)
        self.toc.set_current(index)
        self._update_status()
        self._persist()

    def _goto_previous_chapter(self):
        if not self.book or self.reader.chapter_index <= 0:
            return
        # 回到上一章末尾，符合"往上翻"的直觉。
        # 只调用一次 goto_chapter：连续调用会让先入队的 0 覆盖掉 1.0。
        target = self.reader.chapter_index - 1
        self.reader.goto_chapter(target, 1.0, keep_focus=True)
        self.toc.set_current(target)
        self._update_status()
        self._persist()

    def _on_toc_pick(self, index: int):
        self.goto_chapter(index)
        if self._toc_open:
            self.toggle_toc()

    def _on_scroll(self, _frac: float):
        # 滚动会连续触发，节流后再刷新状态栏，避免每帧重绘。
        # 初始化阶段（定时器还没建）会先收到滚动信号，这里必须容错。
        timer = getattr(self, "_status_timer", None)
        if timer is not None and not timer.isActive():
            timer.start()

    def _refresh_status_throttled(self):
        self._update_status()

    def _update_status(self):
        if not self.book:
            self.status.set_state("未打开书籍", f"{hotkey_labels()['open']} 打开", 0.0)
            return
        ch = self.reader.chapter
        total = len(self.book.chapters)
        idx = self.reader.chapter_index
        frac = self.reader.fraction()
        overall = (idx + frac) / max(1, total)
        name = ch.title if ch else ""
        self.status.set_state(name, f"{idx + 1}/{total} · {int(overall * 100)}%", overall)
        if self._ghost:
            self.setWindowTitle(f"{name} · {int(overall * 100)}%")

    def _show_empty(self):
        labels = hotkey_labels()
        self.reader.show_placeholder(
            "GhostReader",
            f"拖入 EPUB 文件，或按 {labels['open']} 打开",
            f"{labels['toggle']} 隐藏　·　{labels['ghost']} 幽灵模式　·　{labels['settings']} 外观",
        )
        self.status.set_state("未打开书籍", f"{labels['open']} 打开", 0.0)

    # ------------------------------------------------------------ 设置回调
    REFLOW_KEYS = {
        "font_family", "font_size", "line_height", "indent",
        "reading_width", "padding", "text_color",
    }

    def _on_setting_changed(self, key: str):
        """按变更类型分流：只有影响排版的才重排正文，其余只重绘或改窗口属性。"""
        if key in self.REFLOW_KEYS:
            if key == "text_color":
                self._apply_all()
            else:
                self.reader.apply_settings()
                self.update()
        elif key in ("win_w", "win_h"):
            avail = QGuiApplication.primaryScreen().availableGeometry()
            self.resize(self.panel.win_w.value(), self.panel.win_h.value())
            # 变宽后右边缘可能顶出屏幕，把窗口拉回来
            x = max(avail.left(), min(self.x(), avail.right() - self.width()))
            y = max(avail.top(), min(self.y(), avail.bottom() - self.height()))
            if (x, y) != (self.x(), self.y()):
                self.move(x, y)
            self._layout_panels()
        elif key == "page_mode":
            pass
        elif key in ("text_alpha", "ghost_text"):
            # 只重排正文，不用重建整个面板
            self.reader.apply_settings()
        elif key in ("bg_alpha", "column_backing"):
            self.update()          # 背景由窗口自绘，重绘即可
        elif key == "window_opacity":
            self._apply_opacity(animate=False)
        elif key == "always_on_top":
            self.title_bar.btn_pin.setChecked(self.s.always_on_top)
            self.act_top.setChecked(self.s.always_on_top)
            self._apply_window_flags()
        elif key == "click_through":
            set_click_through(self, self.s.click_through)
            self.act_through.setChecked(self.s.click_through)
            if self.s.click_through:
                self.toast.show_message(
                    f"点击穿透已开启，按 {hotkey_labels()['through']} 关闭", 2600
                )
        elif key == "capture_guard":
            ok = set_capture_guard(self, self.s.capture_guard)
            if self.s.capture_guard and not ok:
                self.toast.show_message("当前系统不支持防录屏，已跳过", 2400)
            elif self.s.capture_guard:
                self.toast.show_message("已从屏幕共享与截图中隐藏", 2200)
        self._persist()

    def _on_theme(self, index: int):
        self.s.theme_index = index
        bg, fg, _ = THEMES[index]
        self.s.bg_color = bg
        self.s.text_color = fg
        self._apply_all()
        self.tray.setIcon(make_app_icon(self.pal))
        self._persist()

    def reset_appearance(self):
        defaults = Settings()
        for key in (
            "font_family", "font_size", "line_height", "indent", "text_color",
            "bg_color", "bg_alpha", "window_opacity", "column_backing",
            "reading_width", "padding", "theme_index",
        ):
            setattr(self.s, key, getattr(defaults, key))
        self.panel.sync_from_settings()
        self._apply_all()
        self.toast.show_message("已恢复默认外观")
        self._persist()

    def _bump_font(self, delta: float):
        self.s.font_size = max(11.0, min(40.0, self.s.font_size + delta))
        self.panel.sync_from_settings()
        self.reader.apply_settings()
        self.toast.show_message(f"字号 {self.s.font_size:.0f} pt", 900)

    def _bump_alpha(self, delta: float):
        self.s.bg_alpha = max(0.15, min(1.0, self.s.bg_alpha + delta))
        self.panel.sync_from_settings()
        self.update()
        self.toast.show_message(f"背景不透明度 {int(self.s.bg_alpha * 100)}%", 900)
        self._persist()

    def _bump_width(self, delta: int):
        self.s.reading_width = max(360, min(1200, self.s.reading_width + delta))
        self.panel.sync_from_settings()
        self.reader.apply_settings()
        self.toast.show_message(f"正文宽度 {self.s.reading_width} px", 900)
        self._persist()

    # ------------------------------------------------------------ 隐身
    def toggle_ghost(self):
        self._ghost = not self._ghost
        if self._ghost:
            self.status.hide()
            self._close_panels()
            self._mouse_inside = self.frameGeometry().contains(QCursor.pos())
            self.toast.show_message("幽灵模式：背景全透明，鼠标移开即隐没；⌘⇧G 退出", 2600)
        else:
            self.status.show()
            self._mouse_inside = True
        self.title_bar.set_ghost_mode(self._ghost)
        self.reader.set_ghost_mode(self._ghost)
        self.toc.set_ghost_mode(self._ghost)
        self.title_bar.btn_ghost.setChecked(self._ghost)
        self.act_ghost.setChecked(self._ghost)
        self._apply_all(reflow=False)
        self._layout_panels()

    def toggle_on_top(self):
        self.s.always_on_top = not self.s.always_on_top
        self._apply_all(reflow=False)
        self.toast.show_message("窗口已置顶" if self.s.always_on_top else "已取消置顶", 1000)
        self._persist()

    def toggle_click_through(self):
        if not self.s.click_through and not self._hotkey_really_works():
            # 穿透后窗口收不到鼠标事件，没有全局热键就再也关不掉
            self.toast.show_message("需要先授权「辅助功能」才能开启点击穿透", 3200)
            self.panel.sync_from_settings()
            return
        self.s.click_through = not self.s.click_through
        set_click_through(self, self.s.click_through)
        self.act_through.setChecked(self.s.click_through)
        self.panel.sync_from_settings()
        if self.s.click_through:
            self.toast.show_message(
                f"点击穿透已开启，按 {hotkey_labels()['through']} 关闭", 2600
            )
        self._persist()

    def toggle_visibility(self):
        if self.isVisible():
            self.hide_window()
        else:
            self.show_window()

    def hide_window(self):
        self._persist()
        self.hide()
        self.act_toggle.setText("显示窗口")
        if self.tray.isVisible():
            self.tray.showMessage(
                "GhostReader",
                f"已隐藏，按 {hotkey_labels()['toggle']} 或点击托盘图标恢复",
                QSystemTrayIcon.MessageIcon.Information,
                1600,
            )

    def show_window(self):
        self.show()
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.raise_()
        self.activateWindow()
        self.act_toggle.setText("隐藏窗口")
        self._mouse_inside = True
        self._apply_opacity()
        if self.s.capture_guard:
            QTimer.singleShot(80, lambda: set_capture_guard(self, True))

    def _on_hotkey_status(self, message: str):
        QTimer.singleShot(1400, lambda: self.toast.show_message(message, 4200))

    def _hotkey_really_works(self) -> bool:
        return self.hotkeys.available and accessibility_trusted() is not False

    def _on_global_hotkey(self, name: str):
        if name == "toggle":
            self.toggle_visibility()
        elif name == "ghost":
            if not self.isVisible():
                self.show_window()
            self.toggle_ghost()
        elif name == "through":
            self.toggle_click_through()
        elif name == "top":
            self.toggle_on_top()

    def _on_tray(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.toggle_visibility()
        elif reason == QSystemTrayIcon.ActivationReason.MiddleClick:
            self.toggle_ghost()

    # ------------------------------------------------------------ 空闲淡化
    def _tick_idle(self):
        """只在幽灵模式下工作：光标在窗口内显示文字，移开整窗隐没。

        用光标坐标判断而不是 enter/leave 事件 —— 窗口完全透明时事件不可靠，
        但定时轮询一定能把它叫回来。
        """
        if not self.isVisible():
            return
        inside = self.frameGeometry().contains(QCursor.pos())
        # 抽屉打开时保持可见，否则用户点不到里面的条目
        if self._toc_open or self._settings_open:
            inside = True
        if inside == self._mouse_inside:
            return
        self._mouse_inside = inside
        if self._ghost:
            self._apply_opacity()

    # ------------------------------------------------------------ 事件
    def enterEvent(self, e):
        self._mouse_inside = True
        super().enterEvent(e)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._layout_panels()
        # 拖动窗口边缘后把尺寸回写到设置面板。
        # 正在拖滑块时不要回写，否则会把滑块拽回去、拖动被打断。
        if hasattr(self.panel, "win_w"):
            if not self.panel.win_w.slider.isSliderDown():
                self.panel.win_w.set_value(self.width())
            if not self.panel.win_h.slider.isSliderDown():
                self.panel.win_h.set_value(self.height())
            self.s.win_w, self.s.win_h = self.width(), self.height()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            edge = self._edge_at(e.position().toPoint())
            if edge:
                # 自己算几何，不依赖 startSystemResize（无边框 + 透明窗口上它不稳定）
                self._resizing_edge = edge
                self._resize_origin = e.globalPosition().toPoint()
                self._resize_geo = self.geometry()
                e.accept()
                return
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        if self._resizing_edge:
            self._resizing_edge = Qt.Edge(0)
            self.s.win_w, self.s.win_h = self.width(), self.height()
            self._persist()
            e.accept()
            return
        super().mouseReleaseEvent(e)

    def _edge_at(self, pos: QPoint) -> Qt.Edge:
        edge = Qt.Edge(0)
        if pos.x() <= MARGIN + EDGE:
            edge |= Qt.Edge.LeftEdge
        if pos.x() >= self.width() - MARGIN - EDGE:
            edge |= Qt.Edge.RightEdge
        if pos.y() <= MARGIN + EDGE:
            edge |= Qt.Edge.TopEdge
        if pos.y() >= self.height() - MARGIN - EDGE:
            edge |= Qt.Edge.BottomEdge
        return edge

    def mouseMoveEvent(self, e):
        if self._resizing_edge:
            d = e.globalPosition().toPoint() - self._resize_origin
            x, y, w, h = self._resize_geo.getRect()
            if self._resizing_edge & Qt.Edge.LeftEdge:
                x += d.x()
                w -= d.x()
            if self._resizing_edge & Qt.Edge.RightEdge:
                w += d.x()
            if self._resizing_edge & Qt.Edge.TopEdge:
                y += d.y()
                h -= d.y()
            if self._resizing_edge & Qt.Edge.BottomEdge:
                h += d.y()
            w = max(self.minimumWidth(), w)
            h = max(self.minimumHeight(), h)
            self.setGeometry(x, y, w, h)
            e.accept()
            return

        pos = e.position().toPoint()
        edge = self._edge_at(pos)
        cursor = Qt.CursorShape.ArrowCursor
        if edge in (Qt.Edge.LeftEdge, Qt.Edge.RightEdge):
            cursor = Qt.CursorShape.SizeHorCursor
        elif edge in (Qt.Edge.TopEdge, Qt.Edge.BottomEdge):
            cursor = Qt.CursorShape.SizeVerCursor
        elif edge in (
            Qt.Edge.LeftEdge | Qt.Edge.TopEdge,
            Qt.Edge.RightEdge | Qt.Edge.BottomEdge,
        ):
            cursor = Qt.CursorShape.SizeFDiagCursor
        elif edge in (
            Qt.Edge.RightEdge | Qt.Edge.TopEdge,
            Qt.Edge.LeftEdge | Qt.Edge.BottomEdge,
        ):
            cursor = Qt.CursorShape.SizeBDiagCursor
        self.setCursor(cursor)
        super().mouseMoveEvent(e)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            for url in e.mimeData().urls():
                if documents.is_supported(url.toLocalFile()):
                    e.acceptProposedAction()
                    return
        e.ignore()

    def dropEvent(self, e):
        for url in e.mimeData().urls():
            p = url.toLocalFile()
            if documents.is_supported(p):
                self.open_book(p)
                break

    def wheelEvent(self, e):
        if e.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier):
            self._bump_font(1 if e.angleDelta().y() > 0 else -1)
            e.accept()
            return
        super().wheelEvent(e)

    def keyPressEvent(self, e):
        key = e.key()
        from PyQt6.QtWidgets import QLineEdit

        # 焦点在输入框里时不抢按键
        if isinstance(QApplication.focusWidget(), QLineEdit):
            super().keyPressEvent(e)
            return
        if key in (Qt.Key.Key_Space, Qt.Key.Key_PageDown):
            self.reader.page(1)
            return
        if key == Qt.Key.Key_PageUp:
            self.reader.page(-1)
            return
        if key == Qt.Key.Key_Escape:
            if not self._close_panels():
                self.toggle_visibility()
            return
        if key == Qt.Key.Key_Left:
            self.goto_chapter(self.reader.chapter_index - 1)
            return
        if key == Qt.Key.Key_Right:
            self.goto_chapter(self.reader.chapter_index + 1)
            return
        super().keyPressEvent(e)

    def closeEvent(self, e):
        e.ignore()
        self.quit_app()

    # ------------------------------------------------------------ 持久化
    def _persist(self):
        if self.book:
            self.s.set_progress(self.reader.chapter_index, self.reader.fraction())
        if not self.isMaximized() and not self._ghost:
            g = self.geometry()
            self.s.win_x, self.s.win_y = g.x(), g.y()
            self.s.win_w, self.s.win_h = g.width(), g.height()
        self.s.save()

    def quit_app(self):
        self._persist()
        try:
            self.hotkeys.stop()
        except Exception:
            pass
        self.tray.hide()
        epub.cleanup(self.book)
        QApplication.quit()
