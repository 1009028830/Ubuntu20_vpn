import logging
import os
import selectors
import socket
import time
from dataclasses import dataclass
from typing import Optional, Tuple

from .crypto import TYPE_DATA, TYPE_HELLO, TYPE_KEEPALIVE, PacketError, VpnCrypto
from .tun import configure_tun, open_tun

Address = Tuple[str, int]


@dataclass
class VpnConfig:
    mode: str
    secret: bytes
    tun: str = "u20vpn0"
    address: Optional[str] = None
    mtu: int = 1400
    listen: Optional[Address] = None
    remote: Optional[Address] = None
    setup: bool = False
    keepalive: int = 20
    peer_timeout: int = 120
    max_packet_size: int = 65535


class UdpTunVpn:
    def __init__(self, config: VpnConfig) -> None:
        if config.mode not in {"client", "server"}:
            raise ValueError("mode must be client or server")
        if config.mode == "server" and not config.listen:
            raise ValueError("server mode requires listen address")
        if config.mode == "client" and not config.remote:
            raise ValueError("client mode requires remote address")

        self.config = config
        self.crypto = VpnCrypto(config.mode, config.secret)
        self.tun = None
        self.sock: Optional[socket.socket] = None
        self.peer: Optional[Address] = config.remote if config.mode == "client" else None
        self.last_peer_seen = 0.0
        self.last_hello = 0.0
        self.last_keepalive = 0.0
        self.running = False
        self.log = logging.getLogger("u20vpn")

    def run(self) -> None:
        self.tun = open_tun(self.config.tun)
        self.log.info("opened TUN device %s", self.tun.name)

        if self.config.setup:
            if not self.config.address:
                raise ValueError("--setup requires --address")
            configure_tun(self.tun.name, self.config.address, self.config.mtu)
            self.log.info("configured %s with %s mtu %s", self.tun.name, self.config.address, self.config.mtu)

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setblocking(False)

        if self.config.mode == "server":
            assert self.config.listen is not None
            self.sock.bind(self.config.listen)
            self.log.info("listening on udp://%s:%s", *self.config.listen)
        else:
            self.sock.bind(("0.0.0.0", 0))
            assert self.peer is not None
            self.log.info("client remote is udp://%s:%s", *self.peer)

        selector = selectors.DefaultSelector()
        selector.register(self.tun.fd, selectors.EVENT_READ, self._read_tun)
        selector.register(self.sock, selectors.EVENT_READ, self._read_socket)

        self.running = True
        self._send_hello()

        try:
            while self.running:
                for key, _ in selector.select(timeout=1.0):
                    callback = key.data
                    callback()
                self._tick()
        finally:
            selector.close()
            if self.sock:
                self.sock.close()
            if self.tun:
                self.tun.close()

    def stop(self) -> None:
        self.running = False

    def _read_tun(self) -> None:
        assert self.tun is not None
        try:
            packet = os.read(self.tun.fd, self.config.max_packet_size)
        except BlockingIOError:
            return

        if not packet:
            return
        if not self.peer:
            self.log.debug("dropping TUN packet because no authenticated peer is known")
            return

        self._send(TYPE_DATA, packet, self.peer)

    def _read_socket(self) -> None:
        assert self.sock is not None
        try:
            packet, addr = self.sock.recvfrom(self.config.max_packet_size)
        except BlockingIOError:
            return

        try:
            packet_type, payload = self.crypto.open(packet)
        except PacketError as exc:
            self.log.debug("ignored packet from %s:%s: %s", addr[0], addr[1], exc)
            return

        if self.config.mode == "server" and self.peer != addr:
            self.peer = addr
            self.log.info("authenticated peer is now %s:%s", addr[0], addr[1])

        if self.peer and addr != self.peer:
            self.log.debug("ignored authenticated packet from non-current peer %s:%s", addr[0], addr[1])
            return

        self.last_peer_seen = time.monotonic()

        if packet_type == TYPE_DATA:
            assert self.tun is not None
            os.write(self.tun.fd, payload)
        elif packet_type == TYPE_HELLO:
            self.log.debug("received hello from %s:%s", addr[0], addr[1])
            self._send(TYPE_KEEPALIVE, b"", addr)
        elif packet_type == TYPE_KEEPALIVE:
            self.log.debug("received keepalive from %s:%s", addr[0], addr[1])
        else:
            self.log.debug("ignored unknown packet type %s from %s:%s", packet_type, addr[0], addr[1])

    def _tick(self) -> None:
        now = time.monotonic()

        if self.config.mode == "server" and self.peer and self.last_peer_seen:
            if now - self.last_peer_seen > self.config.peer_timeout:
                self.log.warning("peer %s:%s timed out", self.peer[0], self.peer[1])
                self.peer = None
                self.last_peer_seen = 0.0

        if self.config.mode == "client" and self.last_peer_seen:
            if now - self.last_peer_seen > self.config.peer_timeout:
                self.log.warning("server %s:%s timed out; sending fresh hellos", self.peer[0], self.peer[1])
                self.last_peer_seen = 0.0

        if self.config.mode == "client" and not self.last_peer_seen:
            if now - self.last_hello >= min(5, self.config.keepalive):
                self._send_hello()
            return

        if self.peer and now - self.last_keepalive >= self.config.keepalive:
            self._send(TYPE_KEEPALIVE, b"", self.peer)
            self.last_keepalive = now

    def _send_hello(self) -> None:
        if self.peer:
            self._send(TYPE_HELLO, b"", self.peer)
            now = time.monotonic()
            self.last_hello = now
            self.last_keepalive = now

    def _send(self, packet_type: int, payload: bytes, addr: Address) -> None:
        assert self.sock is not None
        sealed = self.crypto.seal(packet_type, payload)
        self.sock.sendto(sealed, addr)
