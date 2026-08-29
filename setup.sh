#!/bin/bash
# 法律文件脱敏工具 - macOS/Linux 环境安装
# 基础组件失败时立即停止；OCR/NER 分组安装并单独报告。

set -u
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"
LOG="$SCRIPT_DIR/.setup.log"
MIN_PY_MAJOR=3
MIN_PY_MINOR=10

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
ok()   { echo -e "${GREEN}  ✓ $*${NC}"; }
info() { echo -e "${YELLOW}  … $*${NC}"; }
warn() { echo -e "${YELLOW}  ! $*${NC}"; }
err()  { echo -e "${RED}  ✗ $*${NC}"; }

: > "$LOG"
{
    echo "setup started: $(date '+%Y-%m-%d %H:%M:%S')"
    echo "platform: $(uname -s) $(uname -m)"
} >> "$LOG"

echo ""
echo "  ╭────────────────────────────────────╮"
echo "  │   法律文件脱敏工具 - 环境自动安装    │"
echo "  ╰────────────────────────────────────╯"
echo ""

python_is_compatible() {
    "$1" -c "import sys; sys.exit(0 if sys.version_info >= ($MIN_PY_MAJOR,$MIN_PY_MINOR) else 1)" \
        >/dev/null 2>&1
}

core_is_ready() {
    "$1" -c "import flask, fitz, docx, PIL, reportlab" >/dev/null 2>&1
}

ocr_is_ready() {
    "$1" -c "import rapidocr, onnxruntime" >/dev/null 2>&1
}

ai_is_ready() {
    "$1" -c "import torch, transformers" >/dev/null 2>&1
}

backup_venv() {
    if [ -d "$VENV_DIR" ]; then
        local backup="$SCRIPT_DIR/.venv.incompatible.$(date '+%Y%m%d-%H%M%S')"
        info "旧运行环境不兼容，正在备份为 $(basename "$backup")"
        if ! mv "$VENV_DIR" "$backup" >> "$LOG" 2>&1; then
            err "无法备份旧环境，请关闭正在运行的工具后重试"
            return 1
        fi
    fi
}

# 已有环境版本合格时直接复用，并继续补装缺失的 OCR/NER 组件。
REUSE_VENV=0
PYTHON=""
if [ -x "$VENV_DIR/bin/python" ]; then
    if python_is_compatible "$VENV_DIR/bin/python"; then
        REUSE_VENV=1
        PYTHON="$VENV_DIR/bin/python"
        if core_is_ready "$PYTHON" && ocr_is_ready "$PYTHON" && ai_is_ready "$PYTHON"; then
            ok "全部环境已就绪：$($PYTHON --version 2>&1)"
            exit 0
        fi
        info "复用现有环境并补装缺失组件：$($PYTHON --version 2>&1)"
    else
        backup_venv || exit 1
    fi
fi

# 查找 Python 3.10+。不再使用 macOS 命令行工具自带的 Python 3.9。
if [ "$REUSE_VENV" -eq 0 ]; then
    for candidate in python3.12 python3.11 python3.10 python3; do
        if command -v "$candidate" >/dev/null 2>&1 && python_is_compatible "$candidate"; then
            PYTHON="$(command -v "$candidate")"
            break
        fi
    done
fi

UV_BIN=""
find_uv() {
    if command -v uv >/dev/null 2>&1; then
        UV_BIN="$(command -v uv)"
    elif [ -x "$HOME/.local/bin/uv" ]; then
        UV_BIN="$HOME/.local/bin/uv"
    elif [ -x "$HOME/.cargo/bin/uv" ]; then
        UV_BIN="$HOME/.cargo/bin/uv"
    fi
}

