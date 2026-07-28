"""Bootstrap script: create config + admin user, print credentials.

Reads VORTEX_ADMIN_USER, VORTEX_ADMIN_PASS, VORTEX_WEB_SECRET from
environment (set by quick-start.sh). If not set, generates fresh
random values and prints them once.
"""
from __future__ import annotations

import os
import secrets
import sys

from vortexvpn.core.auth import AuthManager
from vortexvpn.core.config import load_config


def main() -> int:
    cfg = load_config()

    # Pick up or generate the web secret
    web_secret = os.environ.get("VORTEX_WEB_SECRET")
    if web_secret:
        cfg.web.secret_key = web_secret

    auth = AuthManager(hmac_secret=cfg.web.secret_key.encode("utf-8"))

    admin_user = os.environ.get("VORTEX_ADMIN_USER", "admin")
    admin_pass_env = os.environ.get("VORTEX_ADMIN_PASS")
    existing = auth.get_user(admin_user)
    if existing:
        print(f"[i] admin user '{admin_user}' already exists")
        return 0

    if not admin_pass_env:
        admin_pass_env = secrets.token_urlsafe(16)
        # Re-export so the caller (quick-start.sh) can capture it
        os.environ["VORTEX_ADMIN_PASS"] = admin_pass_env

    auth.create_user(admin_user, admin_pass_env, is_admin=True)
    print(f"[+] created admin user '{admin_user}'")
    if not os.environ.get("VORTEX_QUIET"):
        print(f"[+] admin password: {admin_pass_env}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
