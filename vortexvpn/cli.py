#!/usr/bin/env python3
"""
vortexvpn — simple command-line interface.

Commands:
  start       start the server in the background
  stop        stop the server
  restart     restart the server
  status      show running state
  logs        tail the log file
  add-user    create a new user interactively
  list-users  list all users
  connect     print the connection info (URL, admin, ports)

Examples:
  vortexvpn start
  vortexvpn add-user
  vortexvpn status

This is just a thin wrapper around scripts/quick-start.sh and the
existing bootstrap/auth modules. It exists so you can remember one
command instead of three.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
SCRIPTS = PROJECT_DIR / "scripts"
QUICK_START = SCRIPTS / "quick-start.sh"


def run_quick_start(arg: str) -> int:
    if not QUICK_START.exists():
        print(f"error: {QUICK_START} not found", file=sys.stderr)
        return 1
    cmd = ["bash", str(QUICK_START), arg] if arg else ["bash", str(QUICK_START)]
    return subprocess.call(cmd, cwd=str(PROJECT_DIR))


def cmd_start(_args) -> int:
    return run_quick_start("start")


def cmd_stop(_args) -> int:
    return run_quick_start("--stop")


def cmd_restart(_args) -> int:
    return run_quick_start("--restart")


def cmd_status(_args) -> int:
    return run_quick_start("--status")


def cmd_logs(_args) -> int:
    return run_quick_start("--logs")


def cmd_connect(_args) -> int:
    """Print connection info from the saved secrets file."""
    secrets = PROJECT_DIR / ".vortex-secrets.env"
    if not secrets.exists():
        print("no secrets found — run `vortexvpn start` first")
        return 1
    # Read without importing (avoids venv detection issues)
    admin_user = admin_pass = web_secret = ""
    for line in secrets.read_text().splitlines():
        if line.startswith("VORTEX_ADMIN_USER="):
            admin_user = line.split("=", 1)[1]
        elif line.startswith("VORTEX_ADMIN_PASS="):
            admin_pass = line.split("=", 1)[1]
        elif line.startswith("VORTEX_WEB_SECRET="):
            web_secret = line.split("=", 1)[1]

    # Get local IP
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
    except OSError:
        local_ip = "127.0.0.1"
    finally:
        s.close()

    # Read port from config
    web_port = 8080
    tunnel_port = 4433
    cfg = PROJECT_DIR / "configs" / "config.toml"
    if cfg.exists():
        try:
            import tomllib
            with cfg.open("rb") as fh:
                c = tomllib.load(fh)
            web_port = c.get("web", {}).get("port", web_port)
            tunnel_port = c.get("tunnel", {}).get("listen_port", tunnel_port)
        except Exception:
            pass

    print()
    print("═" * 56)
    print("            VortexVPN connection info")
    print("═" * 56)
    print(f"  Web panel:  http://{local_ip}:{web_port}")
    print(f"              http://localhost:{web_port}")
    print(f"  Username:   {admin_user}")
    print(f"  Password:   {admin_pass}")
    print(f"  Tunnel UDP: {tunnel_port}")
    print()
    print("  On your phone, open the web panel URL in a browser,")
    print("  log in, and click 'كيفاش تربط هاتف' for setup steps.")
    print("═" * 56)
    print()
    return 0


def cmd_add_user(args) -> int:
    """Create a new user."""
    sys.path.insert(0, str(PROJECT_DIR))
    from vortexvpn.core.auth import AuthManager, AuthError
    from vortexvpn.core.config import load_config

    cfg = load_config()
    auth = AuthManager(hmac_secret=cfg.web.secret_key.encode("utf-8"))

    username = args.username
    if not username:
        username = input("username: ").strip()
    import getpass
    password = args.password or getpass.getpass("password (min 8 chars): ")
    is_admin = args.admin

    try:
        user = auth.create_user(username, password, is_admin=is_admin)
    except AuthError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"created user '{user.username}' (id={user.id}, admin={user.is_admin})")
    return 0


def cmd_list_users(_args) -> int:
    sys.path.insert(0, str(PROJECT_DIR))
    from vortexvpn.core.auth import AuthManager
    from vortexvpn.core.config import load_config

    cfg = load_config()
    auth = AuthManager(hmac_secret=cfg.web.secret_key.encode("utf-8"))
    users = auth.list_users()
    if not users:
        print("(no users yet)")
        return 0
    print(f"{'id':<4} {'username':<20} {'admin':<6} {'active':<7} {'used (B)':<12} {'quota (B)':<12}")
    for u in users:
        print(f"{u.id:<4} {u.username:<20} "
              f"{'yes' if u.is_admin else 'no':<6} "
              f"{'yes' if u.is_active else 'no':<7} "
              f"{u.bandwidth_used_bytes:<12} {u.bandwidth_quota_bytes:<12}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(
        prog="vortexvpn",
        description="VortexVPN simple CLI — one command to rule them all.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("start", help="start the server (background)").set_defaults(func=cmd_start)
    sub.add_parser("stop", help="stop the server").set_defaults(func=cmd_stop)
    sub.add_parser("restart", help="restart the server").set_defaults(func=cmd_restart)
    sub.add_parser("status", help="show running state").set_defaults(func=cmd_status)
    sub.add_parser("logs", help="tail the log file").set_defaults(func=cmd_logs)
    sub.add_parser("connect", help="print connection info (URL, admin, ports)").set_defaults(func=cmd_connect)

    p_user = sub.add_parser("add-user", help="create a new user")
    p_user.add_argument("--username", "-u", help="username (prompted if omitted)")
    p_user.add_argument("--password", "-p", help="password (prompted if omitted)")
    p_user.add_argument("--admin", action="store_true", help="make this user an admin")
    p_user.set_defaults(func=cmd_add_user)

    sub.add_parser("list-users", help="list all users").set_defaults(func=cmd_list_users)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
