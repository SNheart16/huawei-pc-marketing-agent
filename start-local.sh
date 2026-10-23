#!/usr/bin/env bash
# 本地联调启动脚本：配置 DeepSeek 模型服务后启动 app.py
# 用法： ./start-local.sh <DeepSeek API Key> [端口]
# 密钥申请：https://platform.deepseek.com/api_keys
# 注意：密钥只通过环境变量传入，请勿把真实密钥写进本文件或提交到仓库。
set -euo pipefail

KEY="${1:-${LLM_API_KEY:-}}"
PORT="${2:-7860}"

if [[ -z "$KEY" ]]; then
  echo "用法: ./start-local.sh <DeepSeek API Key> [端口]"
  echo "密钥申请: https://platform.deepseek.com/api_keys"
  exit 1
fi

export USE_MOCK=false
export LLM_API_KEY="$KEY"
export LLM_BASE_URL="https://api.deepseek.com/v1"
export LLM_MODEL="deepseek-chat"
export LLM_API_TYPE=chat_completions

echo "启动 华为 PC 推广智能体（端口 $PORT，模型 deepseek-chat）..."
exec python3 app.py --port "$PORT"
