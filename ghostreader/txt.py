"""TXT 解析：编码嗅探 → 章节切分 → 段落转 HTML。

产出和 epub.py 相同的 Book 结构，阅读器无需区分来源。
"""

from __future__ import annotations

import html
import re
from pathlib import Path

from .epub import Book, Chapter, TocEntry

# 常见中文 TXT 的章节标题：第X章 / 第X节 / 序章 / 楔子 / 番外 …
_CN_NUM = "0-9零〇一二三四五六七八九十百千万两"
_CHAPTER_RE = re.compile(
    r"^\s*(?:"
    rf"第\s*[{_CN_NUM}]+\s*[章节節卷回篇部集]"
    rf"|卷\s*[{_CN_NUM}]+"
    r"|序章|序言|序幕|楔子|引子|前言|后记|後記|尾声|尾聲|终章|終章|番外"
    r"|Chapter\s*\d+"
    r")"
)
# 标题行通常很短，太长的一律当正文，避免正文里出现"第一章"就被切开
_TITLE_MAX_LEN = 48

_BLANK_RE = re.compile(r"^\s*$")
_INLINE_TAG_RE = re.compile(r"<[^>]+>")


def read_text_auto(path: Path) -> str:
    """按 BOM → UTF-8 → GB18030 → Big5 的顺序嗅探编码。"""
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:].decode("utf-8", "replace")
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16", "replace")
    for enc in ("utf-8", "gb18030", "big5"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("gb18030", "replace")


def _clean_line(line: str) -> str:
    return line.strip().replace("\u3000", " ").strip()


def _is_chapter_title(line: str) -> bool:
    text = _clean_line(line)
    if not text or len(text) > _TITLE_MAX_LEN:
        return False
    return bool(_CHAPTER_RE.match(text))


def _paragraphs(lines: list[str]) -> list[str]:
    """把若干行压成段落：空行分段；连续非空行按"一段一行"处理。"""
    paras: list[str] = []
    for line in lines:
        text = _clean_line(line)
        if not text:
            continue
        paras.append(text)
    return paras


def _to_html(paras: list[str]) -> str:
    out = []
    for p in paras:
        text = html.escape(p)
        # 行内保留原有的缩进语义：TXT 里常见两个全角空格开头
        out.append(f"<p>{text}</p>")
    return "".join(out)


def _split_chapters(text: str) -> list[tuple[str, list[str]]]:
    """按标题行切章，返回 [(标题, 行列表)]。识别不到标题时按长度兜底切分。"""
    lines = text.splitlines()
    chapters: list[tuple[str, list[str]]] = []
    current_title = ""
    current: list[str] = []

    for line in lines:
        if _is_chapter_title(line):
            if current and any(_clean_line(x) for x in current):
                chapters.append((current_title or "开篇", current))
            current_title = _clean_line(line)
            current = []
        else:
            current.append(line)
    if current and any(_clean_line(x) for x in current):
        chapters.append((current_title or "开篇", current))

    if not chapters:
        return [("全文", lines)]

    # 整本没有识别出标题（只有"开篇"一章且很长）时，按字数切块
    if len(chapters) == 1 and chapters[0][0] == "开篇":
        body = chapters[0][1]
        chunk = 6000
        total_chars = sum(len(_clean_line(x)) for x in body)
        if total_chars > chunk * 1.5:
            blocks: list[tuple[str, list[str]]] = []
            buf: list[str] = []
            size = 0
            idx = 1
            for line in body:
                buf.append(line)
                size += len(_clean_line(line))
                if size >= chunk:
                    blocks.append((f"第 {idx} 节", buf))
                    buf, size, idx = [], 0, idx + 1
            if buf:
                blocks.append((f"第 {idx} 节", buf))
            return blocks
    return chapters


def open_txt(path: str | Path) -> Book:
    src = Path(path).expanduser().resolve()
    if not src.is_file():
        raise FileNotFoundError(f"文件不存在：{src}")

    text = read_text_auto(src)
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    raw_chapters = _split_chapters(text)
    chapters: list[Chapter] = []
    for i, (title, lines) in enumerate(raw_chapters):
        paras = _paragraphs(lines)
        if not paras:
            continue
        chapters.append(
            Chapter(
                index=len(chapters),
                rel_path=f"txt#{i}",
                title=title or f"第 {len(chapters) + 1} 节",
                html=_to_html(paras),
            )
        )
    if not chapters:
        raise ValueError("文件内容为空")

    toc = [TocEntry(c.title, c.index, 0) for c in chapters]
    return Book(
        title=src.stem,
        author="",
        root=src.parent,
        chapters=chapters,
        toc=toc,
        cover=None,
        source=src,
    )
