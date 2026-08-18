import base64
import os
from collections import deque
from dataclasses import dataclass
from typing import Deque, Set, Tuple

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

MAGIC = b"U20VPN01"
TYPE_DATA = 1
TYPE_HELLO = 2
TYPE_KEEPALIVE = 3

HEADER_LEN = len(MAGIC) + 1 + 12
KEY_LEN = 32


class PacketError(Exception):
    """Raised when an incoming packet is malformed or unauthenticated."""


class ReplayWindow:
    def __init__(self, limit: int = 8192) -> None:
        self.limit = limit
        self._seen: Set[bytes] = set()
        self._order: Deque[bytes] = deque()

    def accept(self, nonce: bytes) -> bool:
        if nonce in self._seen:
            return False
        self._seen.add(nonce)
        self._order.append(nonce)
        while len(self._order) > self.limit:
            old = self._order.popleft()
            self._seen.discard(old)
        return True


def generate_secret() -> str:
    return base64.urlsafe_b64encode(os.urandom(KEY_LEN)).decode("ascii")


def load_secret(secret_text: str) -> bytes:
    raw = secret_text.strip()
    if not raw:
        raise ValueError("secret is empty")

    try:
        decoded = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
        if len(decoded) >= KEY_LEN:
            return decoded
    except Exception:
        pass

    return raw.encode("utf-8")


def derive_key(secret: bytes, info: bytes) -> bytes:
    return HKDF(
        algorithm=hashes.SHA256(),
        length=KEY_LEN,
        salt=b"u20vpn-v1",
        info=info,
    ).derive(secret)


@dataclass
class VpnCrypto:
    role: str
    secret: bytes

    def __post_init__(self) -> None:
        if self.role not in {"client", "server"}:
            raise ValueError("role must be client or server")

        c2s = derive_key(self.secret, b"client-to-server")
        s2c = derive_key(self.secret, b"server-to-client")

        if self.role == "client":
            self._send = ChaCha20Poly1305(c2s)
            self._recv = ChaCha20Poly1305(s2c)
        else:
            self._send = ChaCha20Poly1305(s2c)
            self._recv = ChaCha20Poly1305(c2s)

        self._nonce_prefix = os.urandom(4)
        self._counter = 0
        self._replay = ReplayWindow()

    def seal(self, packet_type: int, payload: bytes = b"") -> bytes:
        if packet_type < 1 or packet_type > 255:
            raise ValueError("packet type must fit in one byte")

        nonce = self._next_nonce()
        header = MAGIC + bytes([packet_type]) + nonce
        encrypted = self._send.encrypt(nonce, payload, header)
        return header + encrypted

    def open(self, packet: bytes) -> Tuple[int, bytes]:
        if len(packet) < HEADER_LEN + 16:
            raise PacketError("packet too short")
        if packet[: len(MAGIC)] != MAGIC:
            raise PacketError("bad magic")

        packet_type = packet[len(MAGIC)]
        nonce = packet[len(MAGIC) + 1 : HEADER_LEN]
        header = packet[:HEADER_LEN]
        ciphertext = packet[HEADER_LEN:]

        if not self._replay.accept(nonce):
            raise PacketError("replayed packet")

        try:
            payload = self._recv.decrypt(nonce, ciphertext, header)
        except InvalidTag as exc:
            raise PacketError("authentication failed") from exc

        return packet_type, payload

    def _next_nonce(self) -> bytes:
        self._counter += 1
        if self._counter >= 2**64:
            raise RuntimeError("nonce counter exhausted; restart the process")
        return self._nonce_prefix + self._counter.to_bytes(8, "big")

