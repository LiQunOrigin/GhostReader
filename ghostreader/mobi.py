"""Kindle MOBI / AZW3 解析：PDB 容器 + PalmDOC(LZ77) 解压 + HTML 抽取。

只处理最常见的两种压缩：不压缩(1) 与 PalmDOC(2)。
HUFF/CDIC 压缩（少数书）与 DRM 加密书会明确报错。
"""

from __future__ import annotations

from pathlib import Path

from .epub import Book


def _palmdoc_decompress(data: bytes) -> bytes:
    """PalmDOC LZ77 解压。"""
    out = bytearray()
    i = 0
    n = len(data)
    while i < n:
        c = data[i]
        i += 1
        if c == 0x00:
            out.append(0)
        elif 0x01 <= c <= 0x08:          # 后面 c 个字节原样复制
            out += data[i:i + c]
            i += c
        elif c <= 0x7F:                  # ASCII
            out.append(c)
        elif c <= 0xBF:                  # 2 字节：距离 + 长度
            if i >= n:
                break
            pair = (c << 8) | data[i]
            i += 1
            distance = (pair >> 3) & 0x07FF
            length = (pair & 0x07) + 3
            start = len(out) - distance
            if start < 0:
                continue
            for _ in range(length):
                out.append(out[start])
                start += 1
        else:                            # 0xC0-0xFF：空格 + 字符
            out.append(0x20)
            out.append(c ^ 0x80)
    return bytes(out)


def _record_offsets(raw: bytes) -> list[int]:
    if len(raw) < 78:
        raise ValueError("文件太小，不是有效的 MOBI")
    count = int.from_bytes(raw[76:78], "big")
    if count <= 0 or count > 100000:
        raise ValueError("MOBI 记录数异常")
    offsets = []
    for i in range(count):
        pos = 78 + i * 8
        if pos + 4 > len(raw):
            break
        offsets.append(int.from_bytes(raw[pos:pos + 4], "big"))
    offsets.append(len(raw))
    return offsets


def _book_title(raw: bytes) -> str:
    """尽量从 MOBI 头里取书名，取不到就用文件名。"""
    try:
        start = 0x54          # MOBI header 内 full name offset（相对记录 0 起点 +16）
        # full name offset 位于 MOBI 头 offset 0x54（文件 0x64），长度在 0x58
        name_off = int.from_bytes(raw[16 + 0x54:16 + 0x58], "big")
        name_len = int.from_bytes(raw[16 + 0x58:16 + 0x5C], "big")
        if 0 < name_len < 512 and 0 < name_off < len(raw):
            blob = raw[name_off:name_off + name_len]
            for enc in ("utf-8", "cp1252"):
                try:
                    text = blob.decode(enc).strip()
                    if text:
                        return text
                except UnicodeDecodeError:
                    continue
    except Exception:
        pass
    return ""


def open_mobi(path: str | Path) -> Book:
    from .documents import build_book_from_html

    src = Path(path).expanduser().resolve()
    if not src.is_file():
        raise FileNotFoundError(f"文件不存在：{src}")

    raw = src.read_bytes()
    offsets = _record_offsets(raw)
    if len(offsets) < 3:
        raise ValueError("MOBI 记录不足")

    rec0 = raw[offsets[0]:offsets[1]]
    if len(rec0) < 132:
        raise ValueError("MOBI 头部不完整")

    compression = int.from_bytes(rec0[0:2], "big")
    text_length = int.from_bytes(rec0[4:8], "big")
    text_encoding = int.from_bytes(rec0[28:32], "big")
    encryption = int.from_bytes(rec0[12:14], "big")

    if encryption != 0:
        raise ValueError("这本书带 DRM 加密，无法解析")
    if compression not in (1, 2):
        raise ValueError(f"不支持的 MOBI 压缩方式（{compression}），可能是 HUFF/CDIC")

    first_non_book = int.from_bytes(rec0[0x60:0x64], "big")
    total = len(offsets) - 1
    if not (1 < first_non_book <= total):
        first_non_book = total

    chunks: list[bytes] = []
    for i in range(1, first_non_book):
        data = raw[offsets[i]:offsets[i + 1]]
        if compression == 2:
            data = _palmdoc_decompress(data)
        chunks.append(data)

    text_bytes = b"".join(chunks)
    if text_length and text_length <= len(text_bytes):
        text_bytes = text_bytes[:text_length]

    encoding = "utf-8" if text_encoding == 65001 else "cp1252"
    html_text = text_bytes.decode(encoding, "replace")

    title = _book_title(rec0) or src.stem
    return build_book_from_html(title, html_text, src, base_dir=src.parent)
