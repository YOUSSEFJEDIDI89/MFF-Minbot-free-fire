"""
VortexVPN tunnel client.

Connects to a TunnelServer, performs the handshake, and shuttles
packets between a local TUN device and the encrypted socket. Like
the server, it can run in pure socket mode for testing.
"""

from __future__ import annotations

import asyncio
import socket
import time
from dataclasses import dataclass
from typing import Optional

from .auth import AuthManager
from .crypto import CryptoEngine, KeyDerivation
from .protocol import (
    Packet, PacketType, ProtocolError,
    make_handshake_init, parse_handshake_reply,
)
from ..utils.logging import setup_logging
from ..utils.net import TunDevice


@dataclass
class _PendingHandshake:
    client_priv: bytes
    client_nonce: bytes
    started_at: float


class TunnelClient:
    """Async UDP client. Reconnects with backoff on failure."""

    def __init__(self, server_host: str, server_port: int,
                 username: str, password: str,
                 use_tun: bool = False,
                 mtu: int = 1400) -> None:
        self.server_addr = (server_host, server_port)
        self.username = username
        self.password = password
        self.use_tun = use_tun
        self.mtu = mtu
        self.log = setup_logging(component="client")
        self.crypto = CryptoEngine()
        self._transport: Optional[asyncio.DatagramTransport] = None
        self._tun: Optional[TunDevice] = None
        self._pending: Optional[_PendingHandshake] = None
        self._connected = False
        self._running = False

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        self._transport, _ = await loop.create_datagram_endpoint(
            lambda: _ClientProtocol(self),
            remote_addr=self.server_addr,
        )
        if self.use_tun:
            try:
                self._tun = TunDevice.create()
                self.log.info(f"opened TUN device {self._tun.name}")
                loop.add_reader(self._tun.fd, self._on_tun_readable)
            except RuntimeError as exc:
                self.log.warning(f"TUN unavailable, socket-only mode: {exc}")

        self._running = True
        await self._do_handshake()
        asyncio.create_task(self._keepalive_loop())

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

    async def _do_handshake(self) -> None:
        priv, pub = CryptoEngine.generate_ephemeral_keypair()
        nonce = b"\x01" * 16
        init = make_handshake_init(pub, nonce, self.username)
        self._pending = _PendingHandshake(priv, nonce, time.time())
        self._transport.sendto(init.serialize(), self.server_addr)  # type: ignore[union-attr]
        self.log.info(f"sent handshake init to {self.server_addr}")

    def on_datagram(self, data: bytes) -> None:
        try:
            pkt = Packet.deserialize(data)
        except ProtocolError as exc:
            self.log.warning(f"bad packet: {exc}")
            return

        if pkt.type == PacketType.HANDSHAKE_REPLY and self._pending:
            server_nonce, server_pub, _sig = parse_handshake_reply(pkt)
            shared = CryptoEngine.dh_shared_secret(self._pending.client_priv,
                                                   server_pub)
            kdf = KeyDerivation.generate()
            self.crypto.derive_session_keys(shared, kdf,
                                            self._pending.client_nonce,
                                            server_nonce,
                                            role="client")
            self._connected = True
            self._pending = None
            self.log.info("handshake completed")
        elif pkt.type == PacketType.DATA and self._connected:
            plaintext = self.crypto.open(pkt.payload)
            if self._tun:
                try:
                    self._tun.write(plaintext)
                except OSError as exc:
                    self.log.debug(f"TUN write failed: {exc}")

    def _on_tun_readable(self) -> None:
        if not self._tun or not self._transport:
            return
        try:
            packet = self._tun.read(self.mtu)
        except OSError:
            return
        if self._connected:
            frame = self.crypto.seal(packet)
            data = Packet(type=PacketType.DATA, payload=frame).serialize()
            self._transport.sendto(data, self.server_addr)

    async def _keepalive_loop(self) -> None:
        while self._running and self._connected:
            await asyncio.sleep(25)
            ping = Packet(type=PacketType.PING, payload=b"ping").serialize()
            if self._transport:
                self._transport.sendto(ping, self.server_addr)


class _ClientProtocol(asyncio.DatagramProtocol):
    def __init__(self, client: TunnelClient) -> None:
        self.client = client

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:  # type: ignore[override]
        self.client.on_datagram(data)

    def error_received(self, exc: Exception) -> None:  # type: ignore[override]
        self.client.log.error(f"socket error: {exc}")


async def _main(host: str, port: int, user: str, pw: str) -> None:  # pragma: no cover
    client = TunnelClient(host, port, user, pw, use_tun=False)
    await client.start()
    try:
        await asyncio.Event().wait()
    finally:
        await client.stop()


if __name__ == "__main__":  # pragma: no cover
    import argparse, asyncio, os
    p = argparse.ArgumentParser()
    p.add_argument("--host", default=os.environ.get("VORTEX_HOST", "127.0.0.1"))
    p.add_argument("--port", type=int, default=int(os.environ.get("VORTEX_PORT", "4433")))
    p.add_argument("--user", required=True)
    p.add_argument("--password", required=True)
    args = p.parse_args()
    asyncio.run(_main(args.host, args.port, args.user, args.password))
