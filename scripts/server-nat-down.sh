#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: $0 <wan-interface> <vpn-cidr>" >&2
  exit 2
fi

WAN_IFACE="$1"
VPN_CIDR="$2"

iptables -D FORWARD -s "$VPN_CIDR" -j ACCEPT 2>/dev/null || true
iptables -D FORWARD -d "$VPN_CIDR" -m state --state RELATED,ESTABLISHED -j ACCEPT 2>/dev/null || true
iptables -t nat -D POSTROUTING -s "$VPN_CIDR" -o "$WAN_IFACE" -j MASQUERADE 2>/dev/null || true

