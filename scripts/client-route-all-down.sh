#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: $0 <original-gateway> <original-interface>" >&2
  exit 2
fi

ORIGINAL_GW="$1"
ORIGINAL_IFACE="$2"

ip route replace default via "$ORIGINAL_GW" dev "$ORIGINAL_IFACE"

