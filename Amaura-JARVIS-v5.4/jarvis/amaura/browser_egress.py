"""Ephemeral browser egress proxy with public-network-only CONNECT handling.

The proxy is intentionally small and conservative. Browsers may tunnel HTTPS to
validated public destinations only. The proxy resolves once, pins the selected
public IP for the TCP connection, blocks local/private/link-local/metadata hosts,
and never exposes a LAN listener.
"""

from __future__ import annotations

import contextlib
import select
import socket
import socketserver
import threading
from dataclasses import dataclass

from jarvis.amaura.models import GovernanceError
from jarvis.amaura.network import validate_public_url


class _ProxyHandler(socketserver.StreamRequestHandler):
    timeout = 20

    def handle(self) -> None:
        try:
            first = self.rfile.readline(8192).decode("iso-8859-1", "replace").strip()
        except OSError:
            return
        if not first:
            return
        parts = first.split()
        if len(parts) != 3:
            self._reject(400, "Bad Request")
            return
        method, target, _version = parts
        # Drain headers with strict bounds. We intentionally ignore proxy auth/cookies.
        total = 0
        while True:
            line = self.rfile.readline(8192)
            if not line or line in {b"\r\n", b"\n"}:
                break
            total += len(line)
            if total > 64 * 1024:
                self._reject(431, "Headers Too Large")
                return
        if method.upper() != "CONNECT":
            # Keep the research browser HTTPS-only. This removes plaintext proxying
            # and makes destination enforcement occur on every TLS connection.
            self._reject(403, "HTTPS Required")
            return
        try:
            host, port = self._parse_connect_target(target)
            destination = validate_public_url(f"https://{host}:{port}", resolve=True)
            if port not in {443, 8443}:
                raise GovernanceError("Browser egress permits HTTPS ports 443/8443 only")
            if not destination.addresses:
                raise GovernanceError("No validated browser egress address")
            upstream = socket.create_connection((destination.addresses[0], port), timeout=15)
        except (GovernanceError, OSError, ValueError):
            self._reject(403, "Destination Blocked")
            return
        try:
            self.wfile.write(b"HTTP/1.1 200 Connection Established\r\nConnection: close\r\n\r\n")
            self.wfile.flush()
            self._relay(self.connection, upstream)
        finally:
            with contextlib.suppress(OSError):
                upstream.close()

    @staticmethod
    def _parse_connect_target(target: str) -> tuple[str, int]:
        if target.startswith("["):
            end = target.find("]")
            if end < 0 or end + 2 > len(target):
                raise ValueError("Malformed IPv6 CONNECT target")
            return target[1:end], int(target[end + 2 :])
        if ":" not in target:
            return target, 443
        host, raw_port = target.rsplit(":", 1)
        return host, int(raw_port)

    @staticmethod
    def _relay(client: socket.socket, upstream: socket.socket) -> None:
        client.setblocking(False)
        upstream.setblocking(False)
        sockets = [client, upstream]
        idle_rounds = 0
        while True:
            try:
                readable, _, exceptional = select.select(sockets, [], sockets, 1.0)
            except OSError:
                return
            if exceptional:
                return
            if not readable:
                idle_rounds += 1
                if idle_rounds >= 60:
                    return
                continue
            idle_rounds = 0
            for source in readable:
                target = upstream if source is client else client
                try:
                    data = source.recv(64 * 1024)
                except (BlockingIOError, OSError):
                    continue
                if not data:
                    return
                try:
                    target.sendall(data)
                except OSError:
                    return

    def _reject(self, status: int, reason: str) -> None:
        body = f"Amaura browser egress: {reason}\n".encode()
        with contextlib.suppress(OSError):
            self.wfile.write(
                f"HTTP/1.1 {status} {reason}\r\nContent-Type: text/plain\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode()
                + body
            )
            self.wfile.flush()


class _ThreadingProxy(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


@dataclass(slots=True)
class BrowserEgressProxy:
    server: _ThreadingProxy
    thread: threading.Thread

    @classmethod
    def start(cls) -> BrowserEgressProxy:
        server = _ThreadingProxy(("127.0.0.1", 0), _ProxyHandler)
        thread = threading.Thread(target=server.serve_forever, name="amaura-browser-egress", daemon=True)
        thread.start()
        return cls(server=server, thread=thread)

    @property
    def url(self) -> str:
        host, port = self.server.server_address[:2]
        host_text = host.decode() if isinstance(host, bytes) else str(host)
        return f"http://{host_text}:{port}"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def __enter__(self) -> BrowserEgressProxy:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        self.close()


__all__ = ["BrowserEgressProxy"]
