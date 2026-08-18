import argparse
import json
import logging
import signal
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .crypto import generate_secret, load_secret


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "gen-key":
        print(generate_secret())
        return 0

    if args.command == "clash":
        try:
            from .mihomo import handle_clash_command

            return handle_clash_command(args)
        except Exception as exc:
            logging.getLogger("u20vpn").error("%s", exc)
            return 1

    if args.command != "run":
        parser.print_help()
        return 2

    try:
        config = build_config(args)
        from .vpn import UdpTunVpn

        configure_logging(args.verbose)
        vpn = UdpTunVpn(config)
        install_signal_handlers(vpn)
        vpn.run()
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        logging.getLogger("u20vpn").error("%s", exc)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="u20vpn", description="Minimal encrypted TUN/UDP VPN")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("gen-key", help="generate a base64 pre-shared key")
    build_clash_parser(subparsers)

    run = subparsers.add_parser("run", help="run a VPN endpoint")
    run.add_argument("--config", help="JSON config file")
    run.add_argument("--mode", choices=["server", "client"], help="endpoint mode")
    run.add_argument("--listen", help="server listen address, for example 0.0.0.0:51888")
    run.add_argument("--remote", help="client remote address, for example 203.0.113.10:51888")
    run.add_argument("--secret-file", help="file containing the pre-shared key")
    run.add_argument("--secret", help="pre-shared key text; prefer --secret-file in production")
    run.add_argument("--tun", help="TUN device name")
    run.add_argument("--address", help="TUN interface CIDR, for example 10.88.0.1/24")
    run.add_argument("--mtu", type=int, help="TUN MTU")
    run.add_argument("--setup", action="store_true", default=None, help="configure TUN address and bring it up")
    run.add_argument("--no-setup", action="store_false", dest="setup", help="do not configure TUN")
    run.add_argument("--keepalive", type=int, help="keepalive interval in seconds")
    run.add_argument("--peer-timeout", type=int, help="server peer timeout in seconds")
    run.add_argument("-v", "--verbose", action="count", default=0, help="increase logging verbosity")
    return parser


def build_clash_parser(subparsers: argparse._SubParsersAction) -> None:
    clash = subparsers.add_parser("clash", help="mihomo/Clash subscription helpers")
    clash_subparsers = clash.add_subparsers(dest="clash_command")

    render_config = clash_subparsers.add_parser("render-config", help="render a mihomo config from a Clash subscription")
    add_clash_config_args(render_config)
    render_config.add_argument("-o", "--output", help="write config to this path instead of stdout")

    render_service = clash_subparsers.add_parser("render-service", help="render a mihomo systemd service")
    render_service.add_argument("--config-dir", default="/etc/mihomo", help="mihomo config directory")
    render_service.add_argument("--binary", default="/usr/local/bin/mihomo", help="mihomo binary path")
    render_service.add_argument("-o", "--output", help="write service to this path instead of stdout")

    init = clash_subparsers.add_parser("init", help="write mihomo config and systemd service")
    add_clash_config_args(init)
    init.add_argument("--config", default="/etc/mihomo/config.yaml", help="config output path")
    init.add_argument("--service", default="/etc/systemd/system/mihomo.service", help="systemd service output path")
    init.add_argument("--binary", default="/usr/local/bin/mihomo", help="mihomo binary path")

    ui = clash_subparsers.add_parser("ui", help="run a local mihomo node selection UI")
    ui.add_argument("--config", default="/etc/mihomo/config.yaml", help="mihomo config path")
    ui.add_argument("--controller", help="mihomo external controller URL, for example http://127.0.0.1:9090")
    ui.add_argument("--secret", help="mihomo external controller secret; read from config by default")
    ui.add_argument("--host", default="127.0.0.1", help="UI listen host")
    ui.add_argument("--port", type=int, default=7895, help="UI listen port")
    ui.add_argument("--open", action="store_true", help="open the UI in the default browser")


def add_clash_config_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--subscription-url", help="Clash subscription URL; avoid shell history by using --subscription-file")
    parser.add_argument("--subscription-file", help="file containing the Clash subscription URL")
    parser.add_argument("--mixed-port", type=int, default=7890, help="local HTTP/SOCKS mixed proxy port")
    parser.add_argument("--external-controller", default="127.0.0.1:9090", help="mihomo external controller address")
    parser.add_argument("--controller-secret", help="external controller secret; random by default")
    parser.add_argument("--mode", choices=["rule", "global", "direct"], default="rule", help="mihomo routing mode")
    parser.add_argument("--allow-lan", action="store_true", help="listen on LAN instead of only 127.0.0.1")
    parser.add_argument("--no-tun", action="store_true", help="disable TUN mode in generated config")
    parser.add_argument("--no-dns", action="store_true", help="disable mihomo DNS in generated config")


def build_config(args: argparse.Namespace):
    from .vpn import VpnConfig

    data: Dict[str, Any] = {
        "tun": "u20vpn0",
        "mtu": 1400,
        "setup": False,
        "keepalive": 20,
        "peer_timeout": 120,
    }

    if args.config:
        with open(args.config, "r", encoding="utf-8") as fh:
            loaded = json.load(fh)
        if not isinstance(loaded, dict):
            raise ValueError("config file must contain a JSON object")
        data.update(loaded)

    for key in (
        "mode",
        "listen",
        "remote",
        "secret_file",
        "secret",
        "tun",
        "address",
        "mtu",
        "setup",
        "keepalive",
        "peer_timeout",
    ):
        value = getattr(args, key, None)
        if value is not None:
            data[key] = value

    mode = require_str(data, "mode")
    secret = read_secret(data)

    listen = parse_address(data["listen"]) if data.get("listen") else None
    remote = parse_address(data["remote"]) if data.get("remote") else None

    return VpnConfig(
        mode=mode,
        secret=secret,
        tun=str(data.get("tun", "u20vpn0")),
        address=data.get("address"),
        mtu=int(data.get("mtu", 1400)),
        listen=listen,
        remote=remote,
        setup=bool(data.get("setup", False)),
        keepalive=int(data.get("keepalive", 20)),
        peer_timeout=int(data.get("peer_timeout", 120)),
    )


def read_secret(data: Dict[str, Any]) -> bytes:
    if data.get("secret_file"):
        secret_text = Path(str(data["secret_file"])).read_text(encoding="utf-8")
        return load_secret(secret_text)
    if data.get("secret"):
        return load_secret(str(data["secret"]))
    raise ValueError("missing secret; use --secret-file or --secret")


def require_str(data: Dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"missing required option: {key}")
    return value


def parse_address(value: str) -> Tuple[str, int]:
    if ":" not in value:
        raise ValueError(f"address must be host:port: {value}")
    host, port_text = value.rsplit(":", 1)
    if not host:
        raise ValueError(f"address host is empty: {value}")
    port = int(port_text)
    if port < 1 or port > 65535:
        raise ValueError(f"port out of range: {value}")
    return host, port


def configure_logging(verbose: int) -> None:
    level = logging.WARNING
    if verbose == 1:
        level = logging.INFO
    elif verbose >= 2:
        level = logging.DEBUG
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def install_signal_handlers(vpn) -> None:
    def stop(_signum: int, _frame: Any) -> None:
        vpn.stop()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
