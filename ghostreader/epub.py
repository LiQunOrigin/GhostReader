"""EPUB 解析：容器 → OPF → 目录 → 章节正文（净化后的 HTML 片段）。

设计目标是零第三方依赖：只用标准库完成解包、元数据读取、目录树构建，
并把 XHTML 转成 Qt 富文本引擎能吃下的安全 HTML 子集。
"""

from __future__ import annotations

import os
import posixpath
import re
import shutil
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

# ---------------------------------------------------------------- 工具函数


def _local(tag: str) -> str:
    """去掉命名空间，只保留本地名，兼容不规范但常见的 OPF/NCX。"""
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


# ---------------------------------------------------------------- 数据模型


@dataclass
class TocEntry:
    title: str
    spine_index: int
    level: int = 0


@dataclass
class Chapter:
    index: int
    rel_path: str
    title: str
    html: str = ""


@dataclass
class Book:
    title: str = "未命名"
    author: str = ""
    root: Path = Path(".")
    chapters: list[Chapter] = field(default_factory=list)
    toc: list[TocEntry] = field(default_factory=list)
    cover: Path | None = None
    source: Path | None = None

    @property
    def chapter_count(self) -> int:
        return len(self.chapters)


# ---------------------------------------------------------------- HTML 净化

_VOID = {"br", "img", "hr", "col", "input", "meta", "link"}
_DROP_WITH_CONTENT = {"head", "script", "style", "math", "audio", "video", "iframe", "object"}
_RENAME = {
    "section": "div",
    "article": "div",
    "aside": "div",
    "figure": "div",
    "figcaption": "p",
    "header": "div",
    "footer": "div",
    "main": "div",
    "code": "span",
    "small": "span",
    "tt": "span",
    "cite": "em",
    "dfn": "em",
    "u": "span",
    "dl": "div",
    "dt": "p",
    "dd": "p",
}
_ALLOWED = {
    "p", "div", "br", "h1", "h2", "h3", "h4", "h5", "h6", "svg", "image",
    "em", "i", "strong", "b", "blockquote", "ul", "ol", "li",
    "img", "hr", "span", "a", "sub", "sup", "table", "thead",
    "tbody", "tr", "td", "th", "pre",
}


class _Sanitizer(HTMLParser):
    """把 XHTML 压平成 Qt 能稳定渲染的标签子集。

    - 丢弃脚本/样式/矢量图等危险或不可渲染节点
    - 相对图片路径改写为本地 file:// 绝对路径
    - 书籍内部链接改写为 gr://chapter/<索引> 伪协议，供阅读器跳转
    """

    def __init__(self, base_dir: Path, href_map: dict[str, int]):
        super().__init__(convert_charrefs=True)
        self.base_dir = base_dir
        self.href_map = href_map
        self.out: list[str] = []
        self.stack: list[str] = []
        self.skip_depth = 0
        self.skip_tag = ""
        self.silent = 0

    # -- 路径处理 -------------------------------------------------
    def _resolve_image(self, src: str) -> str | None:
        if not src or src.startswith(("data:", "http:", "https:")):
            return None if not src.startswith("data:") else src
        src = unquote(urlsplit(src).path)
        path = (self.base_dir / src.lstrip("/")).resolve()
        try:
            if path.is_file():
                return path.as_uri()
        except OSError:
            return None
        return None

    def _resolve_link(self, href: str) -> str | None:
        if not href:
            return None
        href = unquote(href)
        if href.startswith(("http:", "https:", "mailto:")):
            return None
        target = href.split("#", 1)[0]
        if not target:  # 同文档锚点，忽略
            return None
        key = posixpath.normpath(posixpath.join(".", target))
        idx = self.href_map.get(key)
        if idx is None:
            return None
        return f"gr://chapter/{idx}"

    # -- 解析回调 -------------------------------------------------
    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if self.skip_depth:
            if tag == self.skip_tag:
                self.skip_depth += 1
            return
        if tag in _DROP_WITH_CONTENT:
            self.skip_depth = 1
            self.skip_tag = tag
            return
        adict = dict(attrs)
        # SVG 只作为容器，里面真正有意义的是 <image>（封面页常见）
        if tag == "svg":
            self.silent += 1
            return
        if tag == "image":
            src = self._resolve_image(
                adict.get("xlink:href") or adict.get("href") or adict.get("src") or ""
            )
            if src:
                self.out.append(f'<img src="{src}" alt="">')
            return
        tag = _RENAME.get(tag, tag)
        if tag not in _ALLOWED:
            return
        if tag == "img":
            src = self._resolve_image(adict.get("src", ""))
            if src:
                alt = (adict.get("alt") or "").replace('"', "")
                self.out.append(f'<img src="{src}" alt="{alt}">')
            return
        if tag == "a":
            href = self._resolve_link(adict.get("href", ""))
            if href:
                self.out.append(f'<a href="{href}">')
                self.stack.append("a")
            return
        if tag in _VOID:
            self.out.append(f"<{tag}>")
            return
        self.out.append(f"<{tag}>")
        self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "svg" and self.silent:
            self.silent -= 1
            return
        if self.skip_depth:
            if tag == self.skip_tag:
                self.skip_depth -= 1
            return
        tag = _RENAME.get(tag, tag)
        if tag not in _ALLOWED or tag in _VOID:
            return
        if tag in self.stack:
            while self.stack:
                t = self.stack.pop()
                self.out.append(f"</{t}>")
                if t == tag:
                    break

    def handle_data(self, data):
        if self.skip_depth:
            return
        # 折叠空白，保留行内单空格
        text = re.sub(r"[ \t\r\n]+", " ", data)
        if not text.strip():
            return
        text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        self.out.append(text)

    def result(self) -> str:
        while self.stack:
            self.out.append(f"</{self.stack.pop()}>")
        return "".join(self.out)


