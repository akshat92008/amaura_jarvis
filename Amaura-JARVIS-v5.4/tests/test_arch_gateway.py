from __future__ import annotations

import asyncio
import base64
import json

from jarvis.arch_gateway import ArchFounderGateway


def _headers(scope):
    return {bytes(k).decode("latin-1").lower(): bytes(v).decode("latin-1") for k, v in scope.get("headers", [])}


def test_arch_gateway_promotes_authenticated_loopback_http_without_exposing_operator(monkeypatch):
    api_key = "j" * 48
    operator_key = "operator-secret-value"
    monkeypatch.setenv("ARCH_RUNTIME", "1")
    monkeypatch.setenv("JARVIS_API_KEY", api_key)
    monkeypatch.setenv("AMAURA_OPERATOR_KEY", operator_key)

    observed = {}
    sent = []

    async def app(scope, receive, send):
        observed.update(_headers(scope))
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    gateway = ArchFounderGateway(app, session_token="ephemeral-session")
    scope = {
        "type": "http",
        "client": ("127.0.0.1", 54321),
        "headers": [(b"x-jarvis-key", api_key.encode())],
    }

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    asyncio.run(gateway(scope, receive, send))

    assert observed["x-amaura-operator-key"] == operator_key
    response_headers = [item for message in sent if message.get("type") == "http.response.start" for item in message["headers"]]
    cookies = [value.decode("latin-1") for key, value in response_headers if key.lower() == b"set-cookie"]
    assert any("arch_founder_session=ephemeral-session" in value for value in cookies)
    assert all(operator_key not in value for value in cookies)


def test_arch_gateway_reuses_ephemeral_cookie_for_operator_api(monkeypatch):
    monkeypatch.setenv("ARCH_RUNTIME", "1")
    monkeypatch.setenv("JARVIS_API_KEY", "j" * 48)
    monkeypatch.setenv("AMAURA_OPERATOR_KEY", "operator-secret-value")

    observed = {}

    async def app(scope, receive, send):
        observed.update(_headers(scope))
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    gateway = ArchFounderGateway(app, session_token="ephemeral-session")
    scope = {
        "type": "http",
        "client": ("127.0.0.1", 12345),
        "headers": [(b"cookie", b"arch_founder_session=ephemeral-session")],
    }

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(_message):
        return None

    asyncio.run(gateway(scope, receive, send))
    assert observed["x-amaura-operator-key"] == "operator-secret-value"


def test_arch_gateway_promotes_authenticated_websocket_protocol_and_chat_payload(monkeypatch):
    api_key = "k" * 48
    operator_key = "operator-secret-value"
    monkeypatch.setenv("ARCH_RUNTIME", "1")
    monkeypatch.setenv("JARVIS_API_KEY", api_key)
    monkeypatch.setenv("AMAURA_OPERATOR_KEY", operator_key)

    encoded = base64.urlsafe_b64encode(api_key.encode()).decode().rstrip("=")
    observed = {}
    observed_message = {}

    async def app(scope, receive, send):
        observed.update(_headers(scope))
        message = await receive()
        observed_message.update(json.loads(message["text"]))

    gateway = ArchFounderGateway(app, session_token="ephemeral-session")
    scope = {
        "type": "websocket",
        "client": ("::1", 12345),
        "headers": [(b"sec-websocket-protocol", f"jarvis, jarvis-key.{encoded}".encode())],
    }

    async def receive():
        return {"type": "websocket.receive", "text": json.dumps({"type": "chat", "content": "Open Safari"})}

    async def send(_message):
        return None

    asyncio.run(gateway(scope, receive, send))
    assert observed["x-amaura-operator-key"] == operator_key
    assert observed_message["operator_key"] == operator_key
    assert observed_message["content"] == "Open Safari"


def test_arch_gateway_does_not_promote_remote_or_unauthenticated_requests(monkeypatch):
    monkeypatch.setenv("ARCH_RUNTIME", "1")
    monkeypatch.setenv("JARVIS_API_KEY", "j" * 48)
    monkeypatch.setenv("AMAURA_OPERATOR_KEY", "operator-secret-value")

    observed = {}

    async def app(scope, receive, send):
        observed.update(_headers(scope))

    gateway = ArchFounderGateway(app, session_token="ephemeral-session")
    scope = {"type": "http", "client": ("10.0.0.5", 12345), "headers": []}

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(_message):
        return None

    asyncio.run(gateway(scope, receive, send))
    assert "x-amaura-operator-key" not in observed
