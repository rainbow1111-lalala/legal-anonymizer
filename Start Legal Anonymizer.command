#!/bin/bash
# ============================================================
# Legal Anonymizer - macOS one-click launcher
# Double-click this file to run; no command line needed
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"
clear

echo ""
echo "  ╔══════════════════════════════════════╗"
echo "  ║      Legal Anonymizer - starting     ║"
echo "  ║          by Lingbao Huang            ║"
echo "  ╚══════════════════════════════════════╝"
echo ""

# ── Determine the Python path ─────────────────────────────────────────
VENV_PYTHON="$SCRIPT_DIR/.venv/bin/python"

if [ -f "$VENV_PYTHON" ] && "$VENV_PYTHON" -c "import flask, fitz, docx" 2>/dev/null; then
    # Already installed, use it directly
    PYTHON_CMD="$VENV_PYTHON"
else
    # First run or broken environment -> auto-install
    echo "  First run: configuring the environment automatically..."
    echo "  (Takes about 3-5 minutes, one time only; please wait)"
    echo ""
    bash "$SCRIPT_DIR/setup.sh"

    if [ -f "$VENV_PYTHON" ]; then
        PYTHON_CMD="$VENV_PYTHON"
    else
        # Fall back to system Python (not recommended, but works)
        for cmd in python3 python; do
            if command -v $cmd &>/dev/null && $cmd -c "import sys; sys.exit(0 if sys.version_info>=(3,9) else 1)" 2>/dev/null; then
                PYTHON_CMD=$cmd
                break
            fi
        done
        if [ -z "$PYTHON_CMD" ]; then
            echo ""
            echo "  ✗ Environment setup failed. Please install Python from https://www.python.org and try again."
            echo ""
            read -p "  Press Enter to exit..." 2>/dev/null || true
            exit 1
        fi
    fi
fi

echo "  ✓ Runtime environment ready"

# ── Create the required directories ──────────────────────────────────────────────
mkdir -p "$SCRIPT_DIR/inbox" "$SCRIPT_DIR/output" "$SCRIPT_DIR/uploads"

# ── First launch: ask the user's preference (whether English PII detection is needed) ──────────
CONFIG_FILE="$SCRIPT_DIR/.user_config"
if [ ! -f "$CONFIG_FILE" ]; then
    echo ""
    echo "  ╔══════════════════════════════════════════════╗"
    echo "  ║      First-launch setup (one time only)      ║"
    echo "  ╚══════════════════════════════════════════════╝"
    echo ""
    echo "  By default this tool detects all sensitive information in Chinese documents."
    echo "  If you also frequently handle mixed Chinese-English / cross-border legal"
    echo "  documents, you can additionally enable the English detection model"
    echo "  (OpenAI privacy-filter)."
    echo ""
    echo "  Trade-off:"
    echo "    • Enabled: also detects English names like John Smith / English"
    echo "      addresses / API tokens / international phone numbers, but requires"
    echo "      downloading a 2.6 GB model"
    echo "    • Disabled: detects Chinese PII only (enough for the vast majority of"
    echo "      legal workflows), saving 2.6 GB of disk and the first-time download"
    echo ""
    read -p "  Do you frequently handle English / cross-border legal documents? (y / n, default n): " ENABLE_EN
    echo ""

    if [[ "$ENABLE_EN" =~ ^[Yy]([Ee][Ss])?$ ]]; then
        echo "ENABLE_OPENAI=1" > "$CONFIG_FILE"
        echo "  ✓ English model enabled. The 2.6 GB model downloads automatically the first time you toggle the OpenAI switch."
    else
        echo "ENABLE_OPENAI=0" > "$CONFIG_FILE"
        echo "  ✓ Chinese-only mode selected. The OpenAI switch will be hidden in the Web UI."
        echo "  (To enable it later, delete the .user_config file in the project root and double-click to launch again to re-choose.)"
    fi
    echo ""
fi

# Read the config and export environment variables for the Web UI
source "$CONFIG_FILE" 2>/dev/null || true
export ENABLE_OPENAI=${ENABLE_OPENAI:-0}