if [ "$REUSE_VENV" -eq 0 ] && [ -z "$PYTHON" ]; then
    info "未找到 Python 3.10+，将自动安装独立 Python 3.11"
    find_uv
    if [ -z "$UV_BIN" ]; then
        info "正在安装 uv（无需管理员权限）"
        if ! curl -LsSf https://astral.sh/uv/install.sh 2>> "$LOG" | sh -s -- --no-modify-path >> "$LOG" 2>&1; then
            err "uv 安装失败，可能是网络无法访问安装源"
            err "请手动安装 Python 3.11 后重试，详情见 .setup.log"
            exit 1
        fi
        find_uv
    fi
    if [ -z "$UV_BIN" ]; then
        err "uv 已下载但未找到可执行文件"
        exit 1
    fi
    if ! "$UV_BIN" python install 3.11 >> "$LOG" 2>&1; then
        err "Python 3.11 下载失败，请检查网络或查看 .setup.log"
        exit 1
    fi
    PYTHON="$("$UV_BIN" python find 3.11 2>> "$LOG")"
fi

if [ -z "$PYTHON" ] || ! python_is_compatible "$PYTHON"; then
    err "未能获取 Python 3.10+"
    exit 1
fi
ok "使用 $($PYTHON --version 2>&1)"

if [ "$REUSE_VENV" -eq 0 ]; then
    info "创建独立运行环境"
    if ! "$PYTHON" -m venv "$VENV_DIR" >> "$LOG" 2>&1; then
        err "虚拟环境创建失败，详情见 .setup.log"
        exit 1
    fi
fi
VENV_PYTHON="$VENV_DIR/bin/python"

info "更新安装工具"
if ! "$VENV_PYTHON" -m pip install --upgrade pip setuptools wheel >> "$LOG" 2>&1; then
    err "pip 更新失败，详情见 .setup.log"
    exit 1
fi

echo ""
info "1/3 安装核心组件（网页、PDF、Word）"
if ! "$VENV_PYTHON" -m pip install -r "$SCRIPT_DIR/requirements-core.txt" >> "$LOG" 2>&1; then
    err "核心组件安装失败，工具不会强行启动"
    err "请查看 .setup.log 中最后的 ERROR"
    exit 1
fi
if ! core_is_ready "$VENV_PYTHON"; then
    err "核心组件验证失败，详情见 .setup.log"
    exit 1
fi
ok "核心组件已就绪"

OCR_READY=0
info "2/3 安装 RapidOCR（扫描 PDF/图片）"
if "$VENV_PYTHON" -m pip install -r "$SCRIPT_DIR/requirements-ocr.txt" >> "$LOG" 2>&1 \
   && ocr_is_ready "$VENV_PYTHON"; then
    OCR_READY=1
    ok "RapidOCR 已就绪"
else
    warn "RapidOCR 安装失败；Word/文字 PDF 仍可使用，扫描件 OCR 暂不可用"
    warn "具体原因见 .setup.log"
fi

AI_READY=0
info "3/3 安装中文 NER 运行时"
if "$VENV_PYTHON" -m pip install -r "$SCRIPT_DIR/requirements-ai.txt" >> "$LOG" 2>&1 \
   && ai_is_ready "$VENV_PYTHON"; then
    AI_READY=1
    ok "中文 NER 运行时已就绪"
else
    warn "NER 运行时安装失败；工具仍可使用规则识别"
    warn "具体原因见 .setup.log"
fi

mkdir -p "$SCRIPT_DIR/inbox" "$SCRIPT_DIR/output" "$SCRIPT_DIR/uploads"
cat > "$SCRIPT_DIR/.setup_status" <<EOF
PYTHON_VERSION=$($VENV_PYTHON -c 'import platform; print(platform.python_version())')
CORE_READY=1
OCR_READY=$OCR_READY
AI_READY=$AI_READY
EOF

echo ""
ok "基础环境安装成功"
if [ "$OCR_READY" -eq 0 ] || [ "$AI_READY" -eq 0 ]; then
    warn "部分高级功能未安装，但不再影响网页工具启动"
fi
echo ""
exit 0
