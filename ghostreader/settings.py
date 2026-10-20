"""配置持久化：JSON 存在用户目录，跨平台一致。"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

APP_NAME = "GhostReader"


def config_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming"))
    elif os.uname().sysname == "Darwin":
        base = Path.home() / "Library/Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    p = base / APP_NAME
    p.mkdir(parents=True, exist_ok=True)
    return p


CONFIG_PATH = config_dir() / "settings.json"


# 主题预设：(背景色, 文字色, 名称)
THEMES: list[tuple[str, str, str]] = [
    ("#F4EDDF", "#33291C", "羊皮纸"),
    ("#FFFDF7", "#1F1F1F", "素白"),
    ("#C7E4C9", "#1E2A1F", "护眼绿"),
    ("#1C1D21", "#C9CBCF", "暗夜"),
    ("#000000", "#B9BCC2", "纯黑"),
]


@dataclass
class Settings:
    # 排版
    font_family: str = "Songti SC"
    font_size: float = 17.0
    line_height: int = 185  # 百分比
    indent: bool = True     # 段首缩进两字
    page_mode: str = "page"  # page = 整页翻页；scroll = 连续滚动
    text_color: str = "#33291C"
    text_alpha: float = 1.0     # 字体不透明度（1.0 = 完全不透明）
    theme_index: int = 0

    # 窗口
    bg_color: str = "#F4EDDF"
    bg_alpha: float = 0.88        # 背景不透明度（文字始终不透明）
    window_opacity: float = 1.0   # 整窗不透明度（含文字）
    always_on_top: bool = True
    column_backing: bool = True   # 低透明度时给正文加一层底衬，保证可读
    reading_width: int = 720      # 正文栏最大宽度（px）
    padding: int = 44             # 正文内边距

    # 隐身
    ghost_text: str = "light"   # 幽灵模式文字色：light / dark / theme
    idle_fade: bool = True
    idle_opacity: float = 0.42
    idle_delay_ms: int = 0   # 0 = 鼠标离开立即淡化
    click_through: bool = False
    capture_guard: bool = False

    # 窗口几何
    win_x: int = -1
    win_y: int = -1
    win_w: int = 760
    win_h: int = 880

    # 配置版本：用于把旧版本的默认值迁移到新默认
    config_version: int = 3

    # 阅读状态
    last_book: str = ""
    progress: dict = field(default_factory=dict)

    # ---------------------------------------------------------------
    def to_json(self) -> dict:
        return asdict(self)

    @classmethod
    def load(cls, path: Path = CONFIG_PATH) -> "Settings":
        s = cls()
        try:
            data = json.loads(path.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            return s
        legacy = "config_version" not in data
        valid = {f.name for f in fields(cls)}
        for k, v in data.items():
            if k in valid and v is not None:
                try:
                    setattr(s, k, v)
                except Exception:
                    pass
        if legacy:
            # 1.x 的默认是“离开 2.2 秒才淡化”，2.x 改为离开即淡化
            s.idle_fade = True
            s.idle_delay_ms = 0
        if legacy or int(data.get("config_version", 0) or 0) < 3:
            # 3.x 起幽灵模式默认用浅灰白：跟随主题时深色字会和深色桌面糊在一起
            if s.ghost_text == "theme":
                s.ghost_text = "light"
            s.config_version = 3
        s.clamp()
        return s

    def save(self, path: Path = CONFIG_PATH) -> None:
        self.clamp()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.to_json(), ensure_ascii=False, indent=2), "utf-8")
            tmp.replace(path)
        except OSError:
            pass

    def clamp(self) -> None:
        self.font_size = min(40.0, max(11.0, float(self.font_size)))
        self.line_height = int(min(260, max(120, self.line_height)))
        self.text_alpha = min(1.0, max(0.25, float(self.text_alpha)))
        self.bg_alpha = min(1.0, max(0.15, float(self.bg_alpha)))
        self.window_opacity = min(1.0, max(0.30, float(self.window_opacity)))
        self.idle_opacity = min(1.0, max(0.15, float(self.idle_opacity)))
        self.idle_delay_ms = int(min(20000, max(0, self.idle_delay_ms)))
        self.reading_width = int(min(1400, max(360, self.reading_width)))
        self.padding = int(min(120, max(12, self.padding)))
        self.win_w = int(min(3000, max(360, self.win_w)))
        self.win_h = int(min(3000, max(260, self.win_h)))
        if not 0 <= self.theme_index < len(THEMES):
            self.theme_index = 0

    # ---------------------------------------------------------------
    def book_key(self) -> str:
        return os.path.basename(self.last_book) if self.last_book else ""

    def get_progress(self) -> tuple[int, float]:
        rec = self.progress.get(self.book_key()) or {}
        return int(rec.get("chapter", 0)), float(rec.get("fraction", 0.0))

    def set_progress(self, chapter: int, fraction: float) -> None:
        if not self.last_book:
            return
        self.progress[self.book_key()] = {
            "chapter": int(chapter),
            "fraction": round(float(fraction), 4),
        }
