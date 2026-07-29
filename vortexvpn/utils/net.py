"""
Network helpers: interface enumeration, IP/CIDR parsing, TUN device wrapper.
"""

from __future__ import annotations

import fcntl
import os
import socket
import struct
from dataclasses import dataclass
from typing import Optional


# Linux TUN/TAP constants
TUNSETIFF = 0x400454ca
IFF_TUN = 0x0001
IFF_NO_PI = 0x1000


def is_valid_cidr(cidr: str) -> bool:
    try:
        socket.inet_aton(cidr.split("/")[0])
        prefix = int(cidr.split("/")[1])
        return 0 <= prefix <= 32
    except (IndexError, ValueError, OSError):
        return False


def cidr_to_network_and_mask(cidr: str) -> tuple[int, int]:
    """Return (network_address_int, prefix_len)."""
    ip, prefix = cidr.split("/")
    ip_int = struct.unpack("!I", socket.inet_aton(ip))[0]
    mask = (0xFFFFFFFF << (32 - int(prefix))) & 0xFFFFFFFF
    return ip_int & mask, int(prefix)


@dataclass
class TunDevice:
    """Wrapper around a Linux TUN device."""
    name: str
    fd: int = -1

    @classmethod
    def create(cls, name: str = "vortex%d") -> "TunDevice":
        """Open a new TUN device. Requires root and Linux."""
        if not os.path.exists("/dev/net/tun"):
            raise RuntimeError("TUN device not available (Linux only)")
        fd = os.open("/dev/net/tun", os.O_RDWR)
        ifr = struct.pack("16sH", name.encode("utf-8")[:15], IFF_TUN | IFF_NO_PI)
        try:
            fcntl.ioctl(fd, TUNSETIFF, ifr)
        except OSError as exc:
            os.close(fd)
            raise RuntimeError("TUNSETIFF failed") from exc
        actual_name = ifr[:16].rstrip(b"\x00").decode("utf-8")
        return cls(name=actual_name, fd=fd)

    def read(self, n: int = 65536) -> bytes:
        if self.fd < 0:
            raise RuntimeError("device closed")
        return os.read(self.fd, n)

    def write(self, data: bytes) -> int:
        if self.fd < 0:
            raise RuntimeError("device closed")
        return os.write(self.fd, data)

    def close(self) -> None:
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1


def get_local_ip() -> str:
    """Best-effort: return this host's primary outbound IP."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()
