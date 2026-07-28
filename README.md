# VortexVPN ⚡

**A high-performance, multi-language VPN server platform built with Python, C++, Java, and Shell.**

[![Tests](https://img.shields.io/badge/tests-32%2F32%20passing-brightgreen)](#tests)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

> ⚠️ **Ethics & scope.** VortexVPN is a **legitimate** VPN server for
> privacy protection, secure remote access, and networking education.
> It is **not** a tool to cheat in online games, bypass anti-cheat,
> manipulate other players' connections, or violate any service's
> terms of use. Misuse is against the project's license and ethics.

---

## ✨ Features

- **Multi-language architecture**
  - 🐍 **Python** — tunnel core, web panel, auth, config
  - ⚙️ **C++** — AES-256-GCM accelerator via pybind11 (measured **~1 GB/s** on commodity hardware)
  - ☕ **Java** — real-time traffic / CPU / memory monitor with TCP JSON streaming
  - 🐚 **Shell** — installer, service manager, dev launcher
- **Strong cryptography**
  - AES-256-GCM authenticated encryption for every tunnel packet
  - X25519 ECDH key exchange
  - HKDF-SHA256 or Argon2id key derivation
  - Argon2id password hashing for stored credentials
- **Web control panel** (Flask)
  - Arabic-first RTL UI with dark theme
  - Login / logout with HMAC-signed stateless tokens
  - Admin user CRUD with bandwidth quota tracking
  - Live client list with auto-refresh
  - Session kick / ban / unban
  - Settings viewer
- **Security hardening**
  - fail2ban-style rate limiting (configurable threshold / window / ban time)
  - Session reaping for idle clients
  - Per-client virtual IP pool
  - Replay protection via per-frame nonces
- **Production-ready**
  - Docker multi-stage build (slim runtime image)
  - docker-compose with healthcheck
  - JSON structured logging with rotation
  - systemd-friendly service script
  - 32 pytest tests, all passing

---

## 🏗️ Architecture

```
┌────────────────────────────────────────────────────────────────┐
│                         Client (TUN)                            │
│  vortexvpn/core/tunnel_client.py                               │
└──────────────┬─────────────────────────────────────────────────┘
               │ UDP, AES-256-GCM, X25519 handshake
               ▼
┌────────────────────────────────────────────────────────────────┐
│                      VortexVPN Server                          │
│  vortexvpn/core/tunnel_server.py   (asyncio UDP)               │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────┐  │
│  │ CryptoEngine     │  │ AuthManager      │  │ Protocol     │  │
│  │ (AES-GCM, HKDF)  │  │ (SQLite+Argon2)  │  │ (1B hdr+pay) │  │
│  └────────┬─────────┘  └──────────────────┘  └──────────────┘  │
│           │ calls C++ accelerator when available                │
│           ▼                                                     │
│  cpp_module/vortex_accel.cpp  (OpenSSL EVP, pybind11)          │
└──────────────┬─────────────────────────────────────────────────┘
               │ exposes /api/v1/stats
               ▼
┌────────────────────────────────────────────────────────────────┐
│                    Web Panel (Flask, port 8080)                │
│  vortexvpn/web/app.py + templates/ + static/                  │
│  - Login (Argon2id verify)                                     │
│  - Dashboard (live clients, traffic, kick)                     │
│  - Users CRUD (admin only)                                     │
│  - Settings viewer                                             │
└──────────────┬─────────────────────────────────────────────────┘
               │ TCP JSON stream (one object per second)
               ▼
┌────────────────────────────────────────────────────────────────┐
│              Java Monitor (port 9101, optional)                │
│  java_monitor/VortexMonitor.java                              │
│  - Reads /proc/net/dev, /proc/stat, /proc/meminfo             │
│  - Publishes rx/tx bps, pps, CPU%, mem% to all subscribers     │
└────────────────────────────────────────────────────────────────┘
```

### Packet wire format

```
+----+----+----+----+----+----+----+----+----+----+----+----+
| 0x01 magic | type (1B) | flags (1B) | payload-len (4B BE)  |
+----+----+----+----+----+----+----+----+----+----+----+----+
|                       payload (variable)                  |
+-----------------------------------------------------------+
```

The full frame is then encrypted with AES-256-GCM, producing
`nonce(12B) || ciphertext || tag(16B)` on the wire.

### Directional key derivation

Both peers derive the same 64-byte `base` from the handshake shared
secret + nonces. They then assign opposite halves:

| Peer   | tx_key        | rx_key        |
|--------|---------------|---------------|
| Client | `base[32:]`   | `base[:32]`   |
| Server | `base[:32]`   | `base[32:]`   |

So `client.tx_key == server.rx_key` and `server.tx_key == client.rx_key`.

---

## 🚀 Quick start

### Option A — Docker (recommended for evaluation)

```bash
git clone https://github.com/YOUSSEFJEDIDI89/MFF-Minbot-free-fire.git
cd MFF-Minbot-free-fire
cp configs/config.toml.example configs/config.toml
# edit configs/config.toml: set a long random web.secret_key
docker compose -f docker/docker-compose.yml up -d --build
docker compose -f docker/docker-compose.yml exec vortexvpn \
    python -m vortexvpn.bootstrap   # prints admin password
```

Open <http://localhost:8080> and log in with `admin` + printed password.

### Option B — Bare-metal install (Linux)

```bash
git clone https://github.com/YOUSSEFJEDIDI89/MFF-Minbot-free-fire.git
cd MFF-Minbot-free-fire
sudo ./scripts/install.sh
sudo $EDITOR /etc/vortexvpn/config.toml          # set secret_key
/opt/vortexvpn/venv/bin/python -m vortexvpn.bootstrap
/opt/vortexvpn/scripts/manage.sh start
```

### Option C — Dev mode (no root, no TUN)

```bash
git clone https://github.com/YOUSSEFJEDIDI89/MFF-Minbot-free-fire.git
cd MFF-Minbot-free-fire
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
pip install pybind11
( cd cpp_module && make )               # optional, builds accelerator
./scripts/start-dev.sh                  # foreground, logs to stderr
```

---

## 🧪 Tests

```bash
source venv/bin/activate
pytest -v
```

Expected output:

```
============================== 32 passed in ~3s ==============================
```

Coverage:

| Suite            | Tests | What it verifies                                  |
|------------------|-------|---------------------------------------------------|
| `test_crypto.py` | 6     | AES-GCM round-trip, tamper detection, AAD, nonces |
| `test_protocol.py` | 7   | Packet serialize/deserialize, bad magic, truncation |
| `test_auth.py`   | 10    | CRUD, Argon2 verify, tokens, fail2ban, bandwidth  |
| `test_tunnel.py` | 2     | UDP server start/stop, max-clients enforcement    |
| `test_web_api.py`| 7     | Login flow, RBAC, stats/users/kick endpoints      |

---

## 📁 Project layout

```
vortexvpn/
├── vortexvpn/                  # Python package
│   ├── __init__.py
│   ├── __main__.py             # `python -m vortexvpn.web`
│   ├── bootstrap.py            # one-shot admin user creation
│   ├── core/
│   │   ├── config.py           # TOML + env-var config loader
│   │   ├── crypto.py           # AES-GCM + X25519 + HKDF/Argon2id
│   │   ├── protocol.py         # wire format
│   │   ├── auth.py             # SQLite user store + tokens + fail2ban
│   │   ├── tunnel_server.py    # async UDP server
│   │   └── tunnel_client.py    # async UDP client
│   ├── web/
│   │   ├── app.py              # Flask factory + routes + API
│   │   ├── templates/          # dashboard.html, login.html, users.html, settings.html
│   │   └── static/             # main.css, dashboard.js, users.js
│   ├── utils/
│   │   ├── logging.py          # JSON structured logging
│   │   └── net.py              # TUN wrapper, CIDR helpers
│   └── api/
├── cpp_module/
│   ├── vortex_accel.cpp        # OpenSSL AES-GCM + SHA-256 via pybind11
│   └── Makefile                # `make`, `make test`, `make install`
├── java_monitor/
│   ├── VortexMonitor.java      # /proc readers + TCP JSON publisher
│   └── run.sh                  # build / start / stop / logs
├── scripts/
│   ├── install.sh              # distro-aware installer (deb/fed/rhel)
│   ├── manage.sh               # start/stop/restart/status/logs
│   └── start-dev.sh            # foreground dev launcher
├── tests/                      # pytest suite (32 tests)
├── docker/
│   ├── Dockerfile              # multi-stage: build C++ → slim runtime
│   └── docker-compose.yml      # web + tunnel + monitor
├── configs/
│   └── config.toml.example     # documented configuration template
├── docs/
│   └── ARCHITECTURE.md
├── requirements.txt
├── pytest.ini
├── .dockerignore
├── .gitignore
├── LICENSE
└── README.md
```

---

## 🔧 Configuration

All settings live in `configs/config.toml` (TOML). Environment variables
prefixed with `VORTEX_` override file values — useful for Docker / CI.

| Section  | Key                       | Default                 | Notes                                |
|----------|---------------------------|-------------------------|--------------------------------------|
| tunnel   | listen_port               | 4433                    | UDP port                             |
| tunnel   | cipher                    | `aes-256-gcm`           | Only AEAD ciphers are safe           |
| tunnel   | kdf                       | `hkdf-sha256`           | `argon2id` available                 |
| tunnel   | max_clients               | 256                     | Hard cap                             |
| tunnel   | virtual_subnet            | `10.99.0.0/24`          | Pool for client IPs                  |
| web      | port                      | 8080                    | HTTP port                            |
| web      | secret_key                | **CHANGE ME**           | Used for HMAC tokens & session cookie |
| web      | session_cookie_secure     | false                   | Set `true` behind HTTPS              |
| monitor  | sample_interval_ms        | 1000                    | Java poll cadence                    |
| security | fail2ban_threshold        | 5                       | Failed logins before ban             |
| security | fail2ban_ban_s            | 3600                    | Ban duration                         |
| (top)    | log_level                 | `INFO`                  | `DEBUG` / `WARNING` / `ERROR`        |

---

## 🛡️ Security notes

- **Token storage**: HMAC-signed, stateless — no DB lookup per request
- **Password storage**: Argon2id (memory-hard) — fallback PBKDF2-SHA256 (200k iters)
- **Wire encryption**: AES-256-GCM with 96-bit per-frame counter nonce
- **Handshake**: X25519 ECDH + HKDF/Argon2id derivation
- **Anti-replay**: counter-based nonces; never reused within a session
- **Rate limiting**: fail2ban-style per-username; can be extended to per-IP via `fail2ban` integration
- **TLS**: not bundled — terminate TLS at a reverse proxy (Caddy, nginx, Traefik)

### What VortexVPN does NOT do

- It does **not** improve game performance. VPNs route traffic; they don't
  offload computation from your device.
- It does **not** bypass game anti-cheat. Any tool claiming to do so is
  malware or a scam.
- It does **not** let one device "borrow" another device's CPU/GPU.

---

## 📜 License

MIT © VortexVPN Contributors. See [LICENSE](LICENSE).

---

## 🤝 Contributing

1. Fork → feature branch (`feat/my-feature`)
2. Add tests for any new behavior
3. `pytest -v` must pass
4. Open PR with a clear description

Please do **not** open PRs that add game-cheating functionality — they
will be rejected and the reporter banned from the project.
