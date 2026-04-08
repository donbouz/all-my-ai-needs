#!/bin/bash
set -euo pipefail

NEED_MANUAL=0
PROXY_HTTP="${HTTP_PROXY:-http://127.0.0.1:7897}"
PROXY_HTTPS="${HTTPS_PROXY:-http://127.0.0.1:7897}"

echo "[bird-twitter-bookmarks] 检查 Node.js..."
if ! command -v node >/dev/null 2>&1; then
  echo "[bird-twitter-bookmarks] 未检测到 node，请先安装 Node.js 20+"
  NEED_MANUAL=1
fi

echo "[bird-twitter-bookmarks] 检查 npm..."
if ! command -v npm >/dev/null 2>&1; then
  echo "[bird-twitter-bookmarks] 未检测到 npm，请先安装 npm"
  NEED_MANUAL=1
fi

echo "[bird-twitter-bookmarks] 检查 Python3..."
if ! command -v python3 >/dev/null 2>&1; then
  echo "[bird-twitter-bookmarks] 未检测到 python3，请先安装 Python3"
  NEED_MANUAL=1
fi

echo "[bird-twitter-bookmarks] 检查 sqlite3..."
if ! command -v sqlite3 >/dev/null 2>&1; then
  echo "[bird-twitter-bookmarks] 未检测到 sqlite3，请先安装 sqlite3"
  NEED_MANUAL=1
fi

echo "[bird-twitter-bookmarks] 检查 fieldtheory (ft)..."
if command -v ft >/dev/null 2>&1; then
  echo "[bird-twitter-bookmarks] ft 已安装: $(ft --version 2>/dev/null || echo unknown)"
else
  if command -v npm >/dev/null 2>&1; then
    echo "[bird-twitter-bookmarks] 尝试安装 fieldtheory"
    if HTTP_PROXY="$PROXY_HTTP" HTTPS_PROXY="$PROXY_HTTPS" npm install -g fieldtheory >/dev/null 2>&1; then
      echo "[bird-twitter-bookmarks] fieldtheory 安装完成: $(ft --version 2>/dev/null || echo unknown)"
    else
      echo "[bird-twitter-bookmarks] 自动安装失败，请手动执行："
      echo "  HTTP_PROXY=$PROXY_HTTP HTTPS_PROXY=$PROXY_HTTPS npm install -g fieldtheory"
      NEED_MANUAL=1
    fi
  else
    NEED_MANUAL=1
  fi
fi

echo "[bird-twitter-bookmarks] 代理提示：当前环境建议命令前缀"
echo "  NODE_USE_ENV_PROXY=1 HTTP_PROXY=$PROXY_HTTP HTTPS_PROXY=$PROXY_HTTPS ft <command>"
echo "  HTTP_PROXY=$PROXY_HTTP HTTPS_PROXY=$PROXY_HTTPS python3 <l2_script> classify-unknown --engine auto"

SCRIPT_PATH="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/scripts/bookmark_l2_labels.py"
if [ -f "$SCRIPT_PATH" ]; then
  if python3 "$SCRIPT_PATH" --help >/dev/null 2>&1; then
    echo "[bird-twitter-bookmarks] L2 标签脚本可用: $SCRIPT_PATH"
  else
    echo "[bird-twitter-bookmarks] L2 标签脚本执行失败，请检查 Python 运行环境"
    NEED_MANUAL=1
  fi
fi

if [ "$NEED_MANUAL" -eq 1 ]; then
  exit 2
fi
