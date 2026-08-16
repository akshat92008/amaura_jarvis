"""Network egress controls shared by agents and production provider adapters.

All production HTTP(S) requests are pinned to the exact public IP address that
was validated. TLS certificate verification and SNI still use the original
hostname. Redirects are rejected and are never followed.
"""

from __future__ import annotations

import http.client
import ipaddress
import json
import socket
import ssl
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from jarvis.amaura.models import GovernanceError

_BLOCKED_HOSTS = {"metadata.google.internal", "metadata.aws.internal", "instance-data"}


@dataclass(frozen=True, slots=True)
class ValidatedDestination:
    url: str
    scheme: str
    hostname: str
    port: int
    addresses: tuple[str, ...]


def _address_is_public(value: str) -> bool:
    try:
        return ipaddress.ip_address(value).is_global
    except ValueError:
        return False


def validate_public_url(
    url: str,
    *,
    resolve: bool = True,
    resolver: Callable[..., list[tuple[Any, ...]]] = socket.getaddrinfo,
) -> ValidatedDestination:
    """Validate the literal URL and every resolved address."""
    try:
        parsed = urlsplit(url)
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as exc:
        raise GovernanceError("Malformed outbound URL") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise GovernanceError("Only absolute HTTP(S) URLs are allowed")
    if parsed.username or parsed.password:
        raise GovernanceError("URLs containing credentials are not allowed")
    hostname = parsed.hostname.rstrip(".").lower()
    if (
        hostname == "localhost"
        or hostname.endswith((".localhost", ".local", ".internal"))
        or hostname in _BLOCKED_HOSTS
    ):
        raise GovernanceError("Local and metadata-service hosts are blocked")

    addresses: set[str] = set()
    try:
        literal = ipaddress.ip_address(hostname)
    except ValueError:
        literal = None
    if literal is not None:
        addresses.add(str(literal))
    elif resolve:
        try:
            records = resolver(hostname, port, type=socket.SOCK_STREAM)
        except OSError as exc:
            raise GovernanceError(f"Outbound hostname could not be resolved: {hostname}") from exc
        for record in records:
            sockaddr = record[4]
            if sockaddr:
                addresses.add(str(sockaddr[0]).split("%", 1)[0])
        if not addresses:
            raise GovernanceError(f"Outbound hostname resolved to no usable address: {hostname}")
    if any(not _address_is_public(address) for address in addresses):
        raise GovernanceError("Private, loopback, link-local, reserved, and metadata network destinations are blocked")
    return ValidatedDestination(
        url=url, scheme=parsed.scheme, hostname=hostname, port=port, addresses=tuple(sorted(addresses))
    )


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, hostname: str, address: str, port: int, *, timeout: float):
        super().__init__(hostname, port=port, timeout=timeout)
        self._validated_address = address

    def connect(self) -> None:
        self.sock = socket.create_connection((self._validated_address, self.port), self.timeout, self.source_address)
        if self._tunnel_host:
            self._tunnel()


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, hostname: str, address: str, port: int, *, timeout: float):
        super().__init__(hostname, port=port, timeout=timeout, context=ssl.create_default_context())
        self._validated_address = address

    def connect(self) -> None:
        raw = socket.create_connection((self._validated_address, self.port), self.timeout, self.source_address)
        if self._tunnel_host:
            self.sock = raw
            self._tunnel()
            raw = self.sock
        # Certificate verification and SNI remain bound to the validated hostname.
        self.sock = self._context.wrap_socket(raw, server_hostname=self.host)


def _path_and_query(url: str) -> str:
    parsed = urlsplit(url)
    path = parsed.path or "/"
    return f"{path}?{parsed.query}" if parsed.query else path


def _pinned_request(
    destination: ValidatedDestination,
    *,
    method: str,
    body: bytes | None,
    headers: dict[str, str],
    timeout: float,
    max_bytes: int,
) -> tuple[int, bytes, dict[str, str]]:
    if not destination.addresses:
        raise GovernanceError("Outbound destination has no validated address")
    # The connection never performs a second hostname lookup.
    address = destination.addresses[0]
    connection_cls = _PinnedHTTPSConnection if destination.scheme == "https" else _PinnedHTTPConnection
    connection = connection_cls(destination.hostname, address, destination.port, timeout=timeout)
    request_headers = {
        "Host": destination.hostname if destination.port in {80, 443} else f"{destination.hostname}:{destination.port}",
        **headers,
    }
    try:
        connection.request(method.upper(), _path_and_query(destination.url), body=body, headers=request_headers)
        response = connection.getresponse()
        if 300 <= int(response.status) < 400:
            raise GovernanceError(f"Outbound redirects are disabled (provider returned HTTP {response.status})")
        raw = response.read(max_bytes + 1)
        if len(raw) > max_bytes:
            raise GovernanceError(f"Provider response exceeded the {max_bytes} byte limit")
        return int(response.status), raw, {str(k).lower(): str(v) for k, v in response.getheaders()}
    except GovernanceError:
        raise
    except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
        raise GovernanceError("Provider request failed") from exc
    finally:
        connection.close()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        raise GovernanceError(f"Outbound redirects are disabled (provider returned HTTP {code})")


