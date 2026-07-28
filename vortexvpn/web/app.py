"""
Flask web panel for VortexVPN.

Exposes:
  - HTML dashboard at /
  - Login / logout
  - User CRUD (admin only)
  - JSON API at /api/v1/... for stats, users, sessions
  - WebSocket-free live updates via /api/v1/stats polling
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from functools import wraps
from typing import Any, Optional

from flask import (
    Flask, abort, flash, jsonify, redirect, render_template, request,
    session, url_for,
)
from werkzeug.middleware.proxy_fix import ProxyFix

from ..core.auth import AuthError, AuthManager
from ..core.config import Config, load_config
from ..core.tunnel_server import TunnelServer
from ..utils.logging import setup_logging


def create_app(config: Optional[Config] = None,
               auth: Optional[AuthManager] = None,
               tunnel: Optional[TunnelServer] = None) -> Flask:
    """Application factory - lets tests inject mocks."""
    cfg = config or load_config()
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config["SECRET_KEY"] = cfg.web.secret_key
    app.config["SESSION_COOKIE_SECURE"] = cfg.web.session_cookie_secure
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)  # type: ignore

    app.config["VORTEX_CFG"] = cfg
    auth = auth or AuthManager(hmac_secret=cfg.web.secret_key.encode("utf-8"))
    app.config["VORTEX_AUTH"] = auth

    log = setup_logging(level=cfg.log_level, component="web")

    # ------------------------------------------------------------------ #
    # Start the tunnel server in a background thread (best-effort)
    # ------------------------------------------------------------------ #
    if tunnel is None:
        tunnel = TunnelServer(
            host=cfg.tunnel.listen_host,
            port=cfg.tunnel.listen_port,
            auth=auth,
            mtu=cfg.tunnel.mtu,
            max_clients=cfg.tunnel.max_clients,
            worker_threads=cfg.tunnel.worker_threads,
            use_tun=False,
        )
        loop = asyncio.new_event_loop()
        t = threading.Thread(target=_run_tunnel, args=(loop, tunnel), daemon=True)
        t.start()
        app.config["VORTEX_LOOP"] = loop
    app.config["VORTEX_TUNNEL"] = tunnel
    app.logger.addHandler(log.handlers[0]) if log.handlers else None

    # ------------------------------------------------------------------ #
    # Auth decorator
    # ------------------------------------------------------------------ #
    def login_required(fn):
        @wraps(fn)
        def _wrapper(*args, **kwargs):
            token = session.get("token")
            if not token:
                return redirect(url_for("login", next=request.path))
            try:
                user = auth.verify_token(token)
            except AuthError:
                session.pop("token", None)
                return redirect(url_for("login", next=request.path))
            request.user = user  # type: ignore[attr-defined]
            return fn(*args, **kwargs)
        return _wrapper

    def admin_required(fn):
        @wraps(fn)
        def _wrapper(*args, **kwargs):
            user = getattr(request, "user", None)
            if not user or not user.is_admin:
                abort(403)
            return fn(*args, **kwargs)
        return login_required(_wrapper)

    # ------------------------------------------------------------------ #
    # HTML routes
    # ------------------------------------------------------------------ #
    @app.route("/")
    @login_required
    def dashboard():
        return render_template("dashboard.html", user=request.user,  # type: ignore
                               stats=tunnel.stats())

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            username = request.form.get("username", "")
            password = request.form.get("password", "")
            try:
                user = auth.authenticate(username, password)
            except AuthError as exc:
                flash(str(exc), "error")
                return render_template("login.html"), 401
            token = auth.issue_token(user)
            session["token"] = token.to_string()
            return redirect(request.args.get("next") or url_for("dashboard"))
        return render_template("login.html")

    @app.route("/logout")
    def logout():
        session.pop("token", None)
        return redirect(url_for("login"))

    @app.route("/users")
    @admin_required
    def users_page():
        return render_template("users.html", user=request.user,
                               users=auth.list_users())

    @app.route("/settings")
    @login_required
    def settings_page():
        return render_template("settings.html", user=request.user, cfg=cfg)

    @app.route("/connect")
    @login_required
    def connect_page():
        import socket as _sock
        s = _sock.socket(_sock.AF_INET, _sock.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            server_ip = s.getsockname()[0]
        except OSError:
            server_ip = "127.0.0.1"
        finally:
            s.close()
        return render_template("connect.html", user=request.user,
                              server_ip=server_ip,
                              tunnel_port=cfg.tunnel.listen_port,
                              web_port=cfg.web.port,
                              virtual_subnet=cfg.tunnel.virtual_subnet,
                              dns_servers=cfg.tunnel.dns_servers)

    # ------------------------------------------------------------------ #
    # JSON API
    # ------------------------------------------------------------------ #
    @app.route("/api/v1/stats")
    @login_required
    def api_stats():
        return jsonify({"ok": True, "stats": tunnel.stats(),
                        "ts": time.time()})

    @app.route("/api/v1/users")
    @admin_required
    def api_users():
        return jsonify({"ok": True, "users": [
            {"id": u.id, "username": u.username, "is_admin": u.is_admin,
             "is_active": u.is_active, "created_at": u.created_at,
             "bandwidth_quota_bytes": u.bandwidth_quota_bytes,
             "bandwidth_used_bytes": u.bandwidth_used_bytes,
             "expires_at": u.expires_at}
            for u in auth.list_users()
        ]})

    @app.route("/api/v1/users", methods=["POST"])
    @admin_required
    def api_create_user():
        body = request.get_json(force=True, silent=True) or {}
        try:
            user = auth.create_user(
                body["username"], body["password"],
                is_admin=bool(body.get("is_admin", False)),
                bandwidth_quota_bytes=int(body.get("bandwidth_quota_bytes", 0)),
                expires_at=float(body["expires_at"]) if body.get("expires_at") else None,
            )
        except (KeyError, AuthError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        return jsonify({"ok": True, "id": user.id}), 201

    @app.route("/api/v1/users/<username>", methods=["DELETE"])
    @admin_required
    def api_delete_user(username: str):
        ok = auth.delete_user(username)
        return jsonify({"ok": ok})

    @app.route("/api/v1/users/<username>/active", methods=["POST"])
    @admin_required
    def api_toggle_active(username: str):
        body = request.get_json(force=True, silent=True) or {}
        ok = auth.set_active(username, bool(body.get("active", True)))
        return jsonify({"ok": ok})

    @app.route("/api/v1/sessions/kick", methods=["POST"])
    @admin_required
    def api_kick():
        body = request.get_json(force=True, silent=True) or {}
        ip = body.get("ip"); port = int(body.get("port", 0))
        if not ip or not port:
            return jsonify({"ok": False, "error": "ip and port required"}), 400
        ok = tunnel.kick((ip, port))
        return jsonify({"ok": ok})

    @app.route("/healthz")
    def healthz():
        return jsonify({"ok": True, "ts": time.time()})

    # ------------------------------------------------------------------ #
    # Error handlers
    # ------------------------------------------------------------------ #
    @app.errorhandler(404)
    def not_found(_): return jsonify({"ok": False, "error": "not found"}), 404

    @app.errorhandler(403)
    def forbidden(_): return jsonify({"ok": False, "error": "forbidden"}), 403

    @app.errorhandler(500)
    def server_error(_): return jsonify({"ok": False, "error": "server error"}), 500

    return app


def _run_tunnel(loop: asyncio.AbstractEventLoop, tunnel: TunnelServer) -> None:
    asyncio.set_event_loop(loop)
    loop.run_until_complete(tunnel.start())
    loop.run_forever()


def main() -> None:  # pragma: no cover
    cfg = load_config()
    app = create_app(cfg)
    app.run(host=cfg.web.host, port=cfg.web.port, debug=cfg.web.debug)


if __name__ == "__main__":  # pragma: no cover
    main()
