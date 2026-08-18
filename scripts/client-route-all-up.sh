#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 3 ]]; then
  echo "usage: $0 <server-public-ip> <original-gateway> <original-interface>" >&2
  exit 2
fi

SERVER_IP="$1"
ORIGINAL_GW="$2"
ORIGINAL_IFACE="$3"

ip route replace "$SERVER_IP"/32 via "$ORIGINAL_GW" dev "$ORIGINAL_IFACE"
ip route replace default dev u20vpn0

