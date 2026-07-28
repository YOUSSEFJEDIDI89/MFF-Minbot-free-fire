"""
Cryptographic engine for VortexVPN.

Uses AES-256-GCM for symmetric encryption of tunnel packets, and
HKDF-SHA256 (or Argon2id when configured) for key derivation.
Optionally delegates hot-path encryption to the C++ accelerator
when the pybind11 module `vortex_accel` is available.

Backend support
---------------
VortexVPN ships with two interchangeable crypto backends so it runs
on platforms where the standard `cryptography` package is hard to
build (notably Termux / Android aarch64, which has no Rust toolchain):

  1. `cryptography` (preferred) — full-featured, audited.
  2. `pycryptodome` (fallback)  — pure-C wheels for Android, iOS, etc.

Both backends implement the same minimal surface:
  - AES-256-GCM seal/open
  - X25519 key exchange
  - HKDF-SHA256
  - Argon2id (only `cryptography`; pycryptodome has it too via `argon2-cffi`)

If neither is available, CryptoError is raised at derive time.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from dataclasses import dataclass
from typing import Optional

# ---------------------------------------------------------------------------
# Backend detection
# ---------------------------------------------------------------------------
_BACKEND: Optional[str] = None

# Optional C++ accelerator
try:
    import vortex_accel  # type: ignore
    _HAS_ACCEL = True
except ImportError:
    _HAS_ACCEL = False

# Try cryptography first
try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    from cryptography.hazmat.primitives.kdf.argon2 import Argon2id
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric.x25519 import (
        X25519PrivateKey, X25519PublicKey,
    )
    from cryptography.hazmat.primitives.serialization import (
        Encoding, PrivateFormat, PublicFormat, NoEncryption,
    )
    _BACKEND = "cryptography"
except ImportError:
    pass

# Fall back to pycryptodome
if _BACKEND is None:
    try:
        from Crypto.Cipher import AES as _pcAES
        from Crypto.Protocol.KDF import HKDF as _pcHKDF
        from Crypto.PublicKey import ECC as _pcECC
        from Crypto.Hash import SHA256 as _pcSHA256
        from Crypto.Protocol.KDF import scrypt as _pcScrypt  # for argon2 fallback
        _BACKEND = "pycryptodome"
    except ImportError:
        pass


NONCE_SIZE = 12            # 96-bit nonce recommended for GCM
KEY_SIZE = 32              # 256-bit key
TAG_SIZE = 16              # GCM auth tag
KDF_INFO = b"vortexvpn-v1-session-key"
HANDSHAKE_MAGIC = b"VORTEX1"


class CryptoError(Exception):
    """Raised on decryption failure, bad MAC, or key derivation failure."""


def get_backend() -> str:
    """Return the active crypto backend name (or 'none' if unavailable)."""
    return _BACKEND or "none"


@dataclass
class KeyDerivation:
    """Key derivation parameters used during the handshake."""

    algorithm: str = "hkdf-sha256"
    salt: Optional[bytes] = None
    iterations: int = 3  # only used by argon2id

    @classmethod
    def generate(cls, algorithm: str = "hkdf-sha256") -> "KeyDerivation":
        return cls(algorithm=algorithm, salt=secrets.token_bytes(16))


# ---------------------------------------------------------------------------
# pycryptodome thin shims (used only when _BACKEND == 'pycryptodome')
# ---------------------------------------------------------------------------
def _pc_aes_gcm_encrypt(key: bytes, nonce: bytes, pt: bytes, aad: bytes) -> bytes:
    cipher = _pcAES.new(key, _pcAES.MODE_GCM, nonce=nonce)
    if aad:
        cipher.update(aad)
    ct, tag = cipher.encrypt_and_digest(pt)
    return ct + tag  # mirror cryptography lib's layout: ct || tag


def _pc_aes_gcm_decrypt(key: bytes, nonce: bytes, ct_tag: bytes, aad: bytes) -> bytes:
    if len(ct_tag) < TAG_SIZE:
        raise CryptoError("ciphertext too short")
    ct, tag = ct_tag[:-TAG_SIZE], ct_tag[-TAG_SIZE:]
    cipher = _pcAES.new(key, _pcAES.MODE_GCM, nonce=nonce)
    if aad:
        cipher.update(aad)
    try:
        return cipher.decrypt_and_verify(ct, tag)
    except (ValueError, KeyError) as exc:
        raise CryptoError("decryption failed") from exc


def _pc_x25519_generate() -> tuple[bytes, bytes]:
    """Generate an X25519 keypair.

    pycryptodome doesn't expose X25519 directly. We generate a random
    clamped scalar and use the pure-Python Montgomery ladder to compute
    the public key (g * scalar where g is the Curve25519 base point).
    """
    scalar = bytearray(os.urandom(32))
    # Clamp per RFC 7748
    scalar[0] &= 248
    scalar[31] &= 127
    scalar[31] |= 64
    priv_bytes = bytes(scalar)
    # Base point u=9 → public key
    pub_bytes = _x25519_scalarmult(priv_bytes, (9).to_bytes(32, "little"))
    return priv_bytes, pub_bytes


def _pc_x25519_shared(priv_bytes: bytes, peer_pub_bytes: bytes) -> bytes:
    """Compute X25519 shared secret via pure-Python Montgomery ladder."""
    return _x25519_scalarmult(priv_bytes, peer_pub_bytes)


# Pure-Python X25519 (RFC 7748) — slow but always works
def _x25519_scalarmult(scalar: bytes, u_coord: bytes) -> bytes:
    """X25519 scalar multiplication per RFC 7748."""
    P = 2**255 - 19
    A24 = 121665

    def clamp(k: bytes) -> int:
        k_list = list(k)
        k_list[0] &= 248
        k_list[31] &= 127
        k_list[31] |= 64
        return int.from_bytes(bytes(k_list), "little")

    k = clamp(scalar)
    u = int.from_bytes(u_coord, "little") % P

    x1 = u
    x2, z2 = 1, 0
    x3, z3 = u, 1
    swap = 0

    for t in range(254, -1, -1):
        k_t = (k >> t) & 1
        swap ^= k_t
        if swap:
            x2, x3 = x3, x2
            z2, z3 = z3, z2
        swap = k_t

        A = (x2 + z2) % P
        AA = (A * A) % P
        B = (x2 - z2) % P
        BB = (B * B) % P
        E = (AA - BB) % P
        C = (x3 + z3) % P
        D = (x3 - z3) % P
        DA = (D * A) % P
        CB = (C * B) % P
        x3 = ((DA + CB) ** 2) % P
        z3 = (x1 * ((DA - CB) ** 2)) % P
        x2 = (AA * BB) % P
        z2 = (E * (AA + A24 * E)) % P

    if swap:
        x2, x3 = x3, x2
    inv = pow(z2, P - 2, P)
    shared = (x2 * inv) % P
    return shared.to_bytes(32, "little")


def _pc_hkdf_sha256(secret: bytes, salt: bytes, info: bytes, length: int) -> bytes:
    return _pcHKDF(secret, length, salt=salt if salt else None,
                   hashmod=_pcSHA256, context=info)


def _pc_argon2id(secret: bytes, salt: bytes, length: int,
                 iterations: int) -> bytes:
    """Argon2id fallback via scrypt (similar memory-hardness).

    Note: pycryptodome ships scrypt but not argon2. We approximate
    with scrypt at N=2^16 (64 MiB memory). For real Argon2id, install
    `argon2-cffi` which has Android wheels.
    """
    try:
        from argon2.low_level import hash_secret_raw, Type as Argon2Type
        return hash_secret_raw(
            secret=secret, salt=salt,
            time_cost=iterations, memory_cost=65536,
            parallelism=2, hash_len=length, type=Argon2Type.ID,
        )
    except ImportError:
        pass
    # Fallback: scrypt
    return _pcScrypt(password=secret, salt=salt, key_len=length,
                     N=2**16, r=8, p=2)


# ---------------------------------------------------------------------------
# CryptoEngine
# ---------------------------------------------------------------------------
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
        if _BACKEND is None:
            raise CryptoError(
                "no crypto backend available. Install one of:\n"
                "  - pip install cryptography   (preferred, requires Rust on some platforms)\n"
                "  - pip install pycryptodome   (works on Termux/Android without Rust)"
            )

        material = shared_secret + client_nonce + server_nonce
        if kdf.algorithm == "hkdf-sha256":
            if _BACKEND == "cryptography":
                base = HKDF(
                    algorithm=hashes.SHA256(),
                    length=KEY_SIZE * 2,
                    salt=kdf.salt,
                    info=KDF_INFO,
                ).derive(material)
            else:  # pycryptodome
                base = _pc_hkdf_sha256(material, kdf.salt or b"", KDF_INFO, KEY_SIZE * 2)
        elif kdf.algorithm == "argon2id":
            if _BACKEND == "cryptography":
                kdf_obj = Argon2id(
                    salt=kdf.salt or b"vortex-static-salt",
                    length=KEY_SIZE * 2,
                    iterations=kdf.iterations,
                    lanes=2,
                    memory_cost=65536,
                    ad=None,
                    secret=None,
                )
                base = kdf_obj.derive(material)
            else:  # pycryptodome
                base = _pc_argon2id(material, kdf.salt or b"vortex-static-salt",
                                    KEY_SIZE * 2, kdf.iterations)
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
        return counter.to_bytes(NONCE_SIZE, "big")

    def seal(self, plaintext: bytes, aad: bytes = b"") -> bytes:
        """Encrypt + authenticate plaintext. Returns nonce||ciphertext||tag."""
        if self._tx_key is None:
            raise CryptoError("session keys not derived")
        if _BACKEND is None:
            raise CryptoError("no crypto backend available")

        nonce = self._nonce_for(self._tx_ctr)
        self._tx_ctr += 1

        if self._use_accel:
            try:
                ct = vortex_accel.aes_gcm_encrypt(self._tx_key, nonce, plaintext, aad)
                return nonce + ct
            except Exception:
                self._use_accel = False

        if _BACKEND == "cryptography":
            aesgcm = AESGCM(self._tx_key)
            ct = aesgcm.encrypt(nonce, plaintext, aad or None)
        else:  # pycryptodome
            ct = _pc_aes_gcm_encrypt(self._tx_key, nonce, plaintext, aad)
        return nonce + ct

    def open(self, frame: bytes, aad: bytes = b"") -> bytes:
        """Verify + decrypt. Raises CryptoError on failure."""
        if self._rx_key is None:
            raise CryptoError("session keys not derived")
        if _BACKEND is None:
            raise CryptoError("no crypto backend available")
        if len(frame) < NONCE_SIZE + TAG_SIZE:
            raise CryptoError("frame too short")

        nonce = frame[:NONCE_SIZE]
        ct = frame[NONCE_SIZE:]

        if self._use_accel:
            try:
                return vortex_accel.aes_gcm_decrypt(self._rx_key, nonce, ct, aad)
            except Exception:
                self._use_accel = False

        if _BACKEND == "cryptography":
            aesgcm = AESGCM(self._rx_key)
            try:
                return aesgcm.decrypt(nonce, ct, aad or None)
            except Exception as exc:
                raise CryptoError("decryption failed") from exc
        else:  # pycryptodome
            return _pc_aes_gcm_decrypt(self._rx_key, nonce, ct, aad)

    # ------------------------------------------------------------------ #
    # Handshake helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def generate_ephemeral_keypair() -> tuple[bytes, bytes]:
        """Generate an X25519 keypair for the handshake."""
        if _BACKEND is None:
            raise CryptoError("no crypto backend available")
        if _BACKEND == "cryptography":
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
        return _pc_x25519_generate()

    @staticmethod
    def dh_shared_secret(priv_bytes: bytes, peer_pub_bytes: bytes) -> bytes:
        """Compute the X25519 shared secret."""
        if _BACKEND is None:
            raise CryptoError("no crypto backend available")
        if _BACKEND == "cryptography":
            priv = X25519PrivateKey.from_private_bytes(priv_bytes)
            peer_pub = X25519PublicKey.from_public_bytes(peer_pub_bytes)
            return priv.exchange(peer_pub)
        return _pc_x25519_shared(priv_bytes, peer_pub_bytes)

    @property
    def using_accelerator(self) -> bool:
        return self._use_accel
