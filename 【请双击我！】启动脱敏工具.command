#!/bin/bash
# ============================================================
# 法律文档脱敏工具 - macOS 一键启动
# 双击此文件即可运行，无需任何命令行操作
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"
clear

echo ""
echo "  ╔══════════════════════════════════════╗"
echo "  ║     法律文档脱敏工具 - 正在启动      ║"
echo "  ║        by 黄灵宝同学                 ║"
echo "  ╚══════════════════════════════════════╝"
echo ""

# ── 确定 Python 路径 ─────────────────────────────────────────
VENV_PYTHON="$SCRIPT_DIR/.venv/bin/python"

if [ -x "$VENV_PYTHON" ] \
   && "$VENV_PYTHON" -c "import sys; assert sys.version_info >= (3,10); import flask, fitz, docx, PIL, reportlab" 2>/dev/null; then
    # 已安装好，直接用
    PYTHON_CMD="$VENV_PYTHON"
else
    # 首次运行或环境损坏 → 自动安装
    echo "  首次运行，正在自动配置环境..."
    echo "  （约需 3-5 分钟，仅此一次，请耐心等待）"
    echo ""
    if ! bash "$SCRIPT_DIR/setup.sh"; then
        echo ""
        echo "  ✗ 环境安装未完成，服务不会强行启动。"
        echo "  请查看项目目录下的 .setup.log。"
        echo ""
        read -p "  按回车键退出..." 2>/dev/null || true
        exit 1
    fi
    PYTHON_CMD="$VENV_PYTHON"
fi

if ! "$PYTHON_CMD" -c "import sys; assert sys.version_info >= (3,10); import flask, fitz, docx, PIL, reportlab" 2>/dev/null; then
    echo ""
    echo "  ✗ 核心环境验证失败，请重新运行安装。"
    read -p "  按回车键退出..." 2>/dev/null || true
    exit 1
fi
echo "  ✓ 运行环境就绪（$($PYTHON_CMD --version 2>&1)）"

# ── 创建必要目录 ──────────────────────────────────────────────
mkdir -p "$SCRIPT_DIR/inbox" "$SCRIPT_DIR/output" "$SCRIPT_DIR/uploads"

# ── 首次启动：询问用户偏好（是否需要英文 PII 检测能力）──────────
CONFIG_FILE="$SCRIPT_DIR/.user_config"
if [ ! -f "$CONFIG_FILE" ]; then
    echo ""
    echo "  ╔══════════════════════════════════════════════╗"
    echo "  ║         首次启动配置（仅一次）               ║"
    echo "  ╚══════════════════════════════════════════════╝"
    echo ""
    echo "  这个工具默认能识别中文文档里的所有敏感信息。"
    echo "  如果您也经常处理中英混合 / 涉外法律文书，可以"
    echo "  额外启用英文识别模型（OpenAI privacy-filter）。"
    echo ""
    echo "  权衡："
    echo "    • 启用：多识别 John Smith 等英文人名 / 英文地址 /"
    echo "      API token / 国际电话，但要下载 2.6 GB 模型"
    echo "    • 不启用：只识别中文 PII（绝大多数律师场景已够），"
    echo "      节省 2.6 GB 磁盘和首次下载时间"
    echo ""
    read -p "  您是否经常处理英文/涉外法律文书？(y / n，默认 n)：" ENABLE_EN
    echo ""

    if [[ "$ENABLE_EN" =~ ^[Yy]([Ee][Ss])?$ ]]; then
        echo "ENABLE_OPENAI=1" > "$CONFIG_FILE"
        echo "  ✓ 已启用英文模型。首次勾选 OpenAI 开关时会自动下载 2.6 GB 模型。"
    else
        echo "ENABLE_OPENAI=0" > "$CONFIG_FILE"
        echo "  ✓ 已选择仅中文模式。Web UI 中将隐藏 OpenAI 开关。"
        echo "  （以后想启用，删除项目根目录下 .user_config 文件，重新双击启动即可重新选择）"
    fi
    echo ""
fi

# 读取配置，导出环境变量给 Web UI 使用
source "$CONFIG_FILE" 2>/dev/null || true
export ENABLE_OPENAI=${ENABLE_OPENAI:-0}

# 国内镜像加速（HuggingFace 国内访问慢）
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"

