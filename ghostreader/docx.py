"""DOCX 解析：docx 就是个 zip，正文在 word/document.xml。

只取段落文本与标题样式，图片、表格、脚注一律降级为纯文本。
"""

from __future__ import annotations

import html
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from .epub import Book, Chapter, TocEntry

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _para_text(p: ET.Element) -> str:
    parts = []
    for node in p.iter():
        tag = node.tag
        if tag == f"{_W}t":
            parts.append(node.text or "")
        elif tag == f"{_W}tab":
            parts.append("\t")
        elif tag == f"{_W}br":
            parts.append("\n")
    return "".join(parts).strip()


def _para_style(p: ET.Element) -> str:
    ppr = p.find(f"{_W}pPr")
    if ppr is None:
        return ""
    style = ppr.find(f"{_W}pStyle")
    if style is None:
        return ""
    return (style.get(f"{_W}val") or "").lower()


def _is_heading(style: str, text: str) -> bool:
    if style.startswith(("heading", "标题")):
        return True
    # 没有样式但形如标题的短行
    return len(text) <= 40 and bool(
        __import__("re").match(
            r"^\s*(?:第\s*[0-9零〇一二三四五六七八九十百千万两]+\s*[章节節卷回篇部集]|序章|楔子|前言|后记|尾声|番外)",
            text,
        )
    )


def open_docx(path: str | Path) -> Book:
    src = Path(path).expanduser().resolve()
    if not src.is_file():
        raise FileNotFoundError(f"文件不存在：{src}")
    if not zipfile.is_zipfile(src):
        raise ValueError("不是有效的 docx 文件")

    with zipfile.ZipFile(src) as zf:
        try:
            xml_bytes = zf.read("word/document.xml")
        except KeyError as exc:
            raise ValueError("docx 里找不到 word/document.xml") from exc

    root = ET.fromstring(xml_bytes)
    body = root.find(f"{_W}body")
    if body is None:
        raise ValueError("docx 正文为空")

    chapters: list[Chapter] = []
    cur_title = ""
    cur_parts: list[str] = []

    def flush():
        nonlocal cur_parts
        if cur_parts:
            chapters.append(
                Chapter(
                    index=len(chapters),
                    rel_path=f"docx#{len(chapters)}",
                    title=cur_title or f"第 {len(chapters) + 1} 节",
                    html="".join(cur_parts),
                )
            )
            cur_parts = []

    for child in list(body):
        if child.tag != f"{_W}p":
            continue
        text = _para_text(child)
        if not text:
            continue
        style = _para_style(child)
        if _is_heading(style, text):
            flush()
            cur_title = text
            cur_parts.append(f"<h2>{html.escape(text)}</h2>")
        else:
            cur_parts.append(f"<p>{html.escape(text)}</p>")
    flush()

    if not chapters:
        raise ValueError("docx 里没有可阅读的正文")

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
