"""
Configuration loader for VortexVPN.

Supports YAML and TOML configuration files, with environment variable
overrides for secret values (private keys, database passwords, etc.).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, Optional

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover - fallback for older pythons
    import tomli as tomllib  # type: ignore


DEFAULT_CONFIG_PATHS = [
    "/etc/vortexvpn/config.toml",
    "~/.vortexvpn/config.toml",
    "./configs/config.toml",
]


@dataclass
class TunnelConfig:
    """Tunnel subsystem settings."""

    listen_host: str = "0.0.0.0"
    listen_port: int = 4433
    mtu: int = 1400
    cipher: str = "aes-256-gcm"
    kdf: str = "argon2id"
    handshake_timeout: float = 10.0
    session_ttl: int = 3600
    max_clients: int = 256
    worker_threads: int = 4
    virtual_subnet: str = "10.99.0.0/24"
    dns_servers: list = field(default_factory=lambda: ["1.1.1.1", "9.9.9.9"])


@dataclass
class WebConfig:
    """Web panel settings."""

    host: str = "127.0.0.1"
    port: int = 8080
    secret_key: str = "change-me-in-production"
    database_url: str = "sqlite:///vortexvpn.db"
    debug: bool = False
    cors_origins: list = field(default_factory=lambda: ["http://localhost:8080"])
    session_cookie_secure: bool = True
    # Public URL (set when running behind a reverse proxy with HTTPS).
    # Shown on the /connect page and used in QR codes.
    public_url: str = ""
    # Hidden admin login path. Default is "/admin/login" but you should
    # change it to something unpredictable like "/x7k2m-admin" for
    # extra security-through-obscurity on top of auth.
    admin_path: str = "/admin/login"


@dataclass
class MonitorConfig:
    """Java monitor service settings."""

    enabled: bool = True
    stats_socket: str = "/var/run/vortexvpn/monitor.sock"
    sample_interval_ms: int = 1000
    history_size: int = 3600


@dataclass
class SecurityConfig:
    """Hardening & rate-limiting."""

    fail2ban_threshold: int = 5
    fail2ban_window_s: int = 300
    fail2ban_ban_s: int = 3600
    tls_required: bool = True
    cert_path: str = "/etc/vortexvpn/certs/server.crt"
    key_path: str = "/etc/vortexvpn/certs/server.key"


@dataclass
class Config:
    """Top-level configuration container."""

    tunnel: TunnelConfig = field(default_factory=TunnelConfig)
    web: WebConfig = field(default_factory=WebConfig)
    monitor: MonitorConfig = field(default_factory=MonitorConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    log_level: str = "INFO"
    log_file: str = "/var/log/vortexvpn/vortexvpn.log"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _apply_env_overrides(cfg: Config) -> Config:
    """Apply environment variable overrides for sensitive fields."""
    if val := os.environ.get("VORTEX_WEB_SECRET"):
        cfg.web.secret_key = val
    if val := os.environ.get("VORTEX_DB_URL"):
        cfg.web.database_url = val
    if val := os.environ.get("VORTEX_TUNNEL_PORT"):
        cfg.tunnel.listen_port = int(val)
    if val := os.environ.get("VORTEX_LOG_LEVEL"):
        cfg.log_level = val.upper()
    if val := os.environ.get("VORTEX_TUNNEL_CIPHER"):
        cfg.tunnel.cipher = val
    if val := os.environ.get("VORTEX_MAX_CLIENTS"):
        cfg.tunnel.max_clients = int(val)
    if val := os.environ.get("VORTEX_PUBLIC_URL"):
        cfg.web.public_url = val
    if val := os.environ.get("VORTEX_ADMIN_PATH"):
        cfg.web.admin_path = val
    return cfg


def load_config(path: Optional[str] = None) -> Config:
    """
    Load configuration from the given path, or from the first default
    path that exists. Environment variables override file values.
    """
    cfg = Config()
    resolved: Optional[Path] = None

    if path:
        resolved = Path(path).expanduser()
    else:
        for candidate in DEFAULT_CONFIG_PATHS:
            p = Path(candidate).expanduser()
            if p.exists():
                resolved = p
                break

    if resolved and resolved.exists():
        with resolved.open("rb") as fh:
            data = tomllib.load(fh)
        if "tunnel" in data:
            for k, v in data["tunnel"].items():
                setattr(cfg.tunnel, k, v)
        if "web" in data:
            for k, v in data["web"].items():
                setattr(cfg.web, k, v)
        if "monitor" in data:
            for k, v in data["monitor"].items():
                setattr(cfg.monitor, k, v)
        if "security" in data:
            for k, v in data["security"].items():
                setattr(cfg.security, k, v)
        for k in ("log_level", "log_file"):
            if k in data:
                setattr(cfg, k, data[k])

    return _apply_env_overrides(cfg)
