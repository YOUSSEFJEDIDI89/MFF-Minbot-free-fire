"""
Wire protocol for the VortexVPN tunnel.

Frame layout (after AEAD decryption):

    +----+----+----+----+----+----+----+----+----+----+----+----+
    | 0x01 magic | type (1B) | flags (1B) | payload-len (4B BE)  |
    +----+----+----+----+----+----+----+----+----+----+----+----+
    |                       payload (variable)                  |
    +-----------------------------------------------------------+

The first byte is always 0x01 (protocol version 1). Packets with
unknown magic MUST be rejected to prevent cross-protocol attacks.
"""

from __future__ import annotations

import enum
import struct
from dataclasses import dataclass
from typing import Optional

MAGIC = 0x01
HEADER_FMT = "!BBBI"          # magic, type, flags, payload-len
HEADER_SIZE = struct.calcsize(HEADER_FMT)
MAX_PAYLOAD = 64 * 1024       # 64 KiB, fits within MTU + overhead


class PacketType(enum.IntEnum):
    HANDSHAKE_INIT = 0x01
    HANDSHAKE_REPLY = 0x02
    HANDSHAKE_FINISH = 0x03
    DATA = 0x10
    KEEPALIVE = 0x20
    DISCONNECT = 0x30
    ERROR = 0x40
    PING = 0x50
    PONG = 0x51


class ProtocolError(Exception):
    """Raised on malformed packets or version mismatch."""


@dataclass
class Packet:
    type: PacketType
    flags: int = 0
    payload: bytes = b""

    def serialize(self) -> bytes:
        if len(self.payload) > MAX_PAYLOAD:
            raise ProtocolError(f"payload too large: {len(self.payload)} > {MAX_PAYLOAD}")
        return struct.pack(HEADER_FMT, MAGIC, int(self.type), self.flags,
                           len(self.payload)) + self.payload

    @classmethod
    def deserialize(cls, data: bytes) -> "Packet":
        if len(data) < HEADER_SIZE:
            raise ProtocolError("frame shorter than header")
        magic, ptype, flags, plen = struct.unpack(HEADER_FMT, data[:HEADER_SIZE])
        if magic != MAGIC:
            raise ProtocolError(f"bad magic: 0x{magic:02x}")
        if plen > MAX_PAYLOAD:
            raise ProtocolError(f"declared payload too large: {plen}")
        payload = data[HEADER_SIZE:HEADER_SIZE + plen]
        if len(payload) != plen:
            raise ProtocolError("truncated payload")
        try:
            kind = PacketType(ptype)
        except ValueError as exc:
            raise ProtocolError(f"unknown packet type: 0x{ptype:02x}") from exc
        return cls(type=kind, flags=flags, payload=payload)


# Flag bits
FLAG_COMPRESSED = 0x01
FLAG_RELIABLE = 0x02   # request retransmission (future)
FLAG_PRIORITY = 0x04   # high-priority packet (e.g. handshake)


def make_handshake_init(client_pub: bytes, client_nonce: bytes,
                        username: str) -> Packet:
    """Build a HANDSHAKE_INIT packet."""
    user_bytes = username.encode("utf-8")
    if len(user_bytes) > 64:
        raise ProtocolError("username too long")
    payload = bytes([len(user_bytes)]) + user_bytes + client_nonce + client_pub
    return Packet(type=PacketType.HANDSHAKE_INIT, flags=FLAG_PRIORITY,
                  payload=payload)


def parse_handshake_init(packet: Packet) -> tuple[str, bytes, bytes]:
    """Parse a HANDSHAKE_INIT packet. Returns (username, nonce, pubkey)."""
    if packet.type != PacketType.HANDSHAKE_INIT:
        raise ProtocolError("not a handshake init")
    if len(packet.payload) < 1:
        raise ProtocolError("empty handshake payload")
    ulen = packet.payload[0]
    if len(packet.payload) < 1 + ulen + 16 + 32:
        raise ProtocolError("handshake payload too short")
    off = 1
    username = packet.payload[off:off + ulen].decode("utf-8")
    off += ulen
    nonce = packet.payload[off:off + 16]
    off += 16
    pub = packet.payload[off:off + 32]
    return username, nonce, pub


def make_handshake_reply(server_pub: bytes, server_nonce: bytes,
                         signature: bytes) -> Packet:
    payload = server_nonce + server_pub + signature
    return Packet(type=PacketType.HANDSHAKE_REPLY, flags=FLAG_PRIORITY,
                  payload=payload)


def parse_handshake_reply(packet: Packet) -> tuple[bytes, bytes, bytes]:
    if packet.type != PacketType.HANDSHAKE_REPLY:
        raise ProtocolError("not a handshake reply")
    if len(packet.payload) < 16 + 32 + 64:
        raise ProtocolError("handshake reply too short")
    off = 0
    nonce = packet.payload[off:off + 16]; off += 16
    pub = packet.payload[off:off + 32]; off += 32
    sig = packet.payload[off:off + 64]
    return nonce, pub, sig
