#!/usr/bin/env python3
"""生成一个用于自测的示例 EPUB（含目录、多章节、插图）。

    python tools/make_sample_epub.py out.epub
"""

from __future__ import annotations

import struct
import sys
import zipfile
import zlib
from pathlib import Path

W, H = 600, 380


def png_bytes(width: int, height: int, rgb_func) -> bytes:
    raw = bytearray()
    for y in range(height):
        raw.append(0)  # filter: none
        for x in range(width):
            r, g, b = rgb_func(x, y)
            raw += bytes((r, g, b))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )


def cover_rgb(x: int, y: int):
    t = y / H
    base = (int(238 - 40 * t), int(226 - 46 * t), int(206 - 40 * t))
    cx, cy, r = W * 0.72, H * 0.34, 120
    d = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
    if d < r:
        k = 1 - d / r
        return (
            min(255, int(base[0] + 26 * k)),
            min(255, int(base[1] + 10 * k)),
            min(255, int(base[2] - 30 * k)),
        )
    return base


def fig_rgb(x: int, y: int):
    t = x / W
    return (int(90 + 60 * t), int(105 + 40 * (1 - t)), int(120 + 70 * t))


CHAPTERS = [
    (
        "第一章 灯下的位置",
        [
            "夜里十一点，写字楼的灯只剩三盏。她把杯子推到桌角，让出半个手掌的位置，把屏幕往右下挪了两寸——那里有一块不常被目光扫过的区域。",
            "这是多年养成的习惯：重要的东西不放在最显眼的地方，而是放在看起来最不重要的地方。灯下最亮的地方往往最容易被忽略，因为所有人的注意力都在正中央。",
            "于是她读书。文字浮在桌面之上，像一层薄薄的雾，随窗口的透明度变化而浓淡。有人从身后走过，只看到一屏灰色的报表，和一份安静得近乎空白的桌面。",
            "阅读本来不需要被看见。它只需要被完成。",
        ],
    ),
    (
        "第二章 透明度",
        [
            "透明是一种分寸。太透，字会散在壁纸的花纹里，眼睛要用力去辨认，读三行就累；太实，又像在办公室墙上挂了一块黑板，隔着三排工位都能读出你在看什么。",
            "合适的做法是让背景保持一层薄薄的不透明，而让文字本身完全不透明。这样即便窗口只余六成实度，字仍然是清楚的——眼睛读的是字，不是背景。",
            "她把滑块停在百分之八十六。这个数字不是算出来的，是读了两个小时之后手自己停下来的位置。",
        ],
    ),
    (
        "第三章 快捷键",
        [
            "真正让人安心的，不是窗口有多隐蔽，而是随时能消失。",
            "手指落在两个键上，屏幕上的文字就退进托盘，连任务栏都不留痕迹；再按一次，它从原来的位置长回来，页码还是原来那一页。",
            "习惯之后，这套动作会变成一种呼吸：有人靠近，吸气；人走开，呼气。阅读因此变得从容，而不是提心吊胆。",
        ],
    ),
    (
        "第四章 留白",
        [
            "排版里最容易被忽略的是留白。行距松一点，段落之间空一点，眼睛才有地方休息。中文尤其如此：字是方的，挤在一起就像一堵墙。",
            "她喜欢段首缩进两字，喜欢行距接近两倍，喜欢正文栏宽不超过七百二十像素——一行三十多个字，眼睛不必长距离折返。",
            "书读到最后，记住的往往不是句子，而是那种节奏：一行一行往下走，像夜里沿着一条熟悉的走廊，走到尽头，灯还亮着。",
        ],
    ),
]

FIG_HTML = """
  <div class="figure">
    <img src="images/fig1.png" alt="插图"/>
    <p class="caption">图 1 · 夜里的窗口</p>
  </div>
"""

CSS = """
body { margin: 0; padding: 0; line-height: 1.8; }
h1 { font-size: 1.5em; margin: 1.2em 0 0.8em; font-weight: 600; }
h2 { font-size: 1.15em; margin: 1em 0 0.6em; }
p { margin: 0 0 0.9em; text-indent: 2em; }
p.caption { text-indent: 0; text-align: center; font-size: 0.85em; opacity: 0.7; }
.figure { margin: 1.2em 0; text-align: center; }
img { max-width: 100%; }
blockquote { margin: 1em 0 1em 1.2em; padding-left: 0.8em; border-left: 2px solid #b99; }
"""


def chapter_xhtml(title: str, paras: list[str], extra: str = "") -> str:
    body = "\n".join(f"    <p>{p}</p>" for p in paras)
    return f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="zh-CN">
<head><title>{title}</title><link rel="stylesheet" href="style.css"/></head>
<body>
  <h1>{title}</h1>
{body}
{extra}
</body>
</html>
"""


def build(out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    opf_items = []
    spine = []
    nav_items = []
    for i, (title, paras) in enumerate(CHAPTERS, start=1):
        name = f"ch{i}.xhtml"
        opf_items.append(
            f'    <item id="ch{i}" href="{name}" media-type="application/xhtml+xml"/>'
        )
        spine.append(f'    <itemref idref="ch{i}"/>')
        nav_items.append(f'      <li><a href="{name}">{title}</a></li>')

    opf = f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="uid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="uid">urn:uuid:ghostreader-sample-0001</dc:identifier>
    <dc:title>夜读：关于透明度的一本小书</dc:title>
    <dc:creator>GhostReader 示例</dc:creator>
    <dc:language>zh-CN</dc:language>
    <meta property="dcterms:modified">2026-10-20T00:00:00Z</meta>
  </metadata>
  <manifest>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
    <item id="css" href="style.css" media-type="text/css"/>
    <item id="cover-img" href="images/cover.png" media-type="image/png" properties="cover-image"/>
    <item id="fig1" href="images/fig1.png" media-type="image/png"/>
{chr(10).join(opf_items)}
  </manifest>
  <spine>
{chr(10).join(spine)}
  </spine>
</package>
"""

    nav = f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head><title>目录</title></head>
<body>
  <nav epub:type="toc" id="toc">
    <h1>目录</h1>
    <ol>
{chr(10).join(nav_items)}
    </ol>
  </nav>
</body>
</html>
"""

    container = """<?xml version="1.0" encoding="utf-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""

    with zipfile.ZipFile(out, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", container, compress_type=zipfile.ZIP_DEFLATED)
        zf.writestr("OEBPS/content.opf", opf, compress_type=zipfile.ZIP_DEFLATED)
        zf.writestr("OEBPS/nav.xhtml", nav, compress_type=zipfile.ZIP_DEFLATED)
        zf.writestr("OEBPS/style.css", CSS, compress_type=zipfile.ZIP_DEFLATED)
        zf.writestr("OEBPS/images/cover.png", png_bytes(W, H, cover_rgb), compress_type=zipfile.ZIP_DEFLATED)
        zf.writestr("OEBPS/images/fig1.png", png_bytes(W, H, fig_rgb), compress_type=zipfile.ZIP_DEFLATED)
        for i, (title, paras) in enumerate(CHAPTERS, start=1):
            extra = FIG_HTML if i == 2 else ""
            zf.writestr(
                f"OEBPS/ch{i}.xhtml",
                chapter_xhtml(title, paras, extra),
                compress_type=zipfile.ZIP_DEFLATED,
            )
    return out


if __name__ == "__main__":
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "sample.epub")
    print(build(target))
