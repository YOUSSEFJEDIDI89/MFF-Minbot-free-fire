"""Tests for the wire protocol."""
from __future__ import annotations

import pytest

from vortexvpn.core.protocol import (
    Packet, PacketType, ProtocolError, MAX_PAYLOAD,
    make_handshake_init, parse_handshake_init,
    MAGIC, FLAG_PRIORITY,
)


def test_round_trip_data_packet() -> None:
    pkt = Packet(type=PacketType.DATA, payload=b"hello world")
    raw = pkt.serialize()
    assert raw[0] == MAGIC
    recovered = Packet.deserialize(raw)
    assert recovered.type == PacketType.DATA
    assert recovered.payload == b"hello world"


def test_packet_with_flags() -> None:
    pkt = Packet(type=PacketType.HANDSHAKE_INIT,
                 flags=FLAG_PRIORITY, payload=b"xyz")
    raw = pkt.serialize()
    recovered = Packet.deserialize(raw)
    assert recovered.flags == FLAG_PRIORITY


def test_oversized_payload_rejected() -> None:
    with pytest.raises(ProtocolError):
        Packet(type=PacketType.DATA,
               payload=b"x" * (MAX_PAYLOAD + 1)).serialize()


def test_bad_magic_rejected() -> None:
    import struct
    bad = struct.pack("!BBBI", 0xFF, int(PacketType.DATA), 0, 0)
    with pytest.raises(ProtocolError):
        Packet.deserialize(bad)


def test_truncated_payload_rejected() -> None:
    import struct
    truncated = struct.pack("!BBBI", MAGIC, int(PacketType.DATA), 0, 100) + b"short"
    with pytest.raises(ProtocolError):
        Packet.deserialize(truncated)


def test_handshake_init_round_trip() -> None:
    pub = b"P" * 32
    nonce = b"N" * 16
    pkt = make_handshake_init(pub, nonce, "alice")
    username, recovered_nonce, recovered_pub = parse_handshake_init(pkt)
    assert username == "alice"
    assert recovered_nonce == nonce
    assert recovered_pub == pub


def test_unknown_packet_type_rejected() -> None:
    import struct
    raw = struct.pack("!BBBI", MAGIC, 0xFF, 0, 0)
    with pytest.raises(ProtocolError):
        Packet.deserialize(raw)
