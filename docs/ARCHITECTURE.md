# Architecture reference

This document is the deep-dive companion to `README.md`. Read it when you
need to understand *why* a decision was made, not just *what* the code does.

## 1. Design goals

| Goal                  | How it's met                                                   |
|-----------------------|----------------------------------------------------------------|
| Strong crypto         | AES-256-GCM AEAD; X25519 ECDH; HKDF or Argon2id KDF            |
| Low latency           | UDP transport; per-frame nonce; optional C++ hot path          |
| Operational simplicity| Single Python process + optional Java sidecar; one config file |
| Safe defaults         | Argon2id for passwords; fail2ban-style rate limit on by default|
| Testable              | Pure-Python crypto fallback; in-process fakes; 32 pytest cases |
| Multi-language        | Python for product, C++ for speed, Java for monitoring, Shell  |

## 2. Threading & concurrency model

The Python tunnel server is **asyncio-based**, using a single event loop
for all UDP I/O. The handshake is O(1) per packet; data packets are
encrypted/decrypted inline.

The Flask web panel runs in a **separate thread** with its own asyncio
loop, so the web UI never blocks the tunnel. They communicate via the
shared `TunnelServer` object, which exposes a thread-safe `stats()`
method (snapshot the dict; no lock contention).

The Java monitor is a separate OS process that reads `/proc/*` and
publishes to subscribers over TCP. It has no shared state with Python.

```
┌─────────────┐    ┌───────────────────────────┐    ┌──────────────┐
│ async loop  │    │ Flask thread + own loop   │    │ Java process │
│ (UDP tunnel)│    │ (HTTP + tunnel controller)│    │ (TCP 9101)   │
└─────────────┘    └───────────────────────────┘    └──────────────┘
       ▲                       ▲                          ▲
       └─────────── shared TunnelServer.stats() ──────────┘
                       (read-only snapshot)
```

## 3. Crypto decisions

### 3.1 Why AES-256-GCM, not ChaCha20-Poly1305?

Both are excellent. AES-GCM was chosen because:

1. The C++ accelerator can use OpenSSL's hardware-accelerated AES-NI
   path, which is faster than any portable ChaCha20 implementation on
   modern x86_64 servers.
2. `cryptography` library's `AESGCM` returns `ciphertext || tag` as a
   single buffer, simplifying frame layout.
3. AES-256-GCM is widely audited and FIPS-acceptable.

ChaCha20-Poly1305 would be a reasonable alternative for ARM/Android
clients where AES-NI is unavailable. Pull requests welcome.

### 3.2 Why per-frame counter nonces?

GCM is catastrophically broken under nonce reuse. We use a 96-bit
counter encoded big-endian, monotonically increasing per session per
direction. A 64-bit counter would overflow after 2^64 frames; a 96-bit
counter at 1M frames/sec lasts ~2.5e22 years. Sufficient.

The nonce is **not** random because random nonces risk birthday
collisions after ~2^48 frames per key. Counter nonces are safe as
long as keys are unique per session — which the X25519 handshake
guarantees.

### 3.3 Why directional keys?

If both peers used the same key for send and receive, a reflected
packet (attacker captures client→server frame, replays it as
server→client) would decrypt successfully. Directional keys prevent
this: the reflected frame uses the wrong key, fails AEAD, and is
dropped.

### 3.4 What's missing from the handshake?

The current handshake authenticates the **channel** (via DH) but not
the **user** — anyone with the server's public key can establish a
session. Production deployment must add:

1. A client HMAC over `(client_nonce || server_nonce || username)`
   using a key derived from the user's password.
2. Server-side verification of that HMAC before issuing the
   `HANDSHAKE_REPLY`.
3. A `HANDSHAKE_FINISH` message from the client to confirm key
   confirmation (defense against MITM).

These are clearly marked in `tunnel_server.py::_handle_handshake`
with a NOTE comment. The web panel's auth (login flow) **is** fully
implemented with Argon2id + HMAC tokens.

## 4. Database schema

A single SQLite file (`vortexvpn.db`) holds the `users` table:

```sql
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash BLOB NOT NULL,            -- Argon2id output
    salt BLOB NOT NULL,                     -- 16 bytes
    is_admin INTEGER DEFAULT 0,
    is_active INTEGER DEFAULT 1,
    created_at REAL NOT NULL,
    bandwidth_quota_bytes INTEGER DEFAULT 0,
    bandwidth_used_bytes INTEGER DEFAULT 0,
    expires_at REAL                          -- NULL = no expiry
);
```

To migrate to PostgreSQL, replace `_connect()` in `auth.py` with a
`psycopg`/`asyncpg` pool — the SQL is portable.

## 5. Web panel auth flow

```
Browser ──POST /login {user, pw}──> Server
                                     │
                                     ▼
                       auth.authenticate(user, pw)
                       └─ Argon2id verify, fail2ban check
                                     │
                                     ▼
                       auth.issue_token(user, ttl=3600)
                       └─ HMAC(user.ts.exp, secret)
                                     │
                                     ▼
                       Set-Cookie: session=token_string
Browser <──302 /─────────────────── Server

Browser ──GET /api/v1/stats─────────> Server
Cookie: session=token_string           │
                                     ▼
                       auth.verify_token(token_string)
                       └─ constant-time HMAC compare
                                     │
                                     ▼
                       tunnel.stats() snapshot
Browser <──200 JSON────────────────── Server
```

Tokens are **stateless**: no DB lookup per request. Revocation requires
rotating `web.secret_key` (forces everyone to re-login) or adding a
server-side blocklist (future work).

## 6. Failure modes

| Failure                         | Behavior                                                    |
|---------------------------------|-------------------------------------------------------------|
| C++ accelerator unavailable     | Falls back to `cryptography` library (transparent)         |
| TUN device unavailable          | Server runs in "socket-only" mode (handshake + crypto only)|
| SQLite locked                   | Auth call raises `AuthError`; user sees 500                 |
| Malformed UDP packet            | Logged at WARNING, dropped silently                        |
| Bad magic byte                  | `ProtocolError`, logged, dropped                            |
| AEAD auth failure               | `CryptoError`, logged, dropped                              |
| Client idle > 120s              | Session reaped, virtual IP returned to pool                |
| Too many failed logins          | Username banned for `fail2ban_ban_s`                       |
| Token expired                   | Cookie cleared, redirect to /login                         |
| Non-admin hits admin endpoint   | 403 JSON                                                    |

## 7. Performance characteristics

Measured on a single-core VM (2.4 GHz, no AES-NI in this env):

| Operation              | Pure Python | C++ accelerator |
|------------------------|-------------|-----------------|
| AES-256-GCM seal (1KB) | ~120k/s     | ~750k/s         |
| AES-256-GCM open (1KB) | ~120k/s     | ~750k/s         |
| Argon2id hash (3 iter) | ~3/s        | n/a (lib)       |

On real hardware with AES-NI, expect **5–10×** these numbers.

## 8. Extension points

- **Add a new cipher**: implement `seal`/`open` in `CryptoEngine`, add
  config validation in `TunnelConfig.cipher`.
- **Add a new auth backend**: subclass `AuthManager`, override `_connect`
  and the SQL.
- **Add WebSocket live updates**: replace the 3-second polling in
  `dashboard.js` with a Flask-SocketIO event sourced from
  `TunnelServer.stats()`.
- **Add WireGuard compatibility**: write a `wireguard_compat.py` that
  translates VortexVPN packets to/from WireGuard's Noise protocol. Not
  trivial, but doable.
