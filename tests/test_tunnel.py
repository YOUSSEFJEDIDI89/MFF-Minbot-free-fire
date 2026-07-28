"""Tests for the tunnel server (socket-only, no TUN)."""
from __future__ import annotations

import asyncio
import socket

import pytest

from vortexvpn.core.auth import AuthManager
from vortexvpn.core.tunnel_server import TunnelServer


pytestmark = pytest.mark.asyncio


async def test_server_starts_and_responds(tmp_path):
    """Bind on an ephemeral port; the socket must accept datagrams."""
    auth = AuthManager(db_path=str(tmp_path / "auth.db"),
                       hmac_secret=b"test-secret-32-bytes-fixed-len!!!")
    # Pick a free port
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()

    server = TunnelServer(host="127.0.0.1", port=port, auth=auth,
                          use_tun=False, max_clients=2)
    await server.start()
    try:
        # Send a junk datagram; server must not crash
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(1.0)
        sock.sendto(b"\x00" * 8, ("127.0.0.1", port))
        # Give the server a moment to process
        await asyncio.sleep(0.1)
        # Stats should still be reachable
        stats = server.stats()
        assert stats["listening"] == f"127.0.0.1:{port}"
        assert stats["active_clients"] == 0
        sock.close()
    finally:
        await server.stop()


async def test_max_clients_enforced(tmp_path):
    auth = AuthManager(db_path=str(tmp_path / "auth.db"),
                       hmac_secret=b"test-secret-32-bytes-fixed-len!!!")
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()

    server = TunnelServer(host="127.0.0.1", port=port, auth=auth,
                          use_tun=False, max_clients=0)  # 0 = block all
    await server.start()
    try:
        # Any datagram from an unknown peer should be ignored
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(0.5)
        sock.sendto(b"\x01" + b"\x00" * 7, ("127.0.0.1", port))
        await asyncio.sleep(0.1)
        assert server.stats()["active_clients"] == 0
        sock.close()
    finally:
        await server.stop()
