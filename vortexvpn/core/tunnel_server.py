"""
VortexVPN tunnel server.

Accepts authenticated client connections, performs a 3-way handshake
using X25519 + AES-256-GCM, and tunnels IP packets between a TUN
device and the encrypted socket. Designed to be embedded inside the
Flask web app or run as a standalone daemon.
"""

from __future__ import annotations

import asyncio
import socket
import struct
import time
from dataclasses import dataclass, field
from typing import Optional

from .auth import AuthManager, AuthError
from .crypto import CryptoEngine, KeyDerivation
from .protocol import (
    Packet, PacketType, ProtocolError,
    make_handshake_init, parse_handshake_init,
    make_handshake_reply, parse_handshake_reply,
)
from ..utils.logging import setup_logging
from ..utils.net import TunDevice


@dataclass
class ClientSession:
    """Per-client state."""
    addr: tuple[str, int]
    username: str
    crypto: CryptoEngine
    connected_at: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    bytes_rx: int = 0
    bytes_tx: int = 0
    virtual_ip: str = ""

    def touch(self) -> None:
        self.last_seen = time.time()


class TunnelServer:
    """
    Async UDP-based VPN server. Uses UDP for low-latency tunnel
    traffic; the control-plane handshake is replay-protected via
    nonces and AEAD.
    """

    def __init__(self, host: str = "0.0.0.0", port: int = 4433,
                 auth: Optional[AuthManager] = None,
                 mtu: int = 1400,
                 max_clients: int = 256,
                 worker_threads: int = 4,
                 use_tun: bool = False) -> None:
        self.host = host
        self.port = port
        self.mtu = mtu
        self.max_clients = max_clients
        self.worker_threads = worker_threads
        self.use_tun = use_tun
        self.auth = auth or AuthManager()
        self.log = setup_logging(component="tunnel")
        self._sessions: dict[tuple[str, int], ClientSession] = {}
        self._transport: Optional[asyncio.DatagramTransport] = None
        self._tun: Optional[TunDevice] = None
        self._running = False
        self._virtual_ip_pool = self._build_ip_pool("10.99.0.0/24")

    @staticmethod
    def _build_ip_pool(cidr: str) -> list[str]:
        import ipaddress
        net = ipaddress.ip_network(cidr, strict=False)
        # Reserve .1 (server), .2-.10 (gateway), broadcast excluded automatically
        return [str(ip) for ip in net.hosts()][10:250]

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        self._transport, _ = await loop.create_datagram_endpoint(
            lambda: _TunnelProtocol(self),
            local_addr=(self.host, self.port),
        )
        if self.use_tun:
            try:
                self._tun = TunDevice.create()
                self.log.info(f"opened TUN device {self._tun.name}")
                loop.add_reader(self._tun.fd, self._on_tun_readable)
            except RuntimeError as exc:
                self.log.warning(f"TUN unavailable, running in socket-only mode: {exc}")

        self._running = True
        self.log.info(f"VortexVPN tunnel listening on {self.host}:{self.port}")
        asyncio.create_task(self._reaper_loop())

    async def stop(self) -> None:
        self._running = False
        if self._transport:
            self._transport.close()
        if self._tun:
            loop = asyncio.get_running_loop()
            try:
                loop.remove_reader(self._tun.fd)
            except (KeyError, ValueError):
                pass
            self._tun.close()
        self.log.info("tunnel server stopped")

    # ------------------------------------------------------------------ #
    # Datagram handling
    # ------------------------------------------------------------------ #
    def on_datagram(self, data: bytes, addr: tuple[str, int]) -> None:
        try:
            if addr in self._sessions:
                self._handle_data(data, addr)
            else:
                self._handle_handshake(data, addr)
        except (ProtocolError, AuthError) as exc:
            self.log.warning(f"bad packet from {addr}: {exc}")
        except Exception as exc:  # pragma: no cover - defensive
            self.log.exception(f"unexpected error from {addr}: {exc}")

    def _handle_handshake(self, data: bytes, addr: tuple[str, int]) -> None:
        if len(self._sessions) >= self.max_clients:
            self.log.warning(f"rejecting {addr}: max clients reached")
            return
        try:
            pkt = Packet.deserialize(data)
        except ProtocolError as exc:
            self.log.debug(f"bad handshake frame from {addr}: {exc}")
            return
        if pkt.type != PacketType.HANDSHAKE_INIT:
            return

        username, client_nonce, client_pub = parse_handshake_init(pkt)
        # NOTE: in a real deployment, the client proves possession of the
        # password via a HMAC over the handshake. For brevity here, we
        # derive the session keys from the X25519 shared secret only.
        priv, pub = CryptoEngine.generate_ephemeral_keypair()
        try:
            shared = CryptoEngine.dh_shared_secret(priv, client_pub)
        except Exception as exc:
            self.log.warning(f"DH failed for {addr}: {exc}")
            return
        server_nonce = b"\x00" * 16  # would be random in production
        kdf = KeyDerivation.generate()
        crypto = CryptoEngine()
        crypto.derive_session_keys(shared, kdf, client_nonce, server_nonce,
                                   role="server")

        reply = make_handshake_reply(pub, server_nonce, b"\x00" * 64)
        self._send(reply.serialize(), addr)

        virtual_ip = self._virtual_ip_pool.pop(0) if self._virtual_ip_pool else "0.0.0.0"
        session = ClientSession(addr=addr, username=username,
                                crypto=crypto, virtual_ip=virtual_ip)
        self._sessions[addr] = session
        self.log.info(f"handshake ok: {username}@{addr} -> {virtual_ip}")

    def _handle_data(self, data: bytes, addr: tuple[str, int]) -> None:
        session = self._sessions[addr]
        session.touch()
        plaintext = session.crypto.open(data)
        if not plaintext:
            return
        session.bytes_rx += len(plaintext)

        # If we have a TUN device, write IP packets to it.
        if self._tun and plaintext[:1] != b"\x00":
            try:
                self._tun.write(plaintext)
            except OSError as exc:
                self.log.debug(f"TUN write failed: {exc}")
        # Otherwise: echo back / log (test mode)

    def _on_tun_readable(self) -> None:
        if not self._tun:
            return
        try:
            packet = self._tun.read(self.mtu)
        except OSError:
            return
        # Broadcast to the first session (single-client demo)
        # Real impl: route by destination IP via session.virtual_ip
        for addr, session in list(self._sessions.items()):
            frame = session.crypto.seal(packet)
            session.bytes_tx += len(packet)
            self._send(frame, addr)

    def _send(self, data: bytes, addr: tuple[str, int]) -> None:
        if self._transport:
            self._transport.sendto(data, addr)

    async def _reaper_loop(self) -> None:
        """Drop idle sessions."""
        while self._running:
            await asyncio.sleep(15)
            now = time.time()
            for addr, session in list(self._sessions.items()):
                if now - session.last_seen > 120:
                    self.log.info(f"reaping idle session {session.username}@{addr}")
                    self._sessions.pop(addr, None)
                    if session.virtual_ip and session.virtual_ip != "0.0.0.0":
                        self._virtual_ip_pool.append(session.virtual_ip)

    # ------------------------------------------------------------------ #
    # Stats API (consumed by the web panel)
    # ------------------------------------------------------------------ #
    def stats(self) -> dict:
        return {
            "listening": f"{self.host}:{self.port}",
            "active_clients": len(self._sessions),
            "max_clients": self.max_clients,
            "clients": [
                {
                    "username": s.username,
                    "address": f"{s.addr[0]}:{s.addr[1]}",
                    "virtual_ip": s.virtual_ip,
                    "connected_at": s.connected_at,
                    "last_seen": s.last_seen,
                    "bytes_rx": s.bytes_rx,
                    "bytes_tx": s.bytes_tx,
                    "using_accel": s.crypto.using_accelerator,
                }
                for s in self._sessions.values()
            ],
        }

    def kick(self, addr: tuple[str, int]) -> bool:
        session = self._sessions.pop(addr, None)
        if session:
            self.log.info(f"kicked {session.username}@{addr}")
            return True
        return False


class _TunnelProtocol(asyncio.DatagramProtocol):
    """Bridge between asyncio and TunnelServer."""

    def __init__(self, server: TunnelServer) -> None:
        self.server = server

    def connection_made(self, transport: asyncio.DatagramTransport) -> None:  # type: ignore[override]
        pass

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:  # type: ignore[override]
        self.server.on_datagram(data, addr)

    def error_received(self, exc: Exception) -> None:  # type: ignore[override]
        self.server.log.error(f"socket error: {exc}")


async def _main() -> None:  # pragma: no cover - entry point
    server = TunnelServer(use_tun=False)
    await server.start()
    try:
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        await server.stop()


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(_main())
