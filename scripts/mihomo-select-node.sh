#!/usr/bin/env bash
# 等待 mihomo API 就绪后，将指定代理组切换到指定节点。
#
# 用法：
#   sudo bash scripts/mihomo-select-node.sh <组名> <节点名> [API地址] [secret]
#
# 常用于 systemd ExecStartPost（服务启动后自动选固定节点）：
#   ExecStartPost=-/usr/local/bin/mihomo-select-node.sh PROXY 美国01
#
# 默认从 /etc/mihomo/config.yaml 读取 external-controller 与 secret，
# 无需手工维护密钥。节点临时故障时脚本最多重试 30 次（约 60 秒），
# 失败后非零退出；配合 ExecStartPost 的 "-" 前缀不会导致服务失败。
set -euo pipefail

GROUP="${1:-${MIHOMO_GROUP:-PROXY}}"
NODE="${2:-${MIHOMO_NODE:-}}"
API_BASE="${3:-${MIHOMO_API:-}}"
SECRET="${4:-${MIHOMO_SECRET:-}}"
CONFIG_FILE="${MIHOMO_CONFIG:-/etc/mihomo/config.yaml}"
MAX_TRIES=30
RETRY_SEC=2

if [ -z "${NODE}" ]; then
    echo "usage: $0 <组名> <节点名> [API地址] [secret]" >&2
    echo "       例如: $0 PROXY 美国01" >&2
    exit 2
fi

# 从配置文件提取 external-controller 和 secret
if [ -z "${API_BASE}" ] && [ -r "${CONFIG_FILE}" ]; then
    API_BASE="$(grep -E '^\s*external-controller' "${CONFIG_FILE}" \
        | head -1 | sed -E 's/.*"([^"]+)".*/\1/')"
fi
if [ -z "${SECRET}" ] && [ -r "${CONFIG_FILE}" ]; then
    SECRET="$(grep -E '^\s*secret' "${CONFIG_FILE}" \
        | head -1 | sed -E 's/.*"([^"]+)".*/\1/')"
fi
API_BASE="${API_BASE:-http://127.0.0.1:9090}"

auth_args=()
if [ -n "${SECRET}" ]; then
    auth_args=(-H "Authorization: Bearer ${SECRET}")
fi

payload="{\"name\":\"${NODE}\"}"
for _ in $(seq 1 "${MAX_TRIES}"); do
    if curl -sf -X PUT "${auth_args[@]}" \
        -H "Content-Type: application/json" \
        -d "${payload}" \
        "${API_BASE%/}/proxies/${GROUP}" >/dev/null; then
        echo "[OK] 已切换 ${GROUP} -> ${NODE}" >&2
        exit 0
    fi
    sleep "${RETRY_SEC}"
done

echo "[错误] 切换 ${GROUP} -> ${NODE} 失败（API 未就绪或节点不存在）" >&2
exit 1
