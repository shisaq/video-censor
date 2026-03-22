#!/bin/bash
# ============================================================
# Video Censor — 一键运行脚本
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

# ── 检查 ffmpeg ──
if ! command -v ffmpeg &> /dev/null; then
    echo -e "${RED}❌ 未找到 ffmpeg，请先安装: brew install ffmpeg${NC}"
    exit 1
fi

# ── 检查 tesseract ──
if ! command -v tesseract &> /dev/null; then
    echo -e "${RED}❌ 未找到 tesseract，请先安装: brew install tesseract${NC}"
    exit 1
fi

# ── 检查中文语言包 ──
if ! tesseract --list-langs 2>&1 | grep -q "chi_sim"; then
    echo -e "${YELLOW}⚠️  未找到中文语言包，正在安装...${NC}"
    brew install tesseract-lang
fi

# ── 创建虚拟环境 ──
if [ ! -d "$VENV_DIR" ]; then
    echo -e "${YELLOW}📦 创建 Python 虚拟环境...${NC}"
    python3 -m venv "$VENV_DIR"
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