# ── 预下载 AI 模型（首次启动）─────────────────────────────────────
# 中文 NER 是核心能力（提升 50%+ 检测准确度），强制预下载
# OpenAI 模型仅在用户选择 y 时下载
CN_MODEL_FLAG="$SCRIPT_DIR/.cn_model_ready"
EN_MODEL_FLAG="$SCRIPT_DIR/.en_model_ready"
if "$PYTHON_CMD" -c "import torch, transformers" >/dev/null 2>&1 \
   && { [ ! -f "$CN_MODEL_FLAG" ] || { [ "$ENABLE_OPENAI" = "1" ] && [ ! -f "$EN_MODEL_FLAG" ]; }; }; then
    echo ""
    echo "  ╔══════════════════════════════════════════════╗"
    echo "  ║       下载 AI 模型（首次仅一次）             ║"
    echo "  ╚══════════════════════════════════════════════╝"
    echo ""
    echo "  正在下载中文 NER 模型（约 400 MB，国内镜像）..."
    echo "  这是核心检测能力，可让中文敏感信息识别准确率从 ~50% 提升到 95%+"
    echo "  请耐心等待 1-3 分钟（取决于您的网速）"
    echo ""

    if "$PYTHON_CMD" -c "
import os
os.environ.setdefault('HF_ENDPOINT', 'https://hf-mirror.com')
print('  → 拉取中文 NER 模型 (uer/roberta-base-finetuned-cluener2020-chinese)...', flush=True)
from transformers import AutoTokenizer, AutoModelForTokenClassification
AutoTokenizer.from_pretrained('uer/roberta-base-finetuned-cluener2020-chinese')
AutoModelForTokenClassification.from_pretrained('uer/roberta-base-finetuned-cluener2020-chinese')
print('  ✓ 中文 NER 模型下载完成', flush=True)
"; then
        touch "$CN_MODEL_FLAG"
    else
        echo "  ! 中文 NER 模型下载失败，本次将使用规则识别。"
    fi

    if [ "$ENABLE_OPENAI" = "1" ]; then
        echo ""
        echo "  正在下载英文模型（约 2.6 GB，请耐心等待 5-15 分钟）..."
        echo ""
        if "$PYTHON_CMD" -c "
import os
os.environ.setdefault('HF_ENDPOINT', 'https://hf-mirror.com')
print('  → 拉取英文 PII 模型 (openai/privacy-filter)...', flush=True)
from transformers import AutoTokenizer, AutoModelForTokenClassification
AutoTokenizer.from_pretrained('openai/privacy-filter')
AutoModelForTokenClassification.from_pretrained('openai/privacy-filter')
print('  ✓ 英文模型下载完成', flush=True)
"; then
            touch "$EN_MODEL_FLAG"
        else
            echo "  ! 英文模型下载失败，英文隐私识别暂不可用。"
        fi
    fi
    echo ""
    echo "  模型检查完成。"
    echo ""
elif ! "$PYTHON_CMD" -c "import torch, transformers" >/dev/null 2>&1; then
    echo ""
    echo "  ! NER 运行时未安装，本次启动使用规则识别。"
    echo "  ! 可重新运行 setup.sh 补充安装。"
    echo ""
fi

# ── 结束已有进程 ──────────────────────────────────────────────
pkill -f "python.*web_app.py" 2>/dev/null || true
sleep 0.5

# ── 启动服务 ──────────────────────────────────────────────────
echo "  … 启动服务中..."
"$PYTHON_CMD" "$SCRIPT_DIR/web_app.py" 2>&1 &
SERVER_PID=$!

# 等待服务启动（最多 30 秒）
for i in $(seq 1 30); do
    sleep 1
    if ! kill -0 $SERVER_PID 2>/dev/null; then
        echo ""
        echo "  ✗ 服务启动失败，请查看上方错误信息"
        read -p "  按回车键退出..." 2>/dev/null || true
        exit 1
    fi
    PORT=$(lsof -nP -iTCP -sTCP:LISTEN -p $SERVER_PID 2>/dev/null | grep -oE '127\.0\.0\.1:[0-9]+' | head -1 | cut -d: -f2)
    if [ -n "$PORT" ]; then
        break
    fi
done

PORT=${PORT:-8080}

echo "  ✓ 服务已启动，浏览器即将自动打开..."
echo ""
echo "  ╔══════════════════════════════════════╗"
echo "  ║  地址: http://127.0.0.1:$PORT              ║"
echo "  ║  关闭此窗口即可停止服务              ║"
echo "  ╚══════════════════════════════════════╝"
echo ""

# 浏览器由 web_app.py 内部定时打开，此处不重复 open
# 保持运行，关闭窗口 = 停止服务
wait $SERVER_PID
