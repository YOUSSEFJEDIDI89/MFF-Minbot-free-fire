"""
Interactive admin terminal — a REPL for managing VortexVPN.

Run with:  vortexvpn admin
(or:       python -m vortexvpn.admin_shell)

Type 'help' inside the shell for the command list.
"""
from __future__ import annotations

import cmd
import os
import shlex
import socket
import sys
import time
from pathlib import Path
from typing import Optional

PROJECT_DIR = Path(__file__).resolve().parent.parent


class AdminShell(cmd.Cmd):
    """Interactive REPL for VortexVPN administration."""

    intro = (
        "\n╔══════════════════════════════════════════════════════════╗\n"
        "║          VortexVPN Admin Terminal v1.0                   ║\n"
        "║          اكتب 'help' لعرض كل الأوامر                    ║\n"
        "╚══════════════════════════════════════════════════════════╝\n"
    )
    prompt = "vortex> "

    def __init__(self) -> None:
        super().__init__()
        sys.path.insert(0, str(PROJECT_DIR))
        from vortexvpn.core.auth import AuthManager
        from vortexvpn.core.config import load_config
        from vortexvpn.core.tunnel_server import TunnelServer

        self.cfg = load_config()
        self.auth = AuthManager(hmac_secret=self.cfg.web.secret_key.encode("utf-8"))
        # Tunnel stats via HTTP (so we don't need to share memory with the server)
        self._web_port = self.cfg.web.port
        self._web_host = self.cfg.web.host
        if self._web_host == "0.0.0.0":
            self._web_host = "127.0.0.1"

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def _fmt_bytes(self, n: float) -> str:
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if n < 1024:
                return f"{n:.1f} {unit}"
            n /= 1024
        return f"{n:.1f} PB"

    def _fmt_time(self, ts: float) -> str:
        if not ts:
            return "—"
        delta = time.time() - ts
        if delta < 60:
            return f"{int(delta)}s ago"
        if delta < 3600:
            return f"{int(delta/60)}m ago"
        if delta < 86400:
            return f"{int(delta/3600)}h ago"
        return f"{int(delta/86400)}d ago"

    def _fetch_stats(self) -> Optional[dict]:
        """Fetch live stats from the running web server (internal endpoint)."""
        import json
        import urllib.request
        try:
            # Use the /internal/stats endpoint which is localhost-only, no auth.
            url = f"http://{self._web_host}:{self._web_port}/internal/stats"
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read())
            return data.get("stats")
        except Exception as exc:
            print(f"  [!] could not reach server: {exc}")
            print(f"      is it running? try: vortexvpn start")
            return None

    # ------------------------------------------------------------------ #
    # Commands
    # ------------------------------------------------------------------ #
    def do_help(self, _arg: str) -> None:
        print("\n" + "─" * 60)
        print("  أوامر VortexVPN Admin Terminal")
        print("─" * 60)
        commands = [
            ("help",                  "عرض هذه القائمة"),
            ("status",                "حالة السيرفر + URL + admin"),
            ("stats",                 "إحصائات حية من السيرفر (عملاء، ترافيك)"),
            ("users",                 "قائمة كل المستخدمين"),
            ("sessions",              "العملاء المتصلون حالياً"),
            ("add-user <name>",       "إضافة مستخدم جديد"),
            ("del-user <name>",       "حذف مستخدم"),
            ("reset-password <name>", "تغيير كلمة سر مستخدم"),
            ("toggle <name>",         "تفعيل/تعطيل مستخدم"),
            ("kick <ip> <port>",      "طرد عميل متصل"),
            ("kick-all",              "طرد كل العملاء"),
            ("version",               "إصدار VortexVPN"),
            ("exit / quit",           "خروج"),
        ]
        for cmd_name, desc in commands:
            print(f"  {cmd_name:<24} — {desc}")
        print("─" * 60 + "\n")

    def do_status(self, _arg: str) -> None:
        """Show overall server status."""
        import socket as _sock
        s = _sock.socket(_sock.AF_INET, _sock.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
        except OSError:
            local_ip = "127.0.0.1"
        finally:
            s.close()

        print("\n" + "═" * 50)
        print("  VortexVPN Status")
        print("═" * 50)
        print(f"  Web panel:    http://{local_ip}:{self._web_port}")
        print(f"  Admin login:  http://{local_ip}:{self._web_port}/admin/login")
        print(f"  User login:   http://{local_ip}:{self._web_port}/login")
        print(f"  Tunnel UDP:   {self.cfg.tunnel.listen_port}")
        if self.cfg.web.get("public_url") if hasattr(self.cfg.web, "get") else None:
            print(f"  Public URL:   {self.cfg.web.public_url}")
        # Check if running
        stats = self._fetch_stats()
        if stats:
            print(f"  Active clients: {stats['active_clients']}/{stats['max_clients']}")
            print(f"  Server status:  ● RUNNING")
        else:
            print(f"  Server status:  ○ STOPPED")
        print("═" * 50 + "\n")

    def do_stats(self, _arg: str) -> None:
        """Live stats from the running server."""
        stats = self._fetch_stats()
        if not stats:
            return
        print(f"\n  Listening:      {stats['listening']}")
        print(f"  Active clients: {stats['active_clients']}/{stats['max_clients']}")
        print(f"  Total traffic:  {sum(c['bytes_rx'] + c['bytes_tx'] for c in stats['clients'])} bytes")
        print()

    def do_users(self, _arg: str) -> None:
        """List all users."""
        users = self.auth.list_users()
        if not users:
            print("  (no users)")
            return
        print(f"\n  {'ID':<4} {'Username':<20} {'Admin':<6} {'Active':<7} {'Used':<12} {'Quota':<12}")
        print("  " + "─" * 70)
        for u in users:
            print(f"  {u.id:<4} {u.username:<20} "
                  f"{'✓' if u.is_admin else '—':<6} "
                  f"{'yes' if u.is_active else 'no':<7} "
                  f"{self._fmt_bytes(u.bandwidth_used_bytes):<12} "
                  f"{self._fmt_bytes(u.bandwidth_quota_bytes) if u.bandwidth_quota_bytes else '∞':<12}")
        print()

    def do_sessions(self, _arg: str) -> None:
        """List active tunnel sessions."""
        stats = self._fetch_stats()
        if not stats:
            return
        clients = stats.get("clients", [])
        if not clients:
            print("\n  (no active sessions)\n")
            return
        print(f"\n  {'Username':<15} {'Address':<22} {'Virtual IP':<14} {'↓ RX':<10} {'↑ TX':<10} {'Idle':<10}")
        print("  " + "─" * 80)
        for c in clients:
            print(f"  {c['username']:<15} {c['address']:<22} "
                  f"{c['virtual_ip']:<14} "
                  f"{self._fmt_bytes(c['bytes_rx']):<10} "
                  f"{self._fmt_bytes(c['bytes_tx']):<10} "
                  f"{self._fmt_time(c['last_seen']):<10}")
        print()

    def do_add_user(self, arg: str) -> None:
        """Add a new user. Usage: add-user <username> [--admin]"""
        from vortexvpn.core.auth import AuthError
        import getpass
        try:
            args = shlex.split(arg)
        except ValueError:
            print("  [!] invalid arguments")
            return
        if not args:
            print("  usage: add-user <username> [--admin]")
            return
        username = args[0]
        is_admin = "--admin" in args[1:]
        password = getpass.getpass("  new password (min 8 chars): ")
        if len(password) < 8:
            print("  [!] password too short (min 8 chars)")
            return
        try:
            user = self.auth.create_user(username, password, is_admin=is_admin)
        except AuthError as exc:
            print(f"  [!] {exc}")
            return
        print(f"  [+] created user '{user.username}' (id={user.id}, admin={user.is_admin})")

    def do_del_user(self, arg: str) -> None:
        """Delete a user. Usage: del-user <username>"""
        username = arg.strip()
        if not username:
            print("  usage: del-user <username>")
            return
        if username == "admin":
            confirm = input("  ⚠ delete admin? type 'yes' to confirm: ")
            if confirm != "yes":
                print("  cancelled")
                return
        if self.auth.delete_user(username):
            print(f"  [+] deleted user '{username}'")
        else:
            print(f"  [!] user '{username}' not found")

    def do_reset_password(self, arg: str) -> None:
        """Reset a user's password. Usage: reset-password <username>"""
        from vortexvpn.core.auth import AuthError
        import getpass
        username = arg.strip()
        if not username:
            print("  usage: reset-password <username>")
            return
        if not self.auth.get_user(username):
            print(f"  [!] user '{username}' not found")
            return
        pw = getpass.getpass("  new password (min 8 chars): ")
        if len(pw) < 8:
            print("  [!] password too short")
            return
        try:
            self.auth.reset_password(username, pw)
        except AuthError as exc:
            print(f"  [!] {exc}")
            return
        # Update secrets file if admin
        if username == "admin":
            secrets_file = PROJECT_DIR / ".vortex-secrets.env"
            if secrets_file.exists():
                lines = secrets_file.read_text().splitlines()
                out = [f"VORTEX_ADMIN_PASS={pw}" if l.startswith("VORTEX_ADMIN_PASS=") else l
                       for l in lines]
                secrets_file.write_text("\n".join(out) + "\n")
                secrets_file.chmod(0o600)
        print(f"  [+] password updated for '{username}'")

    def do_toggle(self, arg: str) -> None:
        """Toggle user active state. Usage: toggle <username>"""
        username = arg.strip()
        if not username:
            print("  usage: toggle <username>")
            return
        user = self.auth.get_user(username)
        if not user:
            print(f"  [!] user '{username}' not found")
            return
        new_state = not user.is_active
        if self.auth.set_active(username, new_state):
            print(f"  [+] '{username}' is now {'ACTIVE' if new_state else 'DISABLED'}")

    def do_kick(self, arg: str) -> None:
        """Kick a connected client. Usage: kick <ip> <port>"""
        import json
        import urllib.request
        parts = arg.split()
        if len(parts) != 2:
            print("  usage: kick <ip> <port>")
            return
        ip, port = parts[0], parts[1]
        try:
            port_i = int(port)
        except ValueError:
            print("  [!] port must be a number")
            return
        # Need a token to call admin API — for simplicity we just print
        # the command for now (admin can copy-paste if needed)
        print(f"  [i] to kick {ip}:{port_i}, open the web panel and click 'طرد'")
        print(f"      or: curl -X POST http://{self._web_host}:{self._web_port}/api/v1/sessions/kick \\")
        print(f"           -H 'Content-Type: application/json' \\")
        print(f"           -d '{{\"ip\":\"{ip}\",\"port\":{port_i}}}'")

    def do_kick_all(self, _arg: str) -> None:
        """Kick all connected clients."""
        stats = self._fetch_stats()
        if not stats:
            return
        clients = stats.get("clients", [])
        if not clients:
            print("  (no active sessions to kick)")
            return
        print(f"  ⚠ about to kick {len(clients)} client(s). Type 'yes' to confirm:")
        confirm = input("  > ")
        if confirm != "yes":
            print("  cancelled")
            return
        # Print curl commands (since admin token is needed)
        for c in clients:
            ip, port = c["address"].split(":")
            print(f"  [i] kick {ip}:{port} — see web panel")
        print(f"  [+] use the web panel 'kick' button for each, or restart the server")

    def do_version(self, _arg: str) -> None:
        """Show version."""
        from vortexvpn import __version__
        print(f"  VortexVPN v{__version__}")

    def do_exit(self, _arg: str) -> bool:
        """Exit the shell."""
        print("  goodbye 👋")
        return True

    do_quit = do_exit
    do_EOF = do_exit

    def emptyline(self) -> bool:
        return False


def main() -> int:
    try:
        AdminShell().cmdloop()
    except KeyboardInterrupt:
        print("\n  goodbye 👋")
    return 0


if __name__ == "__main__":
    sys.exit(main())