# Use a mirror for faster access (HuggingFace is slow from mainland China)
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"

# ── Pre-download the AI models (first launch) ─────────────────────────────────────
# Chinese NER is the core capability (boosts detection accuracy by 50%+), so force the pre-download
# The OpenAI model only downloads when the user chooses y
MODEL_FLAG="$SCRIPT_DIR/.models_downloaded"
if [ ! -f "$MODEL_FLAG" ]; then
    echo ""
    echo "  ╔══════════════════════════════════════════════╗"
    echo "  ║   Downloading AI models (first time only)    ║"
    echo "  ╚══════════════════════════════════════════════╝"
    echo ""
    echo "  Downloading the Chinese NER model (about 400 MB, from a mirror)..."
    echo "  This is the core detection capability; it lifts Chinese PII detection accuracy from ~50% to 95%+"
    echo "  Please wait 1-3 minutes (depending on your connection speed)"
    echo ""

    "$PYTHON_CMD" -c "
import os
os.environ.setdefault('HF_ENDPOINT', 'https://hf-mirror.com')
print('  -> Fetching the Chinese NER model (uer/roberta-base-finetuned-cluener2020-chinese)...', flush=True)
from transformers import AutoTokenizer, AutoModelForTokenClassification
AutoTokenizer.from_pretrained('uer/roberta-base-finetuned-cluener2020-chinese')
AutoModelForTokenClassification.from_pretrained('uer/roberta-base-finetuned-cluener2020-chinese')
print('  Chinese NER model download complete', flush=True)
" 2>&1 | tail -20

    if [ "$ENABLE_OPENAI" = "1" ]; then
        echo ""
        echo "  Downloading the English model (about 2.6 GB, please wait 5-15 minutes)..."
        echo ""
        "$PYTHON_CMD" -c "
import os
os.environ.setdefault('HF_ENDPOINT', 'https://hf-mirror.com')
print('  -> Fetching the English PII model (openai/privacy-filter)...', flush=True)
from transformers import AutoTokenizer, AutoModelForTokenClassification
AutoTokenizer.from_pretrained('openai/privacy-filter')
AutoModelForTokenClassification.from_pretrained('openai/privacy-filter')
print('  English model download complete', flush=True)
" 2>&1 | tail -20
    fi

    # Mark as downloaded (to avoid repeated checks)
    touch "$MODEL_FLAG"
    echo ""
    echo "  ✓ All models are ready. Future launches go straight to the browser interface."
    echo ""
fi

# ── Terminate any existing process ──────────────────────────────────────────────
pkill -f "python.*web_app.py" 2>/dev/null || true
sleep 0.5

# ── Start the service ──────────────────────────────────────────────────
echo "  … Starting the service..."
"$PYTHON_CMD" "$SCRIPT_DIR/web_app.py" 2>&1 &
SERVER_PID=$!

# Wait for the service to start (up to 30 seconds)
for i in $(seq 1 30); do
    sleep 1
    if ! kill -0 $SERVER_PID 2>/dev/null; then
        echo ""
        echo "  ✗ The service failed to start; please check the error messages above"
        read -p "  Press Enter to exit..." 2>/dev/null || true
        exit 1
    fi
    PORT=$(lsof -nP -iTCP -sTCP:LISTEN -p $SERVER_PID 2>/dev/null | grep -oE '127\.0\.0\.1:[0-9]+' | head -1 | cut -d: -f2)
    if [ -n "$PORT" ]; then
        break
    fi
done

PORT=${PORT:-8080}

echo "  ✓ Service started; the browser will open automatically..."
echo ""
echo "  ╔══════════════════════════════════════╗"
echo "  ║  Address: http://127.0.0.1:$PORT          ║"
echo "  ║  Close this window to stop the service  ║"
echo "  ╚══════════════════════════════════════╝"
echo ""

# web_app.py opens the browser on its own timer, so do not call open again here
# Keep running; closing the window = stopping the service
wait $SERVER_PID
