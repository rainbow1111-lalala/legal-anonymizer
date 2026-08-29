#!/bin/bash
# 兼容旧入口：统一交给经过验证的一键安装器。
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec bash "$SCRIPT_DIR/setup.sh"