def request_json(
    url: str,
    *,
    method: str = "POST",
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 20.0,
    opener: Any | None = None,
) -> tuple[int, dict[str, Any], dict[str, str]]:
    """Send one redirect-free JSON request pinned to the validated IP."""
    destination = validate_public_url(url, resolve=True)
    body = None
    request_headers = {"Accept": "application/json", "User-Agent": "Amaura-Internal-Workforce/1.2", **(headers or {})}
    if payload is not None:
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        request_headers["Content-Type"] = "application/json"
    timeout = max(1.0, min(timeout, 60.0))
    if opener is not None:  # test-only compatibility; production callers do not inject an opener
        request = urllib.request.Request(url, data=body, headers=request_headers, method=method.upper())
        try:
            with opener.open(request, timeout=timeout) as response:
                raw = response.read(2_000_001)
                status = int(response.status)
                if response.geturl() != url:
                    raise GovernanceError("Provider transport changed destination")
                response_headers = {str(k).lower(): str(v) for k, v in response.headers.items()}
        except GovernanceError:
            raise
        except (OSError, urllib.error.HTTPError, urllib.error.URLError) as exc:
            raise GovernanceError("Provider request failed") from exc
    else:
        status, raw, response_headers = _pinned_request(
            destination, method=method, body=body, headers=request_headers, timeout=timeout, max_bytes=2_000_000
        )
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GovernanceError("Provider returned invalid JSON") from exc
    if not isinstance(decoded, dict):
        raise GovernanceError("Provider response must be a JSON object")
    return status, decoded, response_headers


def request_form_json(
    url: str,
    *,
    payload: dict[str, Any],
    headers: dict[str, str] | None = None,
    timeout: float = 20.0,
) -> tuple[int, dict[str, Any], dict[str, str]]:
    """Send one redirect-free form request pinned to the validated IP."""
    from urllib.parse import urlencode

    destination = validate_public_url(url, resolve=True)
    body = urlencode(payload).encode("utf-8")
    request_headers = {
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "Amaura-Internal-Workforce/3.5",
        **(headers or {}),
    }
    status, raw, response_headers = _pinned_request(
        destination,
        method="POST",
        body=body,
        headers=request_headers,
        timeout=max(1.0, min(timeout, 60.0)),
        max_bytes=2_000_000,
    )
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GovernanceError("Provider returned invalid JSON") from exc
    if not isinstance(decoded, dict):
        raise GovernanceError("Provider response must be a JSON object")
    return status, decoded, response_headers


def request_bytes(
    url: str,
    *,
    method: str = "GET",
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 20.0,
    max_response_bytes: int = 2_000_000,
) -> tuple[int, bytes, dict[str, str]]:
    """Send one redirect-free request pinned to the validated public IP.

    This is the common transport for APIs that accept multipart uploads or return
    an empty body with authoritative identifiers in response headers.  Callers
    must provide an already serialized body and explicit content type.
    """
    destination = validate_public_url(url, resolve=True)
    request_headers = {
        "Accept": "application/json",
        "User-Agent": "Amaura-Internal-Workforce/3.6",
        **(headers or {}),
    }
    return _pinned_request(
        destination,
        method=method,
        body=body,
        headers=request_headers,
        timeout=max(1.0, min(float(timeout), 60.0)),
        max_bytes=max(1, min(int(max_response_bytes), 10_000_000)),
    )


def decode_json_object(raw: bytes, *, allow_empty: bool = False) -> dict[str, Any]:
    """Decode a provider JSON object with a precise empty-body contract."""
    if not raw:
        if allow_empty:
            return {}
        raise GovernanceError("Provider returned an empty response")
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GovernanceError("Provider returned invalid JSON") from exc
    if not isinstance(decoded, dict):
        raise GovernanceError("Provider response must be a JSON object")
    return decoded


def fetch_public_bytes(url: str, *, max_length: int = 100_000) -> tuple[bytes, dict[str, Any]]:
    destination = validate_public_url(url, resolve=True)
    limit = max(1, min(int(max_length), 2_000_000))
    status, raw, headers = _pinned_request(
        destination,
        method="GET",
        body=None,
        headers={"Accept": "text/*,application/json,application/xml", "User-Agent": "Amaura-Evidence-Fetcher/1.2"},
        timeout=15.0,
        max_bytes=limit,
    )
    if not 200 <= status < 300:
        raise GovernanceError(f"Public evidence fetch returned HTTP {status}")
    return raw, {
        "validated_hostname": destination.hostname,
        "validated_ip": destination.addresses[0],
        "status": status,
        "headers": headers,
    }


def fetch_public_text(url: str, *, max_length: int = 10_000) -> str:
    raw, _metadata = fetch_public_bytes(url, max_length=max_length)
    return raw.decode("utf-8", errors="replace")


__all__ = [
    "ValidatedDestination",
    "decode_json_object",
    "fetch_public_bytes",
    "fetch_public_text",
    "request_bytes",
    "request_form_json",
    "request_json",
    "validate_public_url",
]
