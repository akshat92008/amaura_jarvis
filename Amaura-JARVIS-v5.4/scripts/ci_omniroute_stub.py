#!/usr/bin/env python3
"""CI-only OpenAI-compatible cognition stub for platform qualification.

The stub exists solely so hosted macOS CI can exercise JARVIS's real HTTP
provider path without external credentials. It does not replace production
provider certification, which remains the responsibility of the live doctor.
"""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


def _message_text(payload: dict[str, Any]) -> str:
    messages = payload.get("messages") or []
    return "\n".join(
        str(item.get("content") or "")
        for item in messages
        if isinstance(item, dict)
    )


def _completion_for(payload: dict[str, Any]) -> str:
    text = _message_text(payload)
    lower = text.lower()
    if "classify the founder message" in lower:
        return '{"intent":"conversation"}'
    if "what is 2 + 2" in lower or "what is 2+2" in lower:
        return "4"
    return "CI cognition transport is available."


class Handler(BaseHTTPRequestHandler):
    server_version = "AmauraCIProvider/1.0"

    def log_message(self, _format: str, *_args: Any) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            body = b'{"ok":true}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802
        if self.path not in {"/chat/completions", "/v1/chat/completions"}:
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, json.JSONDecodeError):
            self.send_error(400)
            return
        if not isinstance(payload, dict):
            self.send_error(400)
            return

        model = str(payload.get("model") or "ci-cognition")
        response = {
            "id": "ci-omniroute-1",
            "object": "chat.completion",
            "model": model,
            "provider": "ci-local-stub",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": _completion_for(payload)},
                    "finish_reason": "stop",
                }
            ],
        }
        body = json.dumps(response).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Request-Id", "ci-omniroute-1")
        self.send_header("X-Resolved-Provider", "ci-local-stub")
        self.send_header("X-Resolved-Model", model)
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    port = int(os.environ.get("AMAURA_CI_PROVIDER_PORT", "18765"))
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
