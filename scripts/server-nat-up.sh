#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: $0 <wan-interface> <vpn-cidr>" >&2
  exit 2
fi

WAN_IFACE="$1"
VPN_CIDR="$2"

sysctl -w net.ipv4.ip_forward=1
iptables -C FORWARD -s "$VPN_CIDR" -j ACCEPT 2>/dev/null || iptables -A FORWARD -s "$VPN_CIDR" -j ACCEPT
iptables -C FORWARD -d "$VPN_CIDR" -m state --state RELATED,ESTABLISHED -j ACCEPT 2>/dev/null || iptables -A FORWARD -d "$VPN_CIDR" -m state --state RELATED,ESTABLISHED -j ACCEPT
iptables -t nat -C POSTROUTING -s "$VPN_CIDR" -o "$WAN_IFACE" -j MASQUERADE 2>/dev/null || iptables -t nat -A POSTROUTING -s "$VPN_CIDR" -o "$WAN_IFACE" -j MASQUERADE

