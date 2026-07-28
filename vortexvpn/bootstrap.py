"""Bootstrap script: create config + admin user, print credentials."""
from __future__ import annotations

import os
import sys

from vortexvpn.core.auth import AuthManager
from vortexvpn.core.config import load_config


def main() -> int:
    cfg = load_config()
    auth = AuthManager(hmac_secret=cfg.web.secret_key.encode("utf-8"))
    admin_user = os.environ.get("VORTEX_ADMIN_USER", "admin")
    admin_pass = os.environ.get("VORTEX_ADMIN_PASS")
    pw = auth.ensure_admin(admin_user, admin_pass)
    print(f"[*] admin user: {admin_user}")
    if pw == "(already exists)":
        print(f"[*] admin already exists; reset with: vortexvpn-reset-admin {admin_user}")
    else:
        print(f"[*] admin password: {pw}")
        print("[*] (store this safely, it won't be shown again)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
