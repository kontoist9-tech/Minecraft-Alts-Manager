#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
#  Minecraft Account Manager 2.0 — Installer for macOS / Linux
# ─────────────────────────────────────────────────────────────
set -e

CYAN='\033[0;36m'
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo ""
echo -e "${CYAN}══════════════════════════════════════════════════${NC}"
echo -e "${CYAN}  🎮 Minecraft Account Manager 2.0 — Installer  ${NC}"
echo -e "${CYAN}══════════════════════════════════════════════════${NC}"
echo ""

# Check Python 3.10+
if ! command -v python3 &>/dev/null; then
    echo -e "${RED}❌ Python 3 not found!${NC}"
    if [[ "$OSTYPE" == "darwin"* ]]; then
        echo -e "${YELLOW}👉 Install it with Homebrew:${NC}"
        echo "   brew install python"
        echo -e "${YELLOW}   or download from: https://www.python.org/downloads/${NC}"
    else
        echo -e "${YELLOW}👉 Install it with:${NC}"
        echo "   sudo apt install python3 python3-pip  (Ubuntu/Debian)"
        echo "   sudo dnf install python3 python3-pip  (Fedora)"
    fi
    exit 1
fi

PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo -e "${GREEN}✅ Python $PY_VER found${NC}"

# Check pip
if ! python3 -m pip --version &>/dev/null; then
    echo -e "${RED}❌ pip not found. Installing...${NC}"
    python3 -m ensurepip --upgrade || sudo apt install python3-pip -y || sudo dnf install python3-pip -y
fi

# macOS: check Tkinter (required for customtkinter)
if [[ "$OSTYPE" == "darwin"* ]]; then
    if ! python3 -c "import tkinter" &>/dev/null 2>&1; then
        echo -e "${YELLOW}⚠️  Tkinter not found. Installing python-tk...${NC}"
        if command -v brew &>/dev/null; then
            brew install python-tk
        else
            echo -e "${RED}❌ Please install Homebrew first: https://brew.sh${NC}"
            echo "Then run:  brew install python-tk"
            exit 1
        fi
    fi
fi

echo ""
echo -e "${CYAN}📦 Installing required packages...${NC}"
python3 -m pip install --upgrade pip --quiet
python3 -m pip install customtkinter pillow requests minecraft-launcher-lib --quiet

echo ""
echo -e "${GREEN}✅ All packages installed successfully!${NC}"
echo ""
echo -e "${CYAN}🚀 Launching Minecraft Account Manager...${NC}"
echo ""

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python3 "$SCRIPT_DIR/app.py"
