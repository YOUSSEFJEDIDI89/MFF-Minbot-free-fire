"""
Authentication & session management for VortexVPN.

Provides:
  - User storage with Argon2id password hashing
  - Token issuance (HMAC-signed, stateless)
  - Rate limiting (fail2ban-style)
  - SQLite backend (swappable for PostgreSQL)
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

try:
    from argon2.low_level import hash_secret_raw, Type as Argon2Type
    _HAS_ARGON2 = True
except ImportError:
    _HAS_ARGON2 = False


DEFAULT_DB_PATH = str(Path.home() / ".vortexvpn" / "auth.db")
TOKEN_TTL = 3600          # 1 hour for web tokens
SESSION_TTL = 86400       # 24 hour for tunnel sessions


class AuthError(Exception):
    """Raised on invalid credentials, expired tokens, banned clients."""


@dataclass
class User:
    id: int
    username: str
    password_hash: bytes
    salt: bytes
    is_admin: bool = False
    is_active: bool = True
    created_at: float = field(default_factory=time.time)
    bandwidth_quota_bytes: int = 0    # 0 = unlimited
    bandwidth_used_bytes: int = 0
    expires_at: Optional[float] = None  # None = no expiry


@dataclass
class Token:
    username: str
    issued_at: float
    expires_at: float
    signature: bytes

    def to_string(self) -> str:
        """Encode token as username.timestamp.signature (urlsafe)."""
        from base64 import urlsafe_b64encode
        payload = f"{self.username}.{int(self.issued_at)}.{int(self.expires_at)}"
        sig_b64 = urlsafe_b64encode(self.signature).rstrip(b"=").decode("ascii")
        return f"{payload}.{sig_b64}"


class AuthManager:
    """
    SQLite-backed auth manager. Thread-safe via a per-call connection;
    for high-throughput deployments, swap _connect() for a pool.
    """

    def __init__(self, db_path: str = DEFAULT_DB_PATH,
                 hmac_secret: Optional[bytes] = None) -> None:
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._hmac_secret = hmac_secret or secrets.token_bytes(32)
        self._init_schema()
        self._failed_attempts: dict[str, list[float]] = {}
        self._banned_until: dict[str, float] = {}

    # ------------------------------------------------------------------ #
    # DB plumbing
    # ------------------------------------------------------------------ #
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password_hash BLOB NOT NULL,
                    salt BLOB NOT NULL,
                    is_admin INTEGER DEFAULT 0,
                    is_active INTEGER DEFAULT 1,
                    created_at REAL NOT NULL,
                    bandwidth_quota_bytes INTEGER DEFAULT 0,
                    bandwidth_used_bytes INTEGER DEFAULT 0,
                    expires_at REAL
                );
                CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
            """)

    # ------------------------------------------------------------------ #
    # Password hashing
    # ------------------------------------------------------------------ #
    @staticmethod
    def _hash_password(password: str, salt: bytes) -> bytes:
        if _HAS_ARGON2:
            return hash_secret_raw(
                secret=password.encode("utf-8"),
                salt=salt,
                time_cost=3,
                memory_cost=65536,
                parallelism=2,
                hash_len=32,
                type=Argon2Type.ID,
            )
        # Fallback: PBKDF2-HMAC-SHA256
        return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000, 32)

    # ------------------------------------------------------------------ #
    # User CRUD
    # ------------------------------------------------------------------ #
    def create_user(self, username: str, password: str, *,
                    is_admin: bool = False,
                    bandwidth_quota_bytes: int = 0,
                    expires_at: Optional[float] = None) -> User:
        if not username or len(username) > 64:
            raise AuthError("invalid username")
        if len(password) < 8:
            raise AuthError("password must be at least 8 characters")
        salt = secrets.token_bytes(16)
        pw_hash = self._hash_password(password, salt)
        with self._connect() as conn:
            try:
                cur = conn.execute(
                    """INSERT INTO users
                       (username, password_hash, salt, is_admin, is_active,
                        created_at, bandwidth_quota_bytes, bandwidth_used_bytes,
                        expires_at)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (username, pw_hash, salt, int(is_admin), 1,
                     time.time(), bandwidth_quota_bytes, 0, expires_at),
                )
            except sqlite3.IntegrityError as exc:
                raise AuthError("username already exists") from exc
            user_id = cur.lastrowid
        return User(id=user_id, username=username, password_hash=pw_hash,
                    salt=salt, is_admin=is_admin, is_active=True,
                    created_at=time.time(),
                    bandwidth_quota_bytes=bandwidth_quota_bytes,
                    expires_at=expires_at)

    def _row_to_user(self, row: sqlite3.Row) -> User:
        return User(
            id=row["id"], username=row["username"],
            password_hash=row["password_hash"], salt=row["salt"],
            is_admin=bool(row["is_admin"]), is_active=bool(row["is_active"]),
            created_at=row["created_at"],
            bandwidth_quota_bytes=row["bandwidth_quota_bytes"],
            bandwidth_used_bytes=row["bandwidth_used_bytes"],
            expires_at=row["expires_at"],
        )

    def get_user(self, username: str) -> Optional[User]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE username = ?", (username,)
            ).fetchone()
        return self._row_to_user(row) if row else None

    def list_users(self) -> list[User]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM users ORDER BY id").fetchall()
        return [self._row_to_user(r) for r in rows]

    def delete_user(self, username: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM users WHERE username = ?", (username,))
            return cur.rowcount > 0

    def set_active(self, username: str, is_active: bool) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE users SET is_active = ? WHERE username = ?",
                (int(is_active), username),
            )
            return cur.rowcount > 0

    def add_bandwidth_used(self, username: str, n_bytes: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE users SET bandwidth_used_bytes = bandwidth_used_bytes + ? "
                "WHERE username = ?",
                (n_bytes, username),
            )

    # ------------------------------------------------------------------ #
    # Login / token issuance
    # ------------------------------------------------------------------ #
    def _check_ban(self, username: str, threshold: int, window_s: int,
                   ban_s: int) -> None:
        now = time.time()
        banned_until = self._banned_until.get(username, 0)
        if banned_until > now:
            raise AuthError(f"temporarily banned, retry in {int(banned_until - now)}s")
        # Purge old failures
        self._failed_attempts[username] = [
            t for t in self._failed_attempts.get(username, [])
            if now - t < window_s
        ]
        if len(self._failed_attempts[username]) >= threshold:
            self._banned_until[username] = now + ban_s
            self._failed_attempts[username] = []
            raise AuthError("too many failed attempts, temporarily banned")

    def authenticate(self, username: str, password: str,
                     *, threshold: int = 5, window_s: int = 300,
                     ban_s: int = 3600) -> User:
        """Verify credentials. Raises AuthError on failure."""
        self._check_ban(username, threshold, window_s, ban_s)
        user = self.get_user(username)
        if not user or not user.is_active:
            self._failed_attempts.setdefault(username, []).append(time.time())
            raise AuthError("invalid credentials")
        if user.expires_at is not None and user.expires_at < time.time():
            raise AuthError("account expired")
        candidate = self._hash_password(password, user.salt)
        if not hmac.compare_digest(candidate, user.password_hash):
            self._failed_attempts.setdefault(username, []).append(time.time())
            raise AuthError("invalid credentials")
        self._failed_attempts.pop(username, None)
        self._banned_until.pop(username, None)
        return user

    def issue_token(self, user: User, ttl: int = TOKEN_TTL) -> Token:
        now = time.time()
        expires = now + ttl
        payload = f"{user.username}.{int(now)}.{int(expires)}".encode("ascii")
        sig = hmac.new(self._hmac_secret, payload, hashlib.sha256).digest()
        return Token(username=user.username, issued_at=now,
                     expires_at=expires, signature=sig)

    def verify_token(self, token_str: str) -> User:
        """Verify a token string. Raises AuthError if invalid/expired."""
        try:
            username, issued_s, expires_s, sig_b64 = token_str.split(".")
            from base64 import urlsafe_b64decode
            sig = urlsafe_b64decode(sig_b64 + "=" * (-len(sig_b64) % 4))
        except (ValueError, Exception):
            raise AuthError("malformed token")
        if time.time() > int(expires_s):
            raise AuthError("token expired")
        payload = f"{username}.{issued_s}.{expires_s}".encode("ascii")
        expected = hmac.new(self._hmac_secret, payload, hashlib.sha256).digest()
        if not hmac.compare_digest(sig, expected):
            raise AuthError("invalid signature")
        user = self.get_user(username)
        if not user or not user.is_active:
            raise AuthError("user not found or inactive")
        return user

    # ------------------------------------------------------------------ #
    # Bootstrap
    # ------------------------------------------------------------------ #
    def ensure_admin(self, username: str = "admin",
                     password: Optional[str] = None) -> str:
        """Create the admin user if missing; return its password."""
        existing = self.get_user(username)
        if existing:
            return "(already exists)"
        pw = password or secrets.token_urlsafe(16)
        self.create_user(username, pw, is_admin=True)
        return pw
