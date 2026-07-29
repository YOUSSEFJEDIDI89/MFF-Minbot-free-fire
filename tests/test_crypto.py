"""Tests for the crypto engine."""
from __future__ import annotations

import os

import pytest

from vortexvpn.core.crypto import CryptoEngine, KeyDerivation, CryptoError


def test_aes_gcm_round_trip() -> None:
    """Two engines with swapped roles must round-trip: client seals, server opens."""
    secret = os.urandom(32)
    kdf = KeyDerivation.generate()
    client = CryptoEngine()
    client.derive_session_keys(secret, kdf, b"\x01" * 16, b"\x02" * 16,
                               role="client")
    server = CryptoEngine()
    server.derive_session_keys(secret, kdf, b"\x01" * 16, b"\x02" * 16,
                               role="server")

    plaintext = b"vortexvpn test packet " * 10
    frame = client.seal(plaintext, aad=b"hdr")
    assert frame[:12] != plaintext[:12]  # nonce prefix differs
    recovered = server.open(frame, aad=b"hdr")
    assert recovered == plaintext


def test_aes_gcm_tamper_detected() -> None:
    """Flipping a bit in the ciphertext must raise CryptoError."""
    secret = os.urandom(32)
    kdf = KeyDerivation.generate()
    client = CryptoEngine(); client.derive_session_keys(secret, kdf,
        b"\x01" * 16, b"\x02" * 16, role="client")
    server = CryptoEngine(); server.derive_session_keys(secret, kdf,
        b"\x01" * 16, b"\x02" * 16, role="server")

    frame = bytearray(client.seal(b"secret data", aad=b""))
    frame[20] ^= 0x01  # tamper with ciphertext
    with pytest.raises(CryptoError):
        server.open(bytes(frame), aad=b"")


def test_aes_gcm_aad_mismatch() -> None:
    """Different AAD must reject the frame."""
    secret = os.urandom(32)
    kdf = KeyDerivation.generate()
    client = CryptoEngine(); client.derive_session_keys(secret, kdf,
        b"\x01" * 16, b"\x02" * 16, role="client")
    server = CryptoEngine(); server.derive_session_keys(secret, kdf,
        b"\x01" * 16, b"\x02" * 16, role="server")

    frame = client.seal(b"data", aad=b"aad-1")
    with pytest.raises(CryptoError):
        server.open(frame, aad=b"aad-2")


def test_each_seal_uses_unique_nonce() -> None:
    """Consecutive seals must produce distinct nonces (counter advance)."""
    secret = os.urandom(32)
    kdf = KeyDerivation.generate()
    engine = CryptoEngine()
    engine.derive_session_keys(secret, kdf, b"\x01" * 16, b"\x02" * 16,
                               role="server")

    f1 = engine.seal(b"a")
    f2 = engine.seal(b"b")
    f3 = engine.seal(b"c")
    nonces = {f1[:12], f2[:12], f3[:12]}
    assert len(nonces) == 3


def test_bidirectional_round_trip() -> None:
    """Both directions must work: client->server AND server->client."""
    secret = os.urandom(32)
    kdf = KeyDerivation.generate()
    client = CryptoEngine(); client.derive_session_keys(secret, kdf,
        b"\x01" * 16, b"\x02" * 16, role="client")
    server = CryptoEngine(); server.derive_session_keys(secret, kdf,
        b"\x01" * 16, b"\x02" * 16, role="server")

    # client -> server
    cs = client.seal(b"client to server")
    assert server.open(cs) == b"client to server"
    # server -> client
    sc = server.seal(b"server to client")
    assert client.open(sc) == b"server to client"


def test_seal_without_keys_raises() -> None:
    engine = CryptoEngine()
    with pytest.raises(CryptoError):
        engine.seal(b"x")
