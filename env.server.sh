#!/usr/bin/env bash

# 用法:
#   source ./env.local.sh
# 直接执行脚本不会把 export 留在当前 shell 里，所以这里强制提示使用 source。
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  echo "请用 'source ./env.local.sh' 加载环境变量。"
  exit 1
fi
export MODEL_NAME="${MODEL_NAME:-<your-model-name-here>}"
export OPENAI_API_KEY="${OPENAI_API_KEY:-<your-api-key-here>}"
export OPENAI_BASE_URL="${OPENAI_BASE_URL:-<your-api-base-url-here>}"

export MYSQL_HOST="${MYSQL_HOST:-127.0.0.1}"
export MYSQL_PORT="${MYSQL_PORT:-3306}"
export MYSQL_USER="${MYSQL_USER:-chat_app}"
export MYSQL_PASSWORD="${MYSQL_PASSWORD:-chat123456}"
export MYSQL_DATABASE="${MYSQL_DATABASE:-ai_chat_server}"
export MYSQL_CHARSET="${MYSQL_CHARSET:-utf8mb4}"
export MYSQL_POOL_SIZE="${MYSQL_POOL_SIZE:-8}"
export MYSQL_CONNECT_TIMEOUT="${MYSQL_CONNECT_TIMEOUT:-3}"
export DB_WORKER_THREADS="${DB_WORKER_THREADS:-4}"

if [[ "${OPENAI_API_KEY}" == "sk-xxxxxxxxx" ]]; then
  echo "[env] OPENAI_API_KEY=<placeholder>"
else
  echo "[env] OPENAI_API_KEY=<set>"
fi
echo "[env] OPENAI_BASE_URL=${OPENAI_BASE_URL}"
echo "[env] MYSQL=${MYSQL_USER}@${MYSQL_HOST}:${MYSQL_PORT}/${MYSQL_DATABASE}"
if [[ -z "${MYSQL_PASSWORD}" ]]; then
  echo "[env] MYSQL_PASSWORD=<empty>"
else
  echo "[env] MYSQL_PASSWORD=<hidden>"
fi
