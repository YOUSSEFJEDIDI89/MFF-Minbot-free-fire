"""
Cryptographic engine for VortexVPN.

Uses AES-256-GCM for symmetric encryption of tunnel packets, and
HKDF-SHA256 (or Argon2id when configured) for key derivation.
Optionally delegates hot-path encryption to the C++ accelerator
when the pybind11 module `vortex_accel` is available.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from dataclasses import dataclass
from typing import Optional

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    from cryptography.hazmat.primitives.kdf.argon2 import Argon2id
    from cryptography.hazmat.primitives import hashes
    _HAS_CRYPTO = True
except ImportError:  # pragma: no cover - cryptography is a hard dep in production
    _HAS_CRYPTO = False

# Optional C++ acceleration
try:
    import vortex_accel  # type: ignore
    _HAS_ACCEL = True
except ImportError:
    _HAS_ACCEL = False


NONCE_SIZE = 12            # 96-bit nonce recommended for GCM
KEY_SIZE = 32              # 256-bit key
TAG_SIZE = 16              # GCM auth tag
KDF_INFO = b"vortexvpn-v1-session-key"
HANDSHAKE_MAGIC = b"VORTEX1"


class CryptoError(Exception):
    """Raised on decryption failure, bad MAC, or key derivation failure."""


@dataclass
class KeyDerivation:
    """Key derivation parameters used during the handshake."""

    algorithm: str = "hkdf-sha256"
    salt: Optional[bytes] = None
    iterations: int = 3  # only used by argon2id

    @classmethod
    def generate(cls, algorithm: str = "hkdf-sha256") -> "KeyDerivation":
        return cls(algorithm=algorithm, salt=secrets.token_bytes(16))


class CryptoEngine:
    """
    Per-session symmetric crypto engine. Once the handshake produces
    a shared secret, `derive_session_keys` is called to materialise
    TX and RX keys; `seal` / `open` then protect individual packets.
    """

    __slots__ = ("_tx_key", "_rx_key", "_tx_ctr", "_rx_ctr", "_use_accel")

    def __init__(self) -> None:
        self._tx_key: Optional[bytes] = None
        self._rx_key: Optional[bytes] = None
        self._tx_ctr: int = 0
        self._rx_ctr: int = 0
        self._use_accel: bool = _HAS_ACCEL

    # ------------------------------------------------------------------ #
    # Key derivation
    # ------------------------------------------------------------------ #
    def derive_session_keys(self, shared_secret: bytes, kdf: KeyDerivation,
                            client_nonce: bytes, server_nonce: bytes,
                            role: str = "server") -> None:
        """Derive directional keys from the handshake shared secret.

        Role determines key directionality:
          - "server": tx_key = base[:K],  rx_key = base[K:]
          - "client": tx_key = base[K:],  rx_key = base[:K]

        This ensures client.tx_key == server.rx_key (and vice versa),
        which is what real AEAD-based tunnel protocols require.
        """
        if not _HAS_CRYPTO:
            raise CryptoError("cryptography library not installed")

        if kdf.algorithm == "hkdf-sha256":
            base = HKDF(
                algorithm=hashes.SHA256(),
                length=KEY_SIZE * 2,
                salt=kdf.salt,
                info=KDF_INFO,
            ).derive(shared_secret + client_nonce + server_nonce)
        elif kdf.algorithm == "argon2id":
            kdf_obj = Argon2id(
                salt=kdf.salt or b"vortex-static-salt",
                length=KEY_SIZE * 2,
                iterations=kdf.iterations,
                lanes=2,
                memory_cost=65536,
                ad=None,
                secret=None,
            )
            base = kdf_obj.derive(shared_secret + client_nonce + server_nonce)
        else:
            raise CryptoError(f"unsupported kdf: {kdf.algorithm}")

        if role == "client":
            self._tx_key = base[KEY_SIZE:]
            self._rx_key = base[:KEY_SIZE]
        else:
            self._tx_key = base[:KEY_SIZE]
            self._rx_key = base[KEY_SIZE:]
        self._tx_ctr = 0
        self._rx_ctr = 0

    # ------------------------------------------------------------------ #
    # AEAD
    # ------------------------------------------------------------------ #
    def _nonce_for(self, counter: int) -> bytes:
        # 4-byte fixed prefix (per session, derived from key) + 8-byte counter
        # We use a deterministic scheme: counter is encoded big-endian.
        return counter.to_bytes(NONCE_SIZE, "big")

    def seal(self, plaintext: bytes, aad: bytes = b"") -> bytes:
        """Encrypt + authenticate plaintext. Returns nonce||ciphertext||tag."""
        if self._tx_key is None:
            raise CryptoError("session keys not derived")

        nonce = self._nonce_for(self._tx_ctr)
        self._tx_ctr += 1

        if self._use_accel:
            try:
                ct = vortex_accel.aes_gcm_encrypt(self._tx_key, nonce, plaintext, aad)
                return nonce + ct
            except Exception:
                # Fall back to pure-Python on accelerator error
                self._use_accel = False

        aesgcm = AESGCM(self._tx_key)
        ct = aesgcm.encrypt(nonce, plaintext, aad or None)
        return nonce + ct

    def open(self, frame: bytes, aad: bytes = b"") -> bytes:
        """Verify + decrypt. Raises CryptoError on failure."""
        if self._rx_key is None:
            raise CryptoError("session keys not derived")
        if len(frame) < NONCE_SIZE + TAG_SIZE:
            raise CryptoError("frame too short")

        nonce = frame[:NONCE_SIZE]
        ct = frame[NONCE_SIZE:]

        if self._use_accel:
            try:
                return vortex_accel.aes_gcm_decrypt(self._rx_key, nonce, ct, aad)
            except Exception:
                self._use_accel = False

        aesgcm = AESGCM(self._rx_key)
        try:
            return aesgcm.decrypt(nonce, ct, aad or None)
        except Exception as exc:
            raise CryptoError("decryption failed") from exc

    # ------------------------------------------------------------------ #
    # Handshake helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def generate_ephemeral_keypair() -> tuple[bytes, bytes]:
        """Generate an X25519 keypair for the handshake."""
        if not _HAS_CRYPTO:
            raise CryptoError("cryptography library not installed")
        from cryptography.hazmat.primitives.asymmetric.x25519 import (
            X25519PrivateKey,
        )
        from cryptography.hazmat.primitives.serialization import (
            Encoding, PrivateFormat, PublicFormat, NoEncryption,
        )
        priv = X25519PrivateKey.generate()
        pub = priv.public_key()
        priv_bytes = priv.private_bytes(
            encoding=Encoding.Raw,
            format=PrivateFormat.Raw,
            encryption_algorithm=NoEncryption(),
        )
        pub_bytes = pub.public_bytes(
            encoding=Encoding.Raw,
            format=PublicFormat.Raw,
        )
        return priv_bytes, pub_bytes

    @staticmethod
    def dh_shared_secret(priv_bytes: bytes, peer_pub_bytes: bytes) -> bytes:
        """Compute the X25519 shared secret."""
        if not _HAS_CRYPTO:
            raise CryptoError("cryptography library not installed")
        from cryptography.hazmat.primitives.asymmetric.x25519 import (
            X25519PrivateKey, X25519PublicKey,
        )
        priv = X25519PrivateKey.from_private_bytes(priv_bytes)
        peer_pub = X25519PublicKey.from_public_bytes(peer_pub_bytes)
        return priv.exchange(peer_pub)

    @property
    def using_accelerator(self) -> bool:
        return self._use_accel
