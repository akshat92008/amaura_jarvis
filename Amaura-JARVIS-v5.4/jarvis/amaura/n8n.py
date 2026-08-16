"""Hardened n8n webhook client for governed external actions."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlsplit

from jarvis.amaura.models import GovernanceError
from jarvis.amaura.network import request_json, validate_public_url


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        raise GovernanceError(f"n8n redirects are disabled (HTTP {code})")


class N8nClient:
    """Trigger configured n8n webhooks with strict transport and response limits."""

    def __init__(self, base_url: str | None = None, api_key: str | None = None):
        self.base_url = (base_url if base_url is not None else os.environ.get("N8N_BASE_URL", "")).strip().rstrip("/")
        self.api_key = (api_key if api_key is not None else os.environ.get("N8N_API_KEY", "")).strip()

    @property
    def enabled(self) -> bool:
        return os.environ.get("AMAURA_ENABLE_N8N", os.environ.get("USE_N8N", "0")) == "1"

    @property
    def configured(self) -> bool:
        return self.enabled and bool(self.base_url and self.api_key)

    def _local_request(self, url: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        parsed = urlsplit(url)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise GovernanceError("Local n8n is restricted to an explicit loopback HTTP endpoint")
        if os.environ.get("AMAURA_ALLOW_LOCAL_N8N", "0") != "1":
            raise GovernanceError("Local n8n requires AMAURA_ALLOW_LOCAL_N8N=1")
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        request = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
        )
        opener = urllib.request.build_opener(_NoRedirect())
        try:
            with opener.open(request, timeout=30) as response:
                raw = response.read(2_000_001)
                if len(raw) > 2_000_000:
                    raise GovernanceError("n8n response exceeded the 2 MB limit")
                status = int(response.status)
        except GovernanceError:
            raise
        except (OSError, urllib.error.HTTPError, urllib.error.URLError) as exc:
            raise GovernanceError("Local n8n request failed") from exc
        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GovernanceError("n8n returned invalid JSON") from exc
        if not isinstance(decoded, dict):
            raise GovernanceError("n8n response must be a JSON object")
        return status, decoded

    def trigger_webhook(self, webhook_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.configured:
            raise GovernanceError("n8n is not enabled and fully configured")
        webhook = webhook_id.strip().strip("/")
        if not webhook or any(part in webhook for part in ("..", "?", "#")):
            raise GovernanceError("Invalid n8n webhook identifier")
        url = f"{self.base_url}/webhook/{webhook}"
        parsed = urlsplit(url)
        if parsed.hostname in {"127.0.0.1", "localhost", "::1"}:
            status, response = self._local_request(url, payload)
        else:
            validate_public_url(url, resolve=True)
            status, response, _ = request_json(
                url,
                method="POST",
                payload=payload,
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=30,
            )
        if not 200 <= status < 300:
            raise GovernanceError(f"n8n webhook failed with HTTP {status}")
        if response.get("status") != "success":
            raise GovernanceError("n8n webhook did not return explicit success status")
        return response

    def stage_outreach(self, lead_id: str, channel: str, message_type: str, subject: str, body: str) -> dict[str, Any]:
        return self.trigger_webhook(
            os.environ.get("N8N_WEBHOOK_OUTREACH", "amaura-outreach"),
            {
                "lead_id": lead_id,
                "channel": channel,
                "message_type": message_type,
                "subject": subject,
                "body": body,
            },
        )

    def send_message(self, to: str, message: str, *, idempotency_key: str = "") -> dict[str, Any]:
        return self.trigger_webhook(
            os.environ.get("N8N_WEBHOOK_MESSAGE", "amaura-message"),
            {
                "to": to,
                "message": message,
                "idempotency_key": idempotency_key,
            },
        )

    def sync_crm(self, lead_id: str, data: dict[str, Any], *, idempotency_key: str) -> dict[str, Any]:
        return self.trigger_webhook(
            os.environ.get("N8N_WEBHOOK_CRM", "amaura-crm-sync"),
            {
                "lead_id": lead_id,
                "data": data,
                "idempotency_key": idempotency_key,
            },
        )


def get_n8n_client() -> N8nClient:
    return N8nClient()
