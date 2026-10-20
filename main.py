#!/usr/bin/env python3
"""GhostReader 启动入口。

用法：
    python main.py                  # 打开上次阅读的书
    python main.py book.epub        # 直接打开指定书籍
    python main.py --no-global-hotkey
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def resource_path(rel: str) -> Path:
    """兼容 PyInstaller 打包后的资源路径。"""
    base = Path(getattr(sys, "_MEIPASS", ROOT))
    return base / rel

from PyQt6.QtCore import QEvent, QObject, Qt  # noqa: E402
from PyQt6.QtGui import QIcon  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from ghostreader.settings import Settings  # noqa: E402
from ghostreader.single_instance import SingleInstance, payload_from_argv  # noqa: E402
from ghostreader.window import MainWindow  # noqa: E402


def setup_logging() -> None:
    """打包成 .app 后没有终端，把 stdout/stderr 接到日志文件。"""
    if not getattr(sys, "frozen", False):
        return
    try:
        if sys.platform == "darwin":
            log_dir = Path.home() / "Library" / "Logs"
        elif os.name == "nt":
            log_dir = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "GhostReader" / "Logs"
        else:
            log_dir = Path.home() / ".local" / "share" / "GhostReader" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        stream = open(log_dir / "GhostReader.log", "a", buffering=1, encoding="utf-8")
        sys.stdout = stream
        sys.stderr = stream

        def excepthook(exc_type, exc, tb):
            log("未捕获异常：\n" + "".join(traceback.format_exception(exc_type, exc, tb)))

        sys.excepthook = excepthook
    except Exception:
        pass


def log(message: str) -> None:
    try:
        print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)
    except Exception:
        pass


def setup_logging() -> None:
    """打包成 .app 后没有终端，把 stdout/stderr 接到日志文件。"""
    if not getattr(sys, "frozen", False):
        return
    try:
        if sys.platform == "darwin":
            log_dir = Path.home() / "Library" / "Logs"
        elif os.name == "nt":
            log_dir = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "GhostReader" / "Logs"
        else:
            log_dir = Path.home() / ".local" / "share" / "GhostReader" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        stream = open(log_dir / "GhostReader.log", "a", buffering=1, encoding="utf-8")
        sys.stdout = stream
        sys.stderr = stream

        def excepthook(exc_type, exc, tb):
            log("未捕获异常：\n" + "".join(traceback.format_exception(exc_type, exc, tb)))

        sys.excepthook = excepthook
    except Exception:
        pass


def log(message: str) -> None:
    try:
        print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)
    except Exception:
        pass


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="GhostReader · 半透明隐身 EPUB 阅读器")
    p.add_argument("file", nargs="?", help="要打开的 EPUB 文件")
    p.add_argument("--no-global-hotkey", action="store_true", help="不注册系统级全局热键")
    p.add_argument("--alpha", type=float, default=None, help="启动时的背景不透明度 (0.15-1.0)")
    p.add_argument("--ghost", action="store_true", help="以幽灵模式启动")
    return p.parse_args(argv)


class FileOpenRouter(QObject):
    """接住 macOS 的「用本应用打开文件」事件。

    Finder / Dock / `open -a` 传文件走的是 Apple Event，不会出现在 argv 里，
    Qt 会把它转成 QFileOpenEvent。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pending: list[str] = []
        self.callback = None

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.FileOpen:
            path = event.file()
            log(f"FileOpen 事件: {path}")
            if path:
                if self.callback:
                    self.callback(path)
                else:
                    self.pending.append(path)
            return True
        return super().eventFilter(obj, event)

    def flush(self):
        while self.pending:
            path = self.pending.pop(0)
            if self.callback:
                self.callback(path)


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    setup_logging()
    raw = list(argv if argv is not None else sys.argv[1:])
    log(f"启动 argv={raw}")
    log(f"启动 argv={raw}")
    # Finder 双击启动会附带 -psn_0_123456 之类的进程序列号参数，直接忽略
    args = parse_args([a for a in raw if not a.startswith("-psn")])

    QApplication.setAttribute(Qt.ApplicationAttribute.AA_DontCreateNativeWidgetSiblings, True)
    app = QApplication(sys.argv[:1])
    app.setApplicationName("GhostReader")
    app.setApplicationDisplayName("GhostReader")
    app.setQuitOnLastWindowClosed(False)

    router = FileOpenRouter(app)
    app.installEventFilter(router)

    icon_path = resource_path("assets/icon_256.png")
    if icon_path.is_file():
        # macOS 上 QIcon 会直接成为 Dock 图标，不需要碰 AppKit
        app.setWindowIcon(QIcon(str(icon_path)))

    instance = SingleInstance()
    if instance.notify_running(payload_from_argv(raw)):
        print("GhostReader 已在运行，已转发请求")
        return 0
    if not instance.listen():
        print("无法建立单实例监听，继续启动")

    settings = Settings.load()
    if args.alpha is not None:
        settings.bg_alpha = max(0.15, min(1.0, args.alpha))

    win = MainWindow(settings)
    if args.no_global_hotkey:
        win.hotkeys.stop()
    if args.file:
        win.open_book(args.file)
    if args.ghost:
        win.toggle_ghost()
    def on_second_instance(payload: str):
        log(f"收到第二实例请求: {payload!r}")
        if payload:
            win.open_book(payload)
        win.show_window()

    instance.messageReceived.connect(on_second_instance)

    # 事件循环启动前可能已经收到过打开请求，这里补处理
    router.callback = lambda p: (log(f"打开 {p}"), win.open_book(p))
    router.flush()

    win.show()
    win.raise_()
    win.activateWindow()
    code = app.exec()
    instance.close()
    return code


if __name__ == "__main__":
    sys.exit(main())
