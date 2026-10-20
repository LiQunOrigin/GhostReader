"""FictionBook 2（.fb2）解析：XML，标准库即可。

结构：<FictionBook><description><title-info>…</title-info></description>
      <body><section><title>章名</title><p>段落</p>…</section></body>
"""

from __future__ import annotations

import html
import xml.etree.ElementTree as ET
from pathlib import Path

from .epub import Book, Chapter, TocEntry


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _iter(elem: ET.Element, name: str):
    for e in elem.iter():
        if _local(e.tag) == name:
            yield e


def _first(elem: ET.Element, name: str):
    for e in _iter(elem, name):
        return e
    return None


def _text(elem: ET.Element | None) -> str:
    if elem is None:
        return ""
    return "".join(elem.itertext()).strip()


def _section_html(section: ET.Element) -> tuple[str, str]:
    """返回 (标题, 正文 html)。只取当前 section 的直属段落，子 section 单独成章。"""
    title_el = None
    for child in list(section):
        if _local(child.tag) == "title":
            title_el = child
            break
    title = _text(title_el)

    parts: list[str] = []
    for child in list(section):
        tag = _local(child.tag)
        if tag == "title":
            continue
        if tag == "section":
            continue
        if tag == "p":
            txt = _text(child)
            if txt:
                parts.append(f"<p>{html.escape(txt)}</p>")
        elif tag == "subtitle":
            txt = _text(child)
            if txt:
                parts.append(f"<h3>{html.escape(txt)}</h3>")
        elif tag in ("poem", "cite", "epigraph"):
            for p in _iter(child, "p"):
                txt = _text(p)
                if txt:
                    parts.append(f"<p>{html.escape(txt)}</p>")
        elif tag == "empty-line":
            continue
    return title, "".join(parts)


def open_fb2(path: str | Path) -> Book:
    src = Path(path).expanduser().resolve()
    if not src.is_file():
        raise FileNotFoundError(f"文件不存在：{src}")

    root = ET.parse(src).getroot()

    title = _text(_first(root, "book-title")) or src.stem
    author_parts = []
    for a in _iter(root, "author"):
        first = _text(_first(a, "first-name"))
        last = _text(_first(a, "last-name"))
        nick = _text(_first(a, "nickname"))
        name = " ".join(x for x in (first, last) if x) or nick
        if name:
            author_parts.append(name)
            break
    author = ", ".join(author_parts)

    chapters: list[Chapter] = []
    body = _first(root, "body")
    if body is not None:
        def walk(node: ET.Element):
            for child in list(node):
                if _local(child.tag) != "section":
                    continue
                ch_title, ch_html = _section_html(child)
                if ch_html.strip():
                    chapters.append(
                        Chapter(
                            index=len(chapters),
                            rel_path=f"fb2#{len(chapters)}",
                            title=ch_title or f"第 {len(chapters) + 1} 节",
                            html=ch_html,
                        )
                    )
                walk(child)   # 处理嵌套 section（卷 → 章）

        walk(body)

    if not chapters:
        # 退化：整篇当一章
        texts = [f"<p>{html.escape(_text(p))}</p>" for p in _iter(body, "p") if _text(p)]
        if not texts:
            raise ValueError("FB2 里没有可阅读的正文")
        chapters.append(Chapter(0, "fb2#0", title, "".join(texts)))

    toc = [TocEntry(c.title, c.index, 0) for c in chapters]
    return Book(
        title=title,
        author=author,
        root=src.parent,
        chapters=chapters,
        toc=toc,
        cover=None,
        source=src,
    )
