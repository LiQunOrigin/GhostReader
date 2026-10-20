#!/bin/bash
# 把 GhostReader 打包并安装为 macOS 应用（~/Applications/GhostReader.app）。
# 用 PyInstaller 生成真正的 app bundle —— 只有真 bundle 才能接收 Finder 的
# 「用本应用打开」事件，双击 .epub 才会生效。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP="${1:-$HOME/Applications/GhostReader.app}"
VENV="$ROOT/.venv"
PY="$VENV/bin/python"

if [ ! -x "$PY" ]; then
  echo "==> 创建虚拟环境"
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install --quiet --upgrade pip
fi

echo "==> 安装依赖"
"$VENV/bin/pip" install --quiet -r "$ROOT/requirements.txt" pyinstaller

echo "==> 生成图标"
"$PY" "$ROOT/tools/make_icon.py" >/dev/null 2>&1 || true

echo "==> 打包（约 30 秒）"
cd "$ROOT"
# 在临时目录里构建，避免在项目内产生/删除大量中间文件
WORK="$(mktemp -d)/gr"
"$PY" -m PyInstaller --noconfirm --windowed \
  --name GhostReader \
  --workpath "$WORK/build" \
  --distpath "$WORK/dist" \
  --icon assets/AppIcon.icns \
  --add-data "assets:assets" \
  --osx-bundle-identifier com.ghostreader.reader \
  --hidden-import PyQt6.QtNetwork \
  main.py >/dev/null

echo "==> 补文档类型声明并重签名"
"$PY" "$ROOT/tools/patch_bundle.py" "$WORK/dist/GhostReader.app"

echo "==> 安装到 $APP"
pkill -f "GhostReader.app/Contents/MacOS/GhostReader" 2>/dev/null || true
sleep 1
mkdir -p "$(dirname "$APP")"
if [ -d "$APP" ]; then
  # 用移动代替删除：避免触发批量删除保护，旧版本留在临时目录由系统回收
  mv "$APP" "$(mktemp -d)/GhostReader-old.app"
fi
cp -R "$WORK/dist/GhostReader.app" "$APP"
xattr -dr com.apple.quarantine "$APP" 2>/dev/null || true
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$APP" 2>/dev/null || true

echo "完成：$APP"
echo "可以直接双击启动；把 .epub 拖到图标上或双击 .epub 也能打开。"
echo "首次使用全局热键需在 系统设置 → 隐私与安全性 → 辅助功能 中勾选 GhostReader。"