_EMPTY_BLOCK = re.compile(
    r"<(div|p|h[1-6]|li|blockquote|span)>(?:\s|&nbsp;|<br>)*</\1>"
)


def _strip_empty(html: str) -> str:
    """删掉没有任何内容的块，避免整页空白行。"""
    prev = None
    while prev != html:
        prev = html
        html = _EMPTY_BLOCK.sub("", html)
    return html


def _has_content(html: str) -> bool:
    return bool(re.sub(r"<[^>]+>", "", html).strip()) or "<img" in html


# ---------------------------------------------------------------- 解析主体


class EpubError(Exception):
    pass


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8", "gb18030", "utf-16", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def _find_rootfile(extract_dir: Path) -> Path:
    container = extract_dir / "META-INF" / "container.xml"
    if not container.is_file():
        raise EpubError("缺少 META-INF/container.xml，不是有效的 EPUB")
    root = ET.parse(container).getroot()
    rf = _first(root, "rootfile")
    if rf is None or not rf.get("full-path"):
        raise EpubError("container.xml 中没有 rootfile")
    opf = extract_dir / rf.get("full-path")
    if not opf.is_file():
        raise EpubError(f"OPF 文件不存在：{rf.get('full-path')}")
    return opf


def _parse_nav(nav_path: Path, opf_dir: Path, spine_map: dict[str, int]) -> list[TocEntry]:
    entries: list[TocEntry] = []
    try:
        parser = ET.parse(nav_path)
    except ET.ParseError:
        return entries
    root = parser.getroot()
    nav = None
    for candidate in _iter(root, "nav"):
        if "toc" in (candidate.get("{http://www.idpf.org/2007/ops}type") or "").split():
            nav = candidate
            break
    if nav is None:
        nav = _first(root, "nav")
    if nav is None:
        return entries
    nav_dir = nav_path.parent

    def walk(node: ET.Element, level: int):
        for child in list(node):
            if _local(child.tag) == "li":
                for a in list(child):
                    if _local(a.tag) in ("a", "span"):
                        label = _text(a)
                        href = a.get("href", "")
                        idx = -1
                        if href:
                            target = unquote(href).split("#", 1)[0]
                            key = posixpath.normpath(
                                posixpath.join(nav_dir.relative_to(opf_dir).as_posix() if nav_dir != opf_dir else "",
                                               target)
                            )
                            idx = spine_map.get(key, -1)
                        if label and idx >= 0:
                            entries.append(TocEntry(label, idx, level))
                        elif label:
                            entries.append(TocEntry(label, -1, level))
                for sub in list(child):
                    if _local(sub.tag) in ("ol", "ul"):
                        walk(sub, level + 1)

    for ol in list(nav):
        if _local(ol.tag) in ("ol", "ul"):
            walk(ol, 0)
    return [e for e in entries if e.spine_index >= 0]


def _parse_ncx(ncx_path: Path, opf_dir: Path, spine_map: dict[str, int]) -> list[TocEntry]:
    entries: list[TocEntry] = []
    try:
        root = ET.parse(ncx_path).getroot()
    except ET.ParseError:
        return entries
    nav_map = _first(root, "navmap")
    if nav_map is None:
        return entries
    base = ncx_path.parent

    def walk(node: ET.Element, level: int):
        for child in list(node):
            if _local(child.tag) != "navpoint":
                continue
            label = _text(_first(child, "text"))
            src = ""
            content = _first(child, "content")
            if content is not None:
                src = content.get("src", "")
            idx = -1
            if src:
                target = unquote(src).split("#", 1)[0]
                rel_base = base.relative_to(opf_dir).as_posix() if base != opf_dir else ""
                key = posixpath.normpath(posixpath.join(rel_base, target))
                idx = spine_map.get(key, -1)
            if label and idx >= 0:
                entries.append(TocEntry(label, idx, level))
            walk(child, level + 1)

    walk(nav_map, 0)
    return entries


def _cover_image(manifest: dict, opf_dir: Path, root: ET.Element) -> Path | None:
    for item in _iter(root, "item"):
        if "cover-image" in (item.get("properties") or ""):
            p = opf_dir / unquote(item.get("href", ""))
            if p.is_file():
                return p
    # 退化：epub2 的 <meta name="cover" content="id">
    for meta in _iter(root, "meta"):
        if (meta.get("name") or "").lower() == "cover":
            item = manifest.get(meta.get("content", ""))
            if item:
                p = opf_dir / unquote(item["href"])
                if p.is_file():
                    return p
    return None


