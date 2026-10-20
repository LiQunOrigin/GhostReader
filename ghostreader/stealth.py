"""隐身相关能力：防录屏、点击穿透、系统级全局热键。

所有系统调用都做了失败兜底：能力不可用时只降级，不影响阅读。
"""

from __future__ import annotations

import ctypes
import ctypes.util
import os
import sys

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtWidgets import QWidget


# ------------------------------------------------------------------ 防录屏


def set_capture_guard(widget: QWidget, enabled: bool) -> bool:
    """让窗口在屏幕共享 / 录屏 / 截图中不可见（尽力而为）。

    注意：必须确认真实原生窗口已创建，否则把无效指针交给 objc 会直接崩溃。
    """
    from PyQt6.QtGui import QGuiApplication

    platform = QGuiApplication.platformName()
    if not widget.isVisible() or platform not in ("cocoa", "windows"):
        return False
    try:
        if sys.platform == "darwin":
            return _mac_capture_guard(widget, enabled)
        if os.name == "nt":
            return _win_capture_guard(widget, enabled)
    except Exception:
        return False
    return False


def _mac_capture_guard(widget: QWidget, enabled: bool) -> bool:
    """优先走 pyobjc；未安装时退回 ctypes，两条路都做防御。"""
    target = 0 if enabled else 1  # NSWindowSharingNone / NSWindowSharingReadOnly
    try:
        import objc
        from AppKit import NSWindowSharingNone, NSWindowSharingReadOnly  # noqa: F401
        from ctypes import c_void_p

        view = objc.objc_object(c_void_p=int(widget.winId()))
        window = view.window() if view is not None else None
        if window is None:
            return False
        window.setSharingType_(target)
        return True
    except Exception:
        pass

    try:
        objc_lib = ctypes.CDLL(ctypes.util.find_library("objc"))
        objc_lib.objc_msgSend.restype = ctypes.c_void_p
        objc_lib.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        objc_lib.sel_registerName.restype = ctypes.c_void_p
        objc_lib.sel_registerName.argtypes = [ctypes.c_char_p]
        view_ptr = ctypes.c_void_p(int(widget.winId()))
        if not view_ptr:
            return False
        window = objc_lib.objc_msgSend(view_ptr, objc_lib.sel_registerName(b"window"))
        if not window:
            return False
        objc_lib.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]
        objc_lib.objc_msgSend(window, objc_lib.sel_registerName(b"setSharingType:"), target)
        return True
    except Exception:
        return False


def _win_capture_guard(widget: QWidget, enabled: bool) -> bool:
    user32 = ctypes.windll.user32
    hwnd = int(widget.winId())
    if enabled:
        # WDA_EXCLUDEFROMCAPTURE (0x11) 优先，老系统退回 WDA_MONITOR (0x01)
        if not user32.SetWindowDisplayAffinity(hwnd, 0x11):
            return bool(user32.SetWindowDisplayAffinity(hwnd, 0x01))
        return True
    return bool(user32.SetWindowDisplayAffinity(hwnd, 0x00))


# ------------------------------------------------------------------ 点击穿透


def set_click_through(widget: QWidget, enabled: bool) -> None:
    """开启后鼠标事件穿透到下层窗口，用户仍可透过文字看内容。"""
    flags = widget.windowFlags()
    if enabled:
        flags |= Qt.WindowType.WindowTransparentForInput
    else:
        flags &= ~Qt.WindowType.WindowTransparentForInput
    visible = widget.isVisible()
    widget.setWindowFlags(flags)
    if visible:
        widget.show()
        widget.raise_()


# ------------------------------------------------------------------ 权限检测


def accessibility_trusted() -> bool | None:
    """macOS 辅助功能授权状态；其他平台或无法判断时返回 None。"""
    if sys.platform != "darwin":
        return None
    try:
        from ApplicationServices import AXIsProcessTrusted

        return bool(AXIsProcessTrusted())
    except Exception:
        return None


# ------------------------------------------------------------------ 全局热键

DEFAULT_HOTKEYS = {
    "toggle": "<ctrl>+<shift>+h",      # 隐藏 / 显示
    "ghost": "<ctrl>+<shift>+g",       # 幽灵模式（极简 + 低透明）
    "through": "<ctrl>+<shift>+j",     # 点击穿透
    "top": "<ctrl>+<shift>+t",         # 置顶切换
}


class GlobalHotkeys(QObject):
    """系统级热键监听。pynput 不可用（或未授权）时静默降级。"""

    fired = pyqtSignal(str)
    status = pyqtSignal(str)

    def __init__(self, mapping: dict[str, str] | None = None, parent=None):
        super().__init__(parent)
        self.mapping = mapping or DEFAULT_HOTKEYS
        self._listener = None
        self.available = False

    def start(self) -> bool:
        try:
            from pynput import keyboard
        except Exception as exc:  # pragma: no cover - 环境相关
            self.status.emit(f"全局热键不可用：{exc}")
            return False
        if accessibility_trusted() is False:
            # 监听能启动，但系统不会把按键送过来，必须让用户知道
            self.status.emit("全局热键需要「辅助功能」授权，当前仅在窗口聚焦时可用")
        try:
            hotkeys = {combo: (lambda name=name: self.fired.emit(name)) for name, combo in self.mapping.items()}
            self._listener = keyboard.GlobalHotKeys(hotkeys)
            self._listener.daemon = True
            self._listener.start()
            self.available = True
            self.status.emit("全局热键已启用")
            return True
        except Exception as exc:  # pragma: no cover
            self.status.emit(f"全局热键注册失败：{exc}")
            return False

    def stop(self) -> None:
        if self._listener is not None:
            try:
                self._listener.stop()
            except Exception:
                pass
            self._listener = None
        self.available = False
