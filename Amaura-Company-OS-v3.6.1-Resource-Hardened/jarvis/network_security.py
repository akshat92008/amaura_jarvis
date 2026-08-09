"""Network binding and API authentication helpers for JARVIS/Amaura.

The server is local-first. Any non-loopback bind or peer must fail closed unless
an independently generated API key is configured. These helpers intentionally
avoid trusting forwarded headers because the default server is not a proxy-aware
internet service.
"""
from __future__ import annotations

import base64
import hmac
import ipaddress
import os
from collections.abc import Mapping
from typing import Any

LOOPBACK_NAMES = frozenset({"localhost", "ip6-localhost", "localhost.localdomain"})
WILDCARD_HOSTS = frozenset({"", "*", "0.0.0.0", "::", "[::]"})
MIN_API_KEY_LENGTH = 24


def _clean_host(value: Any) -> str:
    host = str(value or "").strip().lower()
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    if "%" in host:  # IPv6 zone identifier
        host = host.split("%", 1)[0]
    return host.rstrip(".")


def is_loopback_host(value: Any) -> bool:
    """Return True only for an explicit loopback hostname or address."""
    host = _clean_host(value)
    if host in LOOPBACK_NAMES:
        return True
    if host in WILDCARD_HOSTS:
        return False
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def is_ip_address(value: Any) -> bool:
    host = _clean_host(value)
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def effective_bind_host() -> str:
    return os.environ.get(
        "JARVIS_EFFECTIVE_BIND_HOST",
        os.environ.get("JARVIS_HOST", "127.0.0.1"),
    ).strip() or "127.0.0.1"


def validate_bind_security(host: str, api_key: str | None = None) -> None:
    """Reject externally reachable binds that do not have strong API auth."""
    key = (api_key if api_key is not None else os.environ.get("JARVIS_API_KEY", "")).strip()
    if not is_loopback_host(host) and len(key) < MIN_API_KEY_LENGTH:
        raise RuntimeError(
            "Refusing non-loopback JARVIS bind without a strong JARVIS_API_KEY "
            f"({MIN_API_KEY_LENGTH}+ characters required)"
        )


def _scope_host(scope: Mapping[str, Any], field: str) -> str:
    value = scope.get(field)
    if isinstance(value, (tuple, list)) and value:
        return str(value[0] or "")
    return ""


def scope_is_remote(scope: Mapping[str, Any]) -> bool:
    """Determine remote exposure from configured bind and concrete socket peers.

    Unknown synthetic hostnames used by ASGI test clients are ignored. Real
    network peers are represented as IP addresses and are evaluated directly.
    """
    if not is_loopback_host(effective_bind_host()):
        return True
    for field in ("server", "client"):
        host = _scope_host(scope, field)
        if is_ip_address(host) and not is_loopback_host(host):
            return True
    return False


def supplied_api_key(headers: Mapping[str, str], query_params: Mapping[str, str] | None = None) -> str:
    direct = str(headers.get("x-jarvis-key", "") or headers.get("X-Jarvis-Key", "")).strip()
    if direct:
        return direct
    if query_params is not None:
        query_value = str(query_params.get("api_key", "")).strip()
        if query_value:
            return query_value
    protocols = str(headers.get("sec-websocket-protocol", "") or headers.get("Sec-WebSocket-Protocol", ""))
    for raw_protocol in protocols.split(","):
        protocol = raw_protocol.strip()
        if not protocol.startswith("jarvis-key."):
            continue
        encoded = protocol.removeprefix("jarvis-key.")
        padding = "=" * (-len(encoded) % 4)
        try:
            return base64.urlsafe_b64decode(encoded + padding).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return ""
    return ""


def api_key_matches(supplied: str, expected: str | None = None) -> bool:
    configured = (expected if expected is not None else os.environ.get("JARVIS_API_KEY", "")).strip()
    return bool(configured and supplied and hmac.compare_digest(supplied, configured))


def browser_host(host: str) -> str:
    """Return a safe local URL host for wildcard listeners."""
    return "127.0.0.1" if _clean_host(host) in WILDCARD_HOSTS else host
