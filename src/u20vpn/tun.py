import fcntl
import os
import struct
import subprocess
from dataclasses import dataclass

TUNSETIFF = 0x400454CA
IFF_TUN = 0x0001
IFF_NO_PI = 0x1000


@dataclass
class TunDevice:
    name: str
    fd: int

    def fileno(self) -> int:
        return self.fd

    def close(self) -> None:
        os.close(self.fd)


def open_tun(name: str) -> TunDevice:
    if len(name.encode("utf-8")) > 15:
        raise ValueError("TUN device name must be 15 bytes or fewer")

    fd = os.open("/dev/net/tun", os.O_RDWR)
    ifr = struct.pack("16sH", name.encode("utf-8"), IFF_TUN | IFF_NO_PI)
    result = fcntl.ioctl(fd, TUNSETIFF, ifr)
    actual_name = result[:16].split(b"\x00", 1)[0].decode("utf-8")
    os.set_blocking(fd, False)
    return TunDevice(actual_name, fd)


def configure_tun(name: str, address: str, mtu: int) -> None:
    run_ip("addr", "replace", address, "dev", name)
    run_ip("link", "set", "dev", name, "mtu", str(mtu), "up")


def run_ip(*args: str) -> None:
    subprocess.run(["ip", *args], check=True)

