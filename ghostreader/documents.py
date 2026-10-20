"""统一入口：按扩展名把各种电子书解析成 Book。

支持的格式都用标准库实现，不引入第三方解析库：

| 扩展名 | 说明 |
| --- | --- |
| .epub | EPUB 2/3 |
| .txt  | 纯文本（自动嗅探 UTF-8 / GBK / Big5 / UTF-16） |
| .fb2  | FictionBook 2（XML） |
| .html/.htm/.xhtml/.zhtml | 单文件网页 |
| .docx | Word 文档（读 word/document.xml） |
| .mobi/.azw3/.azw | Kindle（PalmDOC 压缩） |

PDF 不在支持范围内：它是固定版式，与流式重排冲突，且解析需要额外的重型依赖。
"""

from __future__ import annotations

import html as html_lib
import re
import zipfile
from pathlib import Path

from . import docx as docx_mod
from . import epub, fb2, mobi, txt
from .epub import Book, Chapter, TocEntry, _Sanitizer

SUPPORTED_EXTS = {
    ".epub",
    ".txt",
    ".fb2",
    ".html",
    ".htm",
    ".xhtml",
    ".zhtml",
    ".docx",
    ".mobi",
    ".azw3",
    ".azw",
}

# 文件对话框用的过滤器
FILE_FILTER = (
    "电子书 (*.epub *.txt *.fb2 *.html *.htm *.xhtml *.zhtml *.docx *.mobi *.azw3 *.azw);;"
    "EPUB (*.epub);;纯文本 (*.txt);;FictionBook (*.fb2);;网页 (*.html *.htm *.xhtml *.zhtml);;"
    "Word (*.docx);;Kindle (*.mobi *.azw3 *.azw);;所有文件 (*)"
)


def is_supported(path: str | Path) -> bool:
    return Path(path).suffix.lower() in SUPPORTED_EXTS


def open_document(path: str | Path) -> Book:
    """按扩展名分派到对应的解析器。"""
    src = Path(path).expanduser().resolve()
    ext = src.suffix.lower()
    if ext == ".epub":
        return epub.open_epub(src)
    if ext == ".txt":
        return txt.open_txt(src)
    if ext == ".fb2":
        return fb2.open_fb2(src)
    if ext in (".html", ".htm", ".xhtml", ".zhtml"):
        return open_html_file(src)
    if ext == ".docx":
        return docx_mod.open_docx(src)
    if ext in (".mobi", ".azw3", ".azw"):
        return mobi.open_mobi(src)
    raise ValueError(f"不支持的格式：{ext or '（无扩展名）'}")


# ------------------------------------------------------------------ 公共工具

_PAGEBREAK_RE = re.compile(r"<mbp:pagebreak[^>]*>", re.I)


def split_html_chapters(raw_html: str) -> list[tuple[str, str]]:
    """把一整段 HTML 按 <h1>/<h2>/<mbp:pagebreak> 切成章节。

    返回 [(标题, html 片段)]；切不出来时整篇作为一章。
    """
    body = raw_html
    # Kindle 常见的分页标记先换成统一的分章标记
    body = _PAGEBREAK_RE.sub("<hr class='__pb'>", body)

    # 按 h1 / h2 / 分页标记切
    parts = re.split(r"(?=<h[12][\s>])|(?=<hr class='__pb'>)", body, flags=re.I)
    chunks: list[tuple[str, str]] = []
    for part in parts:
        if not part.strip():
            continue
        m = re.match(r"\s*<h[12][^>]*>(.*?)</h[12]>", part, re.I | re.S)
        title = ""
        if m:
            title = re.sub(r"<[^>]+>", "", m.group(1))
            title = html_lib.unescape(title).strip()
        chunks.append((title, part))

    if len(chunks) <= 1:
        return [("", body)]
    return chunks


def build_book_from_html(
    title: str,
    raw_html: str,
    source: Path,
    author: str = "",
    base_dir: Path | None = None,
) -> Book:
    """把整篇 HTML 净化、分章，产出 Book。"""
    base_dir = base_dir or source.parent
    chapters: list[Chapter] = []
    toc: list[TocEntry] = []

    for i, (ch_title, chunk) in enumerate(split_html_chapters(raw_html)):
        san = _Sanitizer(base_dir, {})
        try:
            san.feed(chunk)
            san.close()
            cleaned = san.result()
        except Exception:
            cleaned = ""
        if not cleaned.strip():
            continue
        chapters.append(
            Chapter(
                index=len(chapters),
                rel_path=f"chunk#{i}",
                title=ch_title or f"第 {len(chapters) + 1} 节",
                html=cleaned,
            )
        )

    if not chapters:
        raise ValueError("文件里没有可阅读的正文")

    toc = [TocEntry(c.title, c.index, 0) for c in chapters]
    return Book(
        title=title,
        author=author,
        root=base_dir,
        chapters=chapters,
        toc=toc,
        cover=None,
        source=source,
    )


def open_html_file(path: Path) -> Book:
    raw = txt.read_text_auto(path)
    # 顺手把 <body> 之外的东西剥掉
    m = re.search(r"<body[^>]*>(.*?)</body>", raw, re.I | re.S)
    body = m.group(1) if m else raw
    title = path.stem
    t = re.search(r"<title[^>]*>(.*?)</title>", raw, re.I | re.S)
    if t:
        name = re.sub(r"<[^>]+>", "", t.group(1)).strip()
        if name:
            title = html_lib.unescape(name)
    return build_book_from_html(title, body, path, base_dir=path.parent)


def is_zip(path: Path) -> bool:
    return zipfile.is_zipfile(path)
