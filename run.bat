@echo off
chcp 65001 >nul 2>&1
REM ============================================================
REM Video Censor — 一键运行脚本 (Windows)
REM 自动检查依赖 → 激活虚拟环境 → 运行脱敏工具
REM ============================================================

setlocal enabledelayedexpansion

set "SCRIPT_DIR=%~dp0"
set "VENV_DIR=%SCRIPT_DIR%.venv"
set "REQUIREMENTS=%SCRIPT_DIR%requirements.txt"

echo 🔒 Video Censor — 录屏视频敏感信息自动脱敏
echo ================================================

REM ── 检查 ffmpeg ──
where ffmpeg >nul 2>&1
if errorlevel 1 (
    echo ❌ 未找到 ffmpeg，请先安装:
    echo    方法1: winget install Gyan.FFmpeg
    echo    方法2: choco install ffmpeg
    echo    方法3: 从 https://ffmpeg.org/download.html 下载并添加到 PATH
    exit /b 1
)

REM ── 检查 tesseract ──
where tesseract >nul 2>&1
if errorlevel 1 (
    echo ❌ 未找到 tesseract，请先安装:
    echo    方法1: winget install UB-Mannheim.TesseractOCR
    echo    方法2: choco install tesseract
    echo    方法3: 从 https://github.com/UB-Mannheim/tesseract/wiki 下载安装
    echo    安装后请确保 tesseract 所在目录已添加到系统 PATH
    exit /b 1
)

REM ── 检查中文语言包 ──
tesseract --list-langs 2>&1 | findstr /c:"chi_sim" >nul
if errorlevel 1 (
    echo ⚠️  未找到中文语言包 chi_sim
    echo    请从 https://github.com/tesseract-ocr/tessdata 下载 chi_sim.traineddata
    echo    放到 Tesseract 安装目录的 tessdata 文件夹中
)

REM ── 查找 Python ──
set "PYTHON="
where python >nul 2>&1
if not errorlevel 1 (
    set "PYTHON=python"
) else (
    where python3 >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON=python3"
    )
)
if "%PYTHON%"=="" (
    echo ❌ 未找到 Python，请先安装 Python 3.10+
    echo    下载: https://www.python.org/downloads/
    echo    安装时请勾选 "Add Python to PATH"
    exit /b 1
)

REM ── 创建虚拟环境 ──
if not exist "%VENV_DIR%\" (
    echo 📦 创建 Python 虚拟环境...
    %PYTHON% -m venv "%VENV_DIR%"
)

REM ── 激活虚拟环境 ──
call "%VENV_DIR%\Scripts\activate.bat"

REM ── 安装依赖 ──
if exist "%REQUIREMENTS%" (
    pip install -q -r "%REQUIREMENTS%"
)

echo.

REM ── 如果没有传入参数，交互式提示输入视频路径 ──
if "%~1"=="" (
    echo 请输入视频文件路径（可以直接把视频文件拖拽到此窗口）:
    set /p "VIDEO_PATH=>"
    REM 去掉拖拽时可能带的引号
    set "VIDEO_PATH=!VIDEO_PATH:"=!"
    if "!VIDEO_PATH!"=="" (
        echo ❌ 未指定视频文件
        pause
        exit /b 1
    )
    python "%SCRIPT_DIR%video_censor.py" "!VIDEO_PATH!"
) else (
    python "%SCRIPT_DIR%video_censor.py" %*
)

pause
