#!/bin/bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

export ENABLE_OPENAI=0
export LEGAL_ANONYMIZER_LLM=0
export LEGAL_ANONYMIZER_CN_LLM=0
export LEGAL_ANONYMIZER_OLLAMA=0
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1

echo "启动安全模式：不启用英文模型 / 中文 NER 模型 / Ollama"
echo "服务只监听 127.0.0.1，本机浏览器访问。"
echo

"$SCRIPT_DIR/.venv/bin/python" "$SCRIPT_DIR/web_app.py"
