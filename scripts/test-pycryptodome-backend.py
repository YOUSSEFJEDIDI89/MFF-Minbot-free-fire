"""Test the pycryptodome backend by hiding cryptography."""
from __future__ import annotations

import os
import sys

# Block cryptography import to force pycryptodome path
import builtins
_real_import = builtins.__import__
def _blocked_import(name, *args, **kwargs):
    if name == "cryptography" or name.startswith("cryptography."):
        raise ImportError(f"blocked for test: {name}")
    return _real_import(name, *args, **kwargs)
builtins.__import__ = _blocked_import

# Force re-import of crypto module
for mod in list(sys.modules):
    if "vortexvpn" in mod or "crypto" in mod.lower():
        del sys.modules[mod]

# Make project importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vortexvpn.core.crypto import get_backend, CryptoEngine, KeyDerivation, CryptoError  # noqa

print(f"Active backend: {get_backend()}")
assert get_backend() == "pycryptodome", f"expected pycryptodome, got {get_backend()}"

# Test keypair generation
priv1, pub1 = CryptoEngine.generate_ephemeral_keypair()
priv2, pub2 = CryptoEngine.generate_ephemeral_keypair()
print(f"keypair 1: priv={len(priv1)}B, pub={len(pub1)}B")

# Test DH
shared_at_1 = CryptoEngine.dh_shared_secret(priv1, pub2)
shared_at_2 = CryptoEngine.dh_shared_secret(priv2, pub1)
assert shared_at_1 == shared_at_2, "DH shared secret mismatch!"
print(f"DH shared secret: {shared_at_1.hex()[:32]}...")

# Test AES-GCM round trip
secret = os.urandom(32)
kdf = KeyDerivation.generate()
client = CryptoEngine(); client.derive_session_keys(secret, kdf,
    b"\x01" * 16, b"\x02" * 16, role="client")
server = CryptoEngine(); server.derive_session_keys(secret, kdf,
    b"\x01" * 16, b"\x02" * 16, role="server")

plaintext = b"VortexVPN pycryptodome backend test " * 10
frame = client.seal(plaintext, aad=b"hdr")
recovered = server.open(frame, aad=b"hdr")
assert recovered == plaintext, "round trip failed"
print(f"AES-GCM round-trip OK: {len(plaintext)}B encrypted → {len(frame)}B → recovered")

# Test tamper detection
frame2 = bytearray(client.seal(b"secret", aad=b""))
frame2[20] ^= 0x01
try:
    server.open(bytes(frame2), aad=b"")
    print("FAIL: tamper not detected!")
    sys.exit(1)
except CryptoError:
    print("Tamper detection OK")

# Test bidirectional
cs = client.seal(b"client to server")
assert server.open(cs) == b"client to server"
sc = server.seal(b"server to client")
assert client.open(sc) == b"server to client"
print("Bidirectional OK")

print("\nAll pycryptodome backend tests passed.")
