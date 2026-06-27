#!/bin/bash
# ============================================================
# Legal Anonymizer - fully automated environment setup
# Usage: bash setup.sh  (or called automatically by the launcher; no need to run by hand)
# ============================================================
# Install strategy (chosen automatically):
#   1. If a .venv already exists -> skip and finish
#   2. If the system has Python 3.9+ -> create a venv with system Python
#   3. If uv is available -> use uv to download Python and create a venv
#   4. If Homebrew is available -> brew install python@3.11
#   5. Auto-install uv (no admin rights needed), then use uv to download Python
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"
LOG="$SCRIPT_DIR/.setup.log"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
ok()   { echo -e "${GREEN}  ✓ $*${NC}"; }
info() { echo -e "${YELLOW}  … $*${NC}"; }
err()  { echo -e "${RED}  ✗ $*${NC}"; }

echo ""
echo "  ╔══════════════════════════════════════╗"
echo "  ║  Legal Anonymizer - auto env setup   ║"
echo "  ╚══════════════════════════════════════╝"
echo ""

# ── 0. If already installed, skip ──────────────────────────────────────
if [ -f "$VENV_DIR/bin/python" ]; then
    # Verify the key dependencies are still present
    if "$VENV_DIR/bin/python" -c "import flask, fitz, docx" 2>/dev/null; then
        ok "Environment ready; skipping installation"
        echo ""
        exit 0
    fi
    info "Environment incomplete; reinstalling dependencies..."
    SKIP_VENV_CREATE=1
fi

# ── 1. Find an available Python ────────────────────────────────────────
PYTHON=""
for candidate in python3.12 python3.11 python3.10 python3.9 python3; do
    if command -v "$candidate" &>/dev/null 2>&1; then
        if "$candidate" -c "import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)" 2>/dev/null; then
            PYTHON="$candidate"
            break
        fi
    fi
done

# ── 2. No Python -> obtain it automatically ───────────────────────────────
if [ -z "$PYTHON" ]; then
    # Try uv (no admin rights needed, can download Python itself)
    UV_BIN=""
    if command -v uv &>/dev/null; then
        UV_BIN="uv"
    elif [ -f "$HOME/.local/bin/uv" ]; then
        UV_BIN="$HOME/.local/bin/uv"
    fi

    if [ -z "$UV_BIN" ]; then
        info "Python not found; installing the uv tool (about 10MB, no admin rights needed)..."
        curl -LsSf https://astral.sh/uv/install.sh | sh -s -- --no-modify-path >> "$LOG" 2>&1
        UV_BIN="$HOME/.local/bin/uv"
        if [ ! -f "$UV_BIN" ]; then
            # macOS ARM path
            UV_BIN="$HOME/.cargo/bin/uv"
        fi
    fi

    if [ -f "$UV_BIN" ]; then
        ok "uv ready"
        info "Downloading Python 3.11 (about 1-2 minutes the first time)..."
        "$UV_BIN" python install 3.11 >> "$LOG" 2>&1
        PYTHON=$("$UV_BIN" python find 3.11 2>/dev/null)
        if [ -z "$PYTHON" ]; then
            # uv-managed python path
            PYTHON=$(ls "$HOME/.local/share/uv/python/"python3.11*/bin/python3 2>/dev/null | head -1)
        fi
    fi

    # uv failed -> try Homebrew
    if [ -z "$PYTHON" ]; then
        if command -v brew &>/dev/null; then
            info "Installing Python 3.11 via Homebrew..."
            brew install python@3.11 >> "$LOG" 2>&1
            PYTHON="python3.11"
        fi
    fi

    if [ -z "$PYTHON" ]; then
        err "Could not install Python automatically. Please download and install it from https://www.python.org and try again."
        echo ""
        read -p "  Press Enter to exit..." 2>/dev/null || true
        exit 1
    fi
fi

ok "Python: $($PYTHON --version 2>&1)"

# ── 3. Create the virtual environment ───────────────────────────────────────────
if [ -z "$SKIP_VENV_CREATE" ]; then
    info "Creating the isolated runtime environment..."
    "$PYTHON" -m venv "$VENV_DIR" >> "$LOG" 2>&1
fi
PIP="$VENV_DIR/bin/pip"
ok "Runtime environment ready"

# ── 4. Install dependencies ───────────────────────────────────────────────
echo ""
info "Installing dependency packages (about 3-5 minutes the first time; please wait)..."
"$PIP" install --upgrade pip -q >> "$LOG" 2>&1

REQUIREMENTS="$SCRIPT_DIR/requirements.txt"
if [ -f "$REQUIREMENTS" ]; then
    "$PIP" install -r "$REQUIREMENTS" -q >> "$LOG" 2>&1
else
    "$PIP" install flask pymupdf python-docx pillow reportlab chardet paddleocr -q >> "$LOG" 2>&1
fi
ok "Dependencies installed"

# ── 5. Verify the installation ───────────────────────────────────────────────
echo ""
if "$VENV_DIR/bin/python" -c "import flask, fitz, docx" 2>/dev/null; then
    ok "Core components verified"
else
    err "Some dependencies were not installed successfully; see .setup.log for details"
fi

# ── 6. Make sure the directory structure exists ───────────────────────────────────────────
mkdir -p "$SCRIPT_DIR/inbox" "$SCRIPT_DIR/output" "$SCRIPT_DIR/uploads"

# ── Done ─────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}  ════════════════════════════════════════"
echo -e "    Installation complete! Starting..."
echo -e "  ════════════════════════════════════════${NC}"
echo ""
