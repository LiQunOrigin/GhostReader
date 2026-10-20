@echo off
rem GhostReader - Windows 开发模式启动
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo 首次运行：创建虚拟环境并安装依赖...
  python -m venv .venv
  if errorlevel 1 (
    echo 未找到 python，请先安装 Python 3.9+ 并勾选 "Add to PATH"
    pause
    exit /b 1
  )
  ".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
  ".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt
)

".venv\Scripts\python.exe" main.py %*
