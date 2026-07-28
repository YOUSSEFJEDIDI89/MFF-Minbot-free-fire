"""Tests for the Flask web panel API."""
from __future__ import annotations

import json

import pytest

from vortexvpn.core.auth import AuthManager
from vortexvpn.core.tunnel_server import TunnelServer
from vortexvpn.web.app import create_app


class FakeTunnel:
    """Drop-in for TunnelServer that returns canned stats."""
    def __init__(self) -> None:
        self.kicked: list = []
    def stats(self) -> dict:
        return {
            "listening": "0.0.0.0:4433",
            "active_clients": 1,
            "max_clients": 256,
            "clients": [
                {"username": "alice", "address": "1.2.3.4:5000",
                 "virtual_ip": "10.99.0.11", "connected_at": 0,
                 "last_seen": 0, "bytes_rx": 1024, "bytes_tx": 2048,
                 "using_accel": True}
            ],
        }
    def kick(self, addr) -> bool:
        self.kicked.append(addr)
        return True


@pytest.fixture
def app(tmp_path):
    auth = AuthManager(db_path=str(tmp_path / "auth.db"),
                       hmac_secret=b"test-secret-key-32-chars-long-ok!")
    auth.create_user("admin", "admin-password", is_admin=True)
    auth.create_user("user1", "user-password")
    tunnel = FakeTunnel()
    flask_app = create_app(auth=auth, tunnel=tunnel)  # type: ignore
    flask_app.config["TESTING"] = True
    return flask_app, auth, tunnel


@pytest.fixture
def client(app):
    flask_app, _, _ = app
    return flask_app.test_client()


def login(client, username="admin", password="admin-password"):
    return client.post("/login", data={"username": username, "password": password},
                       follow_redirects=False)


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.get_json()["ok"] is True


def test_login_required_for_stats(client):
    r = client.get("/api/v1/stats")
    assert r.status_code == 302  # redirect to login


def test_stats_after_login(client):
    login(client)
    r = client.get("/api/v1/stats")
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is True
    assert data["stats"]["active_clients"] == 1


def test_users_list_admin_only(client):
    login(client, "admin", "admin-password")
    r = client.get("/api/v1/users")
    assert r.status_code == 200
    usernames = [u["username"] for u in r.get_json()["users"]]
    assert "admin" in usernames
    assert "user1" in usernames


def test_non_admin_cannot_list_users(client):
    login(client, "user1", "user-password")
    r = client.get("/api/v1/users")
    assert r.status_code == 403


def test_create_user_api(client):
    login(client, "admin", "admin-password")
    r = client.post("/api/v1/users", json={
        "username": "newuser", "password": "pass-12345",
    })
    assert r.status_code == 201
    assert r.get_json()["ok"] is True


def test_kick_session(client, app):
    login(client, "admin", "admin-password")
    _, _, tunnel = app
    r = client.post("/api/v1/sessions/kick", json={"ip": "1.2.3.4", "port": 5000})
    assert r.status_code == 200
    assert r.get_json()["ok"] is True
    assert tunnel.kicked == [("1.2.3.4", 5000)]
