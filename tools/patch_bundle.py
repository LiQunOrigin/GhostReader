#!/usr/bin/env python3
"""给 PyInstaller 产出的 .app 补上 EPUB 文档类型声明，并重新做 ad-hoc 签名。

PyInstaller 默认不写 CFBundleDocumentTypes，导致 Finder 双击 / `open -a ... x.epub`
会被 LaunchServices 拒绝（error -10820）。

    python tools/patch_bundle.py dist/GhostReader.app
"""

from __future__ import annotations

import plistlib
import subprocess
import sys
from pathlib import Path


def patch(app: Path) -> bool:
    info = app / "Contents" / "Info.plist"
    if not info.is_file():
        print(f"找不到 {info}")
        return False
    data = plistlib.loads(info.read_bytes())
    if not data.get("CFBundleDocumentTypes"):
        def doc_type(name, utis, exts):
            return {
                "CFBundleTypeName": name,
                "CFBundleTypeRole": "Viewer",
                "LSHandlerRank": "Alternate",
                "LSItemContentTypes": utis,
                "CFBundleTypeExtensions": exts,
            }

        data["CFBundleDocumentTypes"] = [
            doc_type("EPUB 电子书", ["org.idpf.epub-container"], ["epub"]),
            doc_type("纯文本", ["public.plain-text"], ["txt"]),
            doc_type("网页", ["public.html"], ["html", "htm", "xhtml", "zhtml"]),
            doc_type("FictionBook", ["public.xml"], ["fb2"]),
            doc_type(
                "Word 文档",
                ["org.openxmlformats.wordprocessingml.document"],
                ["docx"],
            ),
            doc_type("Kindle 电子书", ["public.data"], ["mobi", "azw3", "azw"]),
        ]
    info.write_bytes(plistlib.dumps(data))
    print("已写入 CFBundleDocumentTypes")

    # 改过 Info.plist 之后原签名失效，重新 ad-hoc 签名
    for args in (
        ["codesign", "--force", "--deep", "--sign", "-", str(app)],
    ):
        proc = subprocess.run(args, capture_output=True, text=True)
        if proc.returncode != 0:
            print("签名失败：", proc.stderr.strip()[:300])
            return False
    print("已重新签名")
    return True


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: patch_bundle.py <App.app>")
        return 2
    return 0 if patch(Path(sys.argv[1]).resolve()) else 1


if __name__ == "__main__":
    sys.exit(main())
