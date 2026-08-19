"""ARCH-local founder session convergence for HTTP and WebSocket surfaces.

The legacy HUD historically asked separately for JARVIS API auth and the Amaura
operator key. ARCH runs as one local founder-facing product, so an already
validated local JARVIS session is promoted to an *ephemeral* founder session.
The long-lived AMAURA_OPERATOR_KEY never leaves the Python process.

Founder-approval authority is intentionally NOT converged here. Consequences
that require AMAURA_APPROVAL_KEY continue to stop at the existing approval
boundary.
"""

from __future__ import annotations

import base64
import hmac
import os
import secrets
from http.cookies import SimpleCookie
from typing import Any, Awaitable, Callable

from jarvis.network_security import MIN_API_KEY_LENGTH, api_key_matches

ASGIApp = Callable[[dict[str, Any], Callable[..., Awaitable[Any]], Callable[..., Awaitable[Any]]], Awaitable[Any]]


class ArchFounderGateway:
    """Promote one authenticated loopback JARVIS session to operator authority.

    Authentication remains two-stage:
    1. the browser/desktop proves JARVIS_API_KEY;
    2. this gateway issues a process-lifetime opaque HttpOnly cookie.

    Subsequent same-process requests may use that cookie. The gateway injects
    the operator header internally so the rest of the already-qualified server
    can keep its existing fail-closed authorization logic unchanged.
    """

    COOKIE_NAME = "arch_founder_session"
    COOKIE_MAX_AGE_SECONDS = 12 * 60 * 60

    def __init__(self, app: ASGIApp, *, session_token: str | None = None) -> None:
        self.app = app
        self.session_token = session_token or secrets.token_urlsafe(48)

    @staticmethod
    def _header(scope: dict[str, Any], name: str) -> str:
        wanted = name.lower().encode("latin-1")
        for key, value in scope.get("headers") or []:
            if bytes(key).lower() == wanted:
                return bytes(value).decode("latin-1")
        return ""

    @staticmethod
    def _is_loopback(scope: dict[str, Any]) -> bool:
        client = scope.get("client") or ("", 0)
        host = str(client[0] or "").strip().lower()
        return host in {"127.0.0.1", "::1", "localhost"}

    @classmethod
    def _protocol_api_key(cls, scope: dict[str, Any]) -> str:
        protocols = cls._header(scope, "sec-websocket-protocol")
        for raw in protocols.split(","):
            token = raw.strip()
            if not token.startswith("jarvis-key."):
                continue
            encoded = token[len("jarvis-key.") :]
            try:
                padding = "=" * ((4 - len(encoded) % 4) % 4)
                return base64.urlsafe_b64decode((encoded + padding).encode("ascii")).decode("utf-8")
            except (ValueError, UnicodeDecodeError):
                return ""
        return ""

    def _cookie_valid(self, scope: dict[str, Any]) -> bool:
        raw = self._header(scope, "cookie")
        if not raw:
            return False
        cookie = SimpleCookie()
        try:
            cookie.load(raw)
        except Exception:
            return False
        morsel = cookie.get(self.COOKIE_NAME)
        return bool(morsel and hmac.compare_digest(morsel.value, self.session_token))

    def _jarvis_key_valid(self, scope: dict[str, Any]) -> bool:
        expected = os.environ.get("JARVIS_API_KEY", "").strip()
        if len(expected) < MIN_API_KEY_LENGTH:
            return False
        supplied = self._header(scope, "x-jarvis-key").strip()
        if scope.get("type") == "websocket" and not supplied:
            supplied = self._protocol_api_key(scope).strip()
        return bool(supplied and api_key_matches(supplied, expected))

    def _founder_session_valid(self, scope: dict[str, Any]) -> bool:
        return self._is_loopback(scope) and (self._cookie_valid(scope) or self._jarvis_key_valid(scope))

    @staticmethod
    def _replace_header(scope: dict[str, Any], name: str, value: str) -> None:
        encoded_name = name.lower().encode("latin-1")
        headers = [(bytes(k), bytes(v)) for k, v in (scope.get("headers") or []) if bytes(k).lower() != encoded_name]
        headers.append((encoded_name, value.encode("latin-1")))
        scope["headers"] = headers

    def _inject_operator(self, scope: dict[str, Any]) -> bool:
        if os.environ.get("ARCH_RUNTIME", "0") != "1":
            return False
        if not self._founder_session_valid(scope):
            return False
        operator_key = os.environ.get("AMAURA_OPERATOR_KEY", "")
        if not operator_key:
            return False
        self._replace_header(scope, "x-amaura-operator-key", operator_key)
        return True

    def _cookie_header(self) -> bytes:
        return (
            f"{self.COOKIE_NAME}={self.session_token}; Path=/; Max-Age={self.COOKIE_MAX_AGE_SECONDS}; "
            "HttpOnly; SameSite=Strict"
        ).encode("latin-1")

    async def __call__(self, scope: dict[str, Any], receive, send) -> None:
        scope_type = scope.get("type")
        if scope_type not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return

        # Work on a shallow copy so callers/tests do not observe header mutation.
        local_scope = dict(scope)
        local_scope["headers"] = list(scope.get("headers") or [])
        had_cookie = self._cookie_valid(local_scope)
        authenticated = self._founder_session_valid(local_scope)
        self._inject_operator(local_scope)

        if scope_type != "http" or not authenticated or had_cookie:
            await self.app(local_scope, receive, send)
            return

        async def send_with_session(message: dict[str, Any]) -> None:
            if message.get("type") == "http.response.start":
                headers = list(message.get("headers") or [])
                headers.append((b"set-cookie", self._cookie_header()))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(local_scope, receive, send_with_session)


def install_arch_gateway() -> None:
    """Install the gateway exactly once on the canonical JARVIS server app."""
    import jarvis.server as server

    if isinstance(server.app, ArchFounderGateway):
        return
    server.app = ArchFounderGateway(server.app)


__all__ = ["ArchFounderGateway", "install_arch_gateway"]
