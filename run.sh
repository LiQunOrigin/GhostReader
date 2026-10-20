#!/bin/bash
# 启动 GhostReader。首次运行会自动创建 .venv 并安装依赖。
#   ./run.sh                打开上次阅读的书
#   ./run.sh book.epub      直接打开指定书籍
#   GHOSTREADER_PYTHON=...  指定已有解释器（跳过自动安装）
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -n "${GHOSTREADER_PYTHON:-}" ]; then
  exec "$GHOSTREADER_PYTHON" "$ROOT/main.py" "$@"
fi

VENV="$ROOT/.venv"
if [ ! -x "$VENV/bin/python" ]; then
  echo "首次运行：创建虚拟环境并安装依赖（约 1-2 分钟）…"
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install --quiet --upgrade pip
  "$VENV/bin/pip" install --quiet -r "$ROOT/requirements.txt"
fi

exec "$VENV/bin/python" "$ROOT/main.py" "$@"