def open_epub(path: str | Path, workdir: Path | None = None) -> Book:
    """解包并解析 EPUB，返回 Book。"""
    src = Path(path).expanduser().resolve()
    if not src.is_file():
        raise EpubError(f"文件不存在：{src}")
    if not zipfile.is_zipfile(src):
        raise EpubError("不是有效的 EPUB（zip）文件")

    workdir = workdir or Path(tempfile.mkdtemp(prefix="ghostreader-"))
    workdir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(src) as zf:
        zf.extractall(workdir)

    opf_path = _find_rootfile(workdir)
    opf_dir = opf_path.parent
    root = ET.parse(opf_path).getroot()

    # 元数据
    title = _text(_first(root, "title")) or src.stem
    author = _text(_first(root, "creator"))

    # manifest
    manifest: dict[str, dict] = {}
    for item in _iter(root, "item"):
        href = item.get("href", "")
        if not href:
            continue
        manifest[item.get("id", "")] = {
            "href": href,
            "type": item.get("media-type", ""),
            "props": item.get("properties", "") or "",
        }

    # spine
    spine_ids = [e.get("idref", "") for e in _iter(root, "itemref")]
    spine_rel: list[str] = []
    for sid in spine_ids:
        item = manifest.get(sid)
        if not item:
            continue
        rel = posixpath.normpath(unquote(item["href"]))
        spine_rel.append(rel)
    if not spine_rel:
        # 退化：按 manifest 中 xhtml 顺序
        spine_rel = [
            posixpath.normpath(unquote(v["href"]))
            for v in manifest.values()
            if "html" in v["type"]
        ]
    if not spine_rel:
        raise EpubError("EPUB 中没有可阅读的正文文档")

    spine_map = {rel: i for i, rel in enumerate(spine_rel)}

    # 目录
    toc: list[TocEntry] = []
    nav_item = next((v for v in manifest.values() if "nav" in v["props"].split()), None)
    if nav_item:
        nav_path = opf_dir / unquote(nav_item["href"])
        if nav_path.is_file():
            toc = _parse_nav(nav_path, opf_dir, spine_map)
    if not toc:
        ncx_id = None
        spine_elem = _first(root, "spine")
        if spine_elem is not None:
            ncx_id = spine_elem.get("toc")
        ncx_item = manifest.get(ncx_id or "") or next(
            (v for v in manifest.values() if "ncx" in v["type"]), None
        )
        if ncx_item:
            ncx_path = opf_dir / unquote(ncx_item["href"])
            if ncx_path.is_file():
                toc = _parse_ncx(ncx_path, opf_dir, spine_map)

    # 章节正文
    chapters: list[Chapter] = []
    for i, rel in enumerate(spine_rel):
        doc = opf_dir / rel
        html = ""
        if doc.is_file():
            san = _Sanitizer(doc.parent, spine_map)
            try:
                san.feed(_read_text(doc))
                san.close()
                html = _strip_empty(san.result())
            except Exception:  # 单章解析失败不应拖垮整本
                html = ""
        if not _has_content(html):
            continue
        title_map = {e.spine_index: e.title for e in toc}
        chapters.append(
            Chapter(index=len(chapters), rel_path=rel, title=title_map.get(i, ""), html=html)
        )

    if not chapters:
        raise EpubError("未能解析出任何章节正文")

    # 补全缺失的章节标题
    for ch in chapters:
        if not ch.title:
            m = re.search(r"<(h[1-3])[^>]*>(.*?)</\1>", ch.html, re.S)
            if m:
                ch.title = re.sub(r"<[^>]+>", "", m.group(2)).strip()[:60]
        if not ch.title:
            low = ch.rel_path.lower()
            if ch.index == 0 and ("cover" in low or "title" in low):
                ch.title = "封面"
            else:
                ch.title = f"第 {ch.index + 1} 节"

    # 目录重映射到解析后的章节序号
    rel_to_index = {c.rel_path: c.index for c in chapters}
    new_toc: list[TocEntry] = []
    for e in toc:
        rel = spine_rel[e.spine_index] if e.spine_index < len(spine_rel) else None
        if rel and rel in rel_to_index:
            new_toc.append(TocEntry(e.title, rel_to_index[rel], e.level))
    if not new_toc:
        new_toc = [TocEntry(c.title, c.index, 0) for c in chapters]

    return Book(
        title=title,
        author=author,
        root=workdir,
        chapters=chapters,
        toc=new_toc,
        cover=_cover_image(manifest, opf_dir, root),
        source=src,
    )


def cleanup(book: Book | None) -> None:
    """删除解包出的临时目录。"""
    if not book:
        return
    try:
        # 只清理我们自己解包的临时目录，且必须确认里面确实是 EPUB 结构，
        # 否则 TXT 书的 root 指向用户目录时会被误删。
        if book.root.name.startswith("ghostreader-") and (book.root / "META-INF").is_dir():
            shutil.rmtree(book.root, ignore_errors=True)
    except OSError:
        pass
