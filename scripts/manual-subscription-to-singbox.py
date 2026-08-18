#!/usr/bin/env python3
"""将手动下载的 Clash 订阅文件转换为 sing-box 配置。

用法:
    sudo .venv/bin/python scripts/manual-subscription-to-singbox.py \
        --subscription /etc/singbox/subscription-clash.yaml \
        --output /etc/singbox/config.json \
        --secret <控制器密钥>

    也可以直接传订阅 URL（会先下载到临时文件）:

    sudo .venv/bin/python scripts/manual-subscription-to-singbox.py \
        --subscription-url "https://..." \
        --output /etc/singbox/config.json \
        --secret <控制器密钥>

说明:
    - 订阅文件是手动下载的 Clash YAML(见 README 的"手动订阅"章节)。
    - 生成的配置监听 127.0.0.1:7890 (HTTP/SOCKS 混合端口)，
      并提供 Clash 兼容 API (127.0.0.1:9090)，可供 u20vpn clash ui 使用。
    - 仅转换 anytls / vmess / vless / trojan / ss 等 sing-box 支持的协议。
"""

import argparse
import json
import re
import sys
from typing import Any, Dict, List, Optional


SUPPORTED = {"anytls", "vmess", "vless", "trojan", "shadowsocks", "ss", "hysteria2", "tuic", "wireguard"}


def parse_node_line(line: str) -> Optional[Dict[str, str]]:
    line = line.strip().lstrip("-").strip()
    if not line.startswith("{"):
        return None
    fields: Dict[str, str] = {}
    for key, value in re.findall(r'(\w[\w-]*):\s*(\[[^\]]*\]|"[^"]*"|[^,}]+)', line):
        fields[key] = value.strip().strip('"')
    return fields


def build_outbound(node: Dict[str, str]) -> Optional[Dict[str, Any]]:
    ptype = node.get("type", "").lower()
    name = node.get("name", "").strip()
    server = node.get("server", "").strip()
    port = int(node.get("port") or 0)
    if not (name and server and port):
        return None
    out: Dict[str, Any] = {"type": ptype, "tag": name, "server": server, "server_port": port}

    if ptype == "anytls":
        out["password"] = node.get("password", "")
        out["tls"] = {
            "enabled": True,
            "server_name": node.get("sni", "") or server,
            "utls": {"enabled": True, "fingerprint": node.get("client-fingerprint", "chrome")},
            "insecure": True,
        }
        alpn = node.get("alpn", "")
        if alpn:
            out["tls"]["alpn"] = [a.strip() for a in alpn.strip("[]").split(",") if a.strip()]
    elif ptype == "vmess":
        out["uuid"] = node.get("uuid", "")
        out["alter_id"] = int(node.get("alterId", "0") or 0)
        cipher = node.get("cipher", "auto")
        if cipher == "auto":
            cipher = "chacha20-poly1305"
        out["security"] = cipher
        if node.get("tls") == "true":
            out["tls"] = {"enabled": True, "server_name": node.get("servername", "") or server}
    elif ptype == "vless":
        out["uuid"] = node.get("uuid", "")
        if node.get("tls") == "true":
            out["tls"] = {"enabled": True, "server_name": node.get("servername", "") or server}
    elif ptype == "trojan":
        out["password"] = node.get("password", "")
        if node.get("sni"):
            out["tls"] = {"enabled": True, "server_name": node["sni"]}
    elif ptype in ("ss", "shadowsocks"):
        out["type"] = "shadowsocks"
        out["method"] = node.get("cipher", "")
        out["password"] = node.get("password", "")
    else:
        return None
    return out


def download_subscription(url: str, dest_path: str) -> None:
    import time
    import urllib.request

    last: Optional[Exception] = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=60) as resp:
                with open(dest_path, "wb") as fh:
                    fh.write(resp.read())
            return
        except Exception as exc:  # noqa: BLE001 - 网络错误统一重试
            last = exc
            time.sleep(2)
    raise RuntimeError(f"下载订阅失败: {last}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subscription", help="手动下载的 Clash 订阅文件路径")
    parser.add_argument("--subscription-url", help="Clash 订阅 URL；先下载到临时文件再转换")
    parser.add_argument("--output", default="/etc/singbox/config.json", help="输出 sing-box 配置路径")
    parser.add_argument("--listen", default="127.0.0.1", help="代理监听地址")
    parser.add_argument("--port", type=int, default=7890, help="HTTP/SOCKS 混合端口")
    parser.add_argument("--controller", default="127.0.0.1:9090", help="Clash 兼容 API 地址")
    parser.add_argument("--secret", default="", help="Clash 兼容 API 密钥")
    args = parser.parse_args()

    if not args.subscription and not args.subscription_url:
        parser.error("需要 --subscription 或 --subscription-url")

    subscription_path = args.subscription
    temp_path: Optional[str] = None
    try:
        if args.subscription_url:
            import os
            import tempfile

            print(f"下载订阅: {args.subscription_url}")
            fd, temp_path = tempfile.mkstemp(prefix="u20vpn-sub-", suffix=".yaml")
            download_subscription(args.subscription_url, temp_path)
            os.close(fd)
            subscription_path = temp_path

        return convert(subscription_path, args)
    finally:
        if temp_path:
            import os

            os.unlink(temp_path)


def convert(subscription_path: str, args: argparse.Namespace) -> int:
    text = open(subscription_path, encoding="utf-8", errors="replace").read()
    match = re.search(r"proxies:\n(.*?)(?:\nproxy-groups:|\Z)", text, re.S)
    if not match:
        print("error: 订阅文件中没有找到 proxies 区块", file=sys.stderr)
        return 1
    body = match.group(1)

    outbounds: List[Dict[str, Any]] = []
    for line in body.splitlines():
        node = parse_node_line(line)
        if not node or node.get("type", "").lower() not in SUPPORTED:
            continue
        out = build_outbound(node)
        if out:
            outbounds.append(out)

    if not outbounds:
        print("error: 没有转换出任何受支持的节点", file=sys.stderr)
        return 1

    tags = [o["tag"] for o in outbounds]
    config: Dict[str, Any] = {
        "log": {"level": "info"},
        "inbounds": [
            {
                "type": "mixed",
                "tag": "mixed-in",
                "listen": args.listen,
                "listen_port": args.port,
            }
        ],
        "outbounds": [
            {
                "type": "urltest",
                "tag": "auto",
                "outbounds": tags,
                "url": "https://www.gstatic.com/generate_204",
                "interval": "5m",
                "tolerance": 50,
            },
            {"type": "selector", "tag": "select", "outbounds": ["auto"] + tags},
            {"type": "direct", "tag": "direct"},
            *outbounds,
        ],
        "route": {"final": "select"},
        "experimental": {
            "clash_api": {
                "external_controller": args.controller,
                "external_ui": "",
                "secret": args.secret,
            }
        },
    }
    with open(args.output, "w", encoding="utf-8") as fh:
        json.dump(config, fh, ensure_ascii=False, indent=2)
    print(f"转换完成: {len(outbounds)} 个节点 -> {args.output}")
    print(f"代理端口: {args.listen}:{args.port}  控制器: {args.controller}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
