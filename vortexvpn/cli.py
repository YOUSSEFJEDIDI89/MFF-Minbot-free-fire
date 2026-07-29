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


def cmd_run(args) -> int:
    """Alias for `start`. Accepts the same flags (--password=, --public-url=, --admin-path=)."""
    # Forward all extra args to quick-start.sh
    extra = []
    if hasattr(args, "password") and args.password:
        extra.append(f"--password={args.password}")
    if hasattr(args, "public_url") and args.public_url:
        extra.append(f"--public-url={args.public_url}")
    if hasattr(args, "admin_path") and args.admin_path:
        extra.append(f"--admin-path={args.admin_path}")
    if extra:
        # Build a custom quick-start invocation
        cmd = ["bash", str(QUICK_START)] + extra
        return subprocess.call(cmd, cwd=str(PROJECT_DIR))
    return run_quick_start("start")


def cmd_admin(_args) -> int:
    """Launch the interactive admin terminal."""
    from vortexvpn.admin_shell import main as admin_main
    return admin_main()


def cmd_guide(_args) -> int:
    """Print the full Arabic command guide."""
    from vortexvpn.guide import print_guide
    print_guide()
    return 0


def cmd_link(args) -> int:
    """Set the public URL (your HTTPS domain) and restart.

    Example: vortexvpn link https://server.vortevpn.org
    """
    url = args.url.rstrip("/")
    if not url.startswith("https://") and not url.startswith("http://"):
        print(f"error: URL must start with http:// or https:// (got: {url})",
              file=sys.stderr)
        return 1

    print(f"[+] setting public_url = {url}")

    # Update config.toml in-place
    cfg_path = PROJECT_DIR / "configs" / "config.toml"
    if not cfg_path.exists():
        # Copy from example
        example = PROJECT_DIR / "configs" / "config.toml.example"
        cfg_path.write_text(example.read_text())

    text = cfg_path.read_text()
    new_lines = []
    in_web_section = False
    public_url_set = False
    admin_path_set = False
    admin_path = args.admin_path

    for line in text.splitlines():
        stripped = line.strip()
        # Track sections
        if stripped.startswith("[") and stripped.endswith("]"):
            in_web_section = (stripped == "[web]")
            new_lines.append(line)
            continue

        # Update public_url
        if in_web_section and stripped.startswith("public_url"):
            new_lines.append(f'public_url = "{url}"')
            public_url_set = True
            continue

        # Update admin_path
        if in_web_section and admin_path and stripped.startswith("admin_path"):
            new_lines.append(f'admin_path = "{admin_path}"')
            admin_path_set = True
            continue

        new_lines.append(line)

    # If public_url wasn't in the file, append it under [web]
    if not public_url_set or (admin_path and not admin_path_set):
        # Re-write with the additions injected at the end of [web]
        final_lines = []
        in_web = False
        for line in new_lines:
            final_lines.append(line)
            stripped = line.strip()
            if stripped == "[web]":
                in_web = True
            elif stripped.startswith("[") and stripped.endswith("]") and in_web:
                # We just left [web] section — inject before this section header
                if not public_url_set:
                    final_lines.insert(-1, f'public_url = "{url}"')
                    public_url_set = True
                if admin_path and not admin_path_set:
                    final_lines.insert(-1, f'admin_path = "{admin_path}"')
                    admin_path_set = True
                in_web = False
        new_lines = final_lines

    cfg_path.write_text("\n".join(new_lines) + "\n")
    print(f"[+] config.toml updated")

    # Also export as env var for the running process
    os.environ["VORTEX_PUBLIC_URL"] = url
    if admin_path:
        os.environ["VORTEX_ADMIN_PATH"] = admin_path
        print(f"[+] admin_path = {admin_path}")

    # Restart server
    print(f"[+] restarting server...")
    subprocess.call(["bash", str(QUICK_START), "--stop"],
                    cwd=str(PROJECT_DIR),
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    rc = subprocess.call(["bash", str(QUICK_START), "start"],
                         cwd=str(PROJECT_DIR))

    if rc == 0:
        print()
        print("═" * 60)
        print(f"  ✓ Server linked to {url}")
        print(f"  ✓ User login:  {url}/login")
        if admin_path:
            print(f"  ✓ Admin login: {url}{admin_path}  (مخفي)")
        else:
            print(f"  ✓ Admin login: {url}/admin/login  (افتراضي)")
        print("═" * 60)
    return rc


def cmd_settings(args) -> int:
    """Show or edit server settings, then optionally restart."""
    cfg_path = PROJECT_DIR / "configs" / "config.toml"
    if not cfg_path.exists():
        example = PROJECT_DIR / "configs" / "config.toml.example"
        cfg_path.write_text(example.read_text())
        print(f"[+] created {cfg_path} from template")

    if args.show:
        # Just print
        print(f"\n--- {cfg_path} ---\n")
        print(cfg_path.read_text())
        return 0

    if args.edit:
        # Open in $EDITOR
        editor = os.environ.get("EDITOR", "nano")
        print(f"[+] opening {cfg_path} in {editor}...")
        return subprocess.call([editor, str(cfg_path)])

    # Interactive mode
    return _interactive_settings(cfg_path)


def _interactive_settings(cfg_path) -> int:
    """Interactive settings editor with restart option."""
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib  # type: ignore

    with cfg_path.open("rb") as fh:
        cfg = tomllib.load(fh)

    print()
    print("═" * 60)
    print("  تعديل الإعدادات")
    print("═" * 60)
    print("  اضغط Enter للحفاظ على القيمة الحالية")
    print()

    # Editable keys with current values
    editable = [
        ("web.port",              "منفذ الواجهة",         cfg.get("web", {}).get("port", 8080)),
        ("web.public_url",        "الرابط العام (HTTPS)",  cfg.get("web", {}).get("public_url", "")),
        ("web.admin_path",        "مسار دخول المشرف",      cfg.get("web", {}).get("admin_path", "/admin/login")),
        ("tunnel.listen_port",    "منفذ النفق (UDP)",     cfg.get("tunnel", {}).get("listen_port", 4433)),
        ("tunnel.max_clients",    "أقصى عدد عملاء",        cfg.get("tunnel", {}).get("max_clients", 256)),
        ("tunnel.mtu",            "حجم الحزمة (MTU)",      cfg.get("tunnel", {}).get("mtu", 1400)),
        ("log_level",             "مستوى السجلات",         cfg.get("log_level", "INFO")),
    ]

    changes = {}
    for key, label, current in editable:
        section, name = key.split(".", 1) if "." in key else ("", key)
        prompt = f"  {label} [{current}]: "
        try:
            new_val = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 1
        if new_val and new_val != str(current):
            changes[key] = new_val

    if not changes:
        print("\n  (لا توجد تغييرات)")
        return 0

    print()
    print("  التغييرات المقترحة:")
    for key, val in changes.items():
        print(f"    {key} = {val}")
    print()
    try:
        confirm = input("  حفظ؟ [y/N]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return 1
    if confirm != "y":
        print("  تم الإلغاء")
        return 0

    # Apply changes to the config file (line-based edit)
    text = cfg_path.read_text()
    new_lines = []
    current_section = ""
    pending = dict(changes)  # copy

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            current_section = stripped
        # Try to match each pending change
        matched = False
        for key in list(pending.keys()):
            if "." in key:
                sec, name = key.split(".", 1)
                sec_bracket = f"[{sec}]"
                if current_section == sec_bracket and stripped.startswith(name):
                    # Determine type and format value
                    val = pending[key]
                    try:
                        val_int = int(val)
                        new_lines.append(f"{name} = {val_int}")
                    except ValueError:
                        new_lines.append(f'{name} = "{val}"')
                    del pending[key]
                    matched = True
                    break
            else:
                # Top-level key like log_level
                if current_section == "" and stripped.startswith(key):
                    new_lines.append(f'{key} = "{pending[key]}"')
                    del pending[key]
                    matched = True
                    break
        if not matched:
            new_lines.append(line)

    cfg_path.write_text("\n".join(new_lines) + "\n")
    print(f"  [+] {cfg_path} محدّث")

    # Restart?
    print()
    try:
        restart = input("  إعادة تشغيل السيرفر الآن؟ [Y/n]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return 0
    if restart != "n":
        print("  [+] إعادة التشغيل...")
        subprocess.call(["bash", str(QUICK_START), "--stop"],
                        cwd=str(PROJECT_DIR),
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return subprocess.call(["bash", str(QUICK_START), "start"],
                               cwd=str(PROJECT_DIR))
    return 0


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


def cmd_show_password(_args) -> int:
    """Print the admin password from the secrets file."""
    secrets = PROJECT_DIR / ".vortex-secrets.env"
    if not secrets.exists():
        print("no secrets file found")
        print("run:  vortexvpn start")
        print("  or: ./scripts/quick-start.sh")
        return 1
    admin_user = admin_pass = ""
    for line in secrets.read_text().splitlines():
        if line.startswith("VORTEX_ADMIN_USER="):
            admin_user = line.split("=", 1)[1]
        elif line.startswith("VORTEX_ADMIN_PASS="):
            admin_pass = line.split("=", 1)[1]
    if not admin_pass:
        print("no admin password recorded in secrets file")
        print("(it may have been reset via 'vortexvpn reset-password')")
        return 1
    print()
    print("─" * 40)
    print(f"  admin username: {admin_user}")
    print(f"  admin password: {admin_pass}")
    print("─" * 40)
    print()
    print("Note: if you changed this password via 'reset-password',")
    print("the value above is the ORIGINAL one and may be outdated.")
    print("Use 'vortexvpn connect' to see the URL + current admin info.")
    return 0


def cmd_reset_password(args) -> int:
    """Reset a user's password (default: admin).

    Updates both the auth DB and the .vortex-secrets.env file (so the
    new password is reflected in 'show-password' / 'connect' output).
    """
    import getpass
    import secrets as _secrets

    sys.path.insert(0, str(PROJECT_DIR))
    from vortexvpn.core.auth import AuthManager, AuthError
    from vortexvpn.core.config import load_config

    cfg = load_config()
    auth = AuthManager(hmac_secret=cfg.web.secret_key.encode("utf-8"))

    username = args.username
    new_pass = args.new

    # Confirm the user exists
    if not auth.get_user(username):
        print(f"error: user '{username}' does not exist", file=sys.stderr)
        print("existing users:")
        for u in auth.list_users():
            print(f"  - {u.username}")
        return 1

    # Prompt for new password if not given on CLI
    if not new_pass:
        print(f"Resetting password for user '{username}'")
        print("(password must be at least 8 characters)")
        new_pass = getpass.getpass("new password: ")
        confirm = getpass.getpass("confirm:      ")
        if new_pass != confirm:
            print("error: passwords do not match", file=sys.stderr)
            return 1
        if len(new_pass) < 8:
            print("error: password must be at least 8 characters", file=sys.stderr)
            return 1

    try:
        ok = auth.reset_password(username, new_pass)
    except AuthError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if not ok:
        print(f"error: user '{username}' not found in DB", file=sys.stderr)
        return 1

    # If we reset admin, also update .vortex-secrets.env so
    # 'show-password' and 'connect' reflect the new value.
    secrets_file = PROJECT_DIR / ".vortex-secrets.env"
    if username == "admin" and secrets_file.exists():
        lines = secrets_file.read_text().splitlines()
        out = []
        for line in lines:
            if line.startswith("VORTEX_ADMIN_PASS="):
                out.append(f"VORTEX_ADMIN_PASS={new_pass}")
            else:
                out.append(line)
        secrets_file.write_text("\n".join(out) + "\n")
        secrets_file.chmod(0o600)

    print(f"[+] password updated for '{username}'")
    if username == "admin":
        print("[+] .vortex-secrets.env also updated")
    print("[+] if the server is running, restart it to pick up changes:")
    print("      vortexvpn restart")
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

    # `run` — friendly alias for `start`, accepts the same flags
    p_run = sub.add_parser("run", help="alias for start (with flags)")
    p_run.add_argument("--password", "-p", help="admin password")
    p_run.add_argument("--public-url", help="public HTTPS URL")
    p_run.add_argument("--admin-path", help="hidden admin login path")
    p_run.set_defaults(func=cmd_run)

    sub.add_parser("stop", help="stop the server").set_defaults(func=cmd_stop)
    sub.add_parser("restart", help="restart the server").set_defaults(func=cmd_restart)
    sub.add_parser("status", help="show running state").set_defaults(func=cmd_status)
    sub.add_parser("logs", help="tail the log file").set_defaults(func=cmd_logs)
    sub.add_parser("connect", help="print connection info (URL, admin, ports)").set_defaults(func=cmd_connect)
    sub.add_parser("show-password", help="print the current admin password (from secrets file)").set_defaults(func=cmd_show_password)
    sub.add_parser("admin", help="launch interactive admin terminal (REPL)").set_defaults(func=cmd_admin)
    sub.add_parser("guide", help="print the full Arabic command guide").set_defaults(func=cmd_guide)

    # `link <url>` — bind server to a real HTTPS domain
    p_link = sub.add_parser("link", help="bind server to a public HTTPS URL + restart")
    p_link.add_argument("url", help="full URL, e.g. https://server.vortevpn.org")
    p_link.add_argument("--admin-path", help="set hidden admin login path (e.g. /x7k2m-secret)")
    p_link.set_defaults(func=cmd_link)

    # `settings` — interactive editor + restart
    p_set = sub.add_parser("settings", help="show / edit settings + restart")
    p_set.add_argument("--show", action="store_true", help="just print current config")
    p_set.add_argument("--edit", action="store_true", help="open config.toml in $EDITOR")
    p_set.set_defaults(func=cmd_settings)

    p_reset = sub.add_parser("reset-password", help="reset admin (or any user) password")
    p_reset.add_argument("--username", "-u", default="admin",
                         help="username (default: admin)")
    p_reset.add_argument("--new", "-n",
                         help="new password (prompted if omitted)")
    p_reset.set_defaults(func=cmd_reset_password)

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
