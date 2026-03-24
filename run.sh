#!/bin/bash
# ============================================================
# Video Censor — 一键运行脚本 (macOS / Linux)
# 自动检查依赖 → 激活虚拟环境 → 运行脱敏工具
# ============================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"
REQUIREMENTS="$SCRIPT_DIR/requirements.txt"

# ── 颜色 ──
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}🔒 Video Censor — 录屏视频敏感信息自动脱敏${NC}"
echo "================================================"

# ── 检测平台与包管理器 ──
OS="$(uname -s)"
install_hint_ffmpeg=""
install_hint_tesseract=""
install_hint_lang=""

if [ "$OS" = "Darwin" ]; then
    install_hint_ffmpeg="brew install ffmpeg"
    install_hint_tesseract="brew install tesseract"
    install_hint_lang="brew install tesseract-lang"
elif [ "$OS" = "Linux" ]; then
    if command -v apt-get &> /dev/null; then
        install_hint_ffmpeg="sudo apt-get install ffmpeg"
        install_hint_tesseract="sudo apt-get install tesseract-ocr"
        install_hint_lang="sudo apt-get install tesseract-ocr-chi-sim"
    elif command -v dnf &> /dev/null; then
        install_hint_ffmpeg="sudo dnf install ffmpeg"
        install_hint_tesseract="sudo dnf install tesseract"
        install_hint_lang="sudo dnf install tesseract-langpack-chi_sim"
    elif command -v pacman &> /dev/null; then
        install_hint_ffmpeg="sudo pacman -S ffmpeg"
        install_hint_tesseract="sudo pacman -S tesseract"
        install_hint_lang="sudo pacman -S tesseract-data-chi_sim"
    else
        install_hint_ffmpeg="请通过系统包管理器安装 ffmpeg"
        install_hint_tesseract="请通过系统包管理器安装 tesseract"
        install_hint_lang="请通过系统包管理器安装 tesseract 中文语言包"
    fi
else
    echo -e "${RED}❌ 不支持的系统: $OS${NC}"
    echo "   Windows 用户请使用 run.bat"
    exit 1
fi

# ── 检查 ffmpeg ──
if ! command -v ffmpeg &> /dev/null; then
    echo -e "${RED}❌ 未找到 ffmpeg，请先安装: ${install_hint_ffmpeg}${NC}"
    exit 1
fi

# ── 检查 tesseract ──
if ! command -v tesseract &> /dev/null; then
    echo -e "${RED}❌ 未找到 tesseract，请先安装: ${install_hint_tesseract}${NC}"
    exit 1
fi

# ── 检查中文语言包 ──
if ! tesseract --list-langs 2>&1 | grep -q "chi_sim"; then
    echo -e "${YELLOW}⚠️  未找到中文语言包，请安装: ${install_hint_lang}${NC}"
fi

# ── 查找 Python ──
if command -v python3 &> /dev/null; then
    PYTHON=python3
elif command -v python &> /dev/null; then
    PYTHON=python
else
    echo -e "${RED}❌ 未找到 Python，请先安装 Python 3.10+${NC}"
    exit 1
fi

# ── 创建虚拟环境 ──
if [ ! -d "$VENV_DIR" ]; then
    echo -e "${YELLOW}📦 创建 Python 虚拟环境...${NC}"
    "$PYTHON" -m venv "$VENV_DIR"
fi

# ── 激活虚拟环境 ──
source "$VENV_DIR/bin/activate"

# ── 安装依赖 ──
if [ -f "$REQUIREMENTS" ]; then
    pip install -q -r "$REQUIREMENTS"
fi

echo ""

# ── 运行主脚本 ──
python "$SCRIPT_DIR/video_censor.py" "$@"
