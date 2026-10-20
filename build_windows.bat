@echo off
rem GhostReader - 打包成 Windows 可执行程序（dist\GhostReader\GhostReader.exe）
chcp 65001 >nul
cd /d "%~dp0"

echo === 准备环境 ===
if not exist ".venv\Scripts\python.exe" (
  python -m venv .venv
  if errorlevel 1 (
    echo 未找到 python，请先安装 Python 3.9+ 并勾选 "Add to PATH"
    pause
    exit /b 1
  )
)
".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt pyinstaller

echo === 生成图标 ===
".venv\Scripts\python.exe" tools\make_icon.py

echo === 打包（约 1 分钟）===
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --windowed ^
  --name GhostReader ^
  --icon assets\icon.ico ^
  --add-data "assets;assets" ^
  --hidden-import PyQt6.QtNetwork ^
  main.py

if errorlevel 1 (
  echo 打包失败
  pause
  exit /b 1
)

echo.
echo === 完成 ===
echo 可执行文件：%cd%\dist\GhostReader\GhostReader.exe
echo 整个 dist\GhostReader 目录可以直接拷走使用。
pause
