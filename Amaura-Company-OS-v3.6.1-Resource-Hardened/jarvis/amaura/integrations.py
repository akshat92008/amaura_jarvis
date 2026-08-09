"""Authenticated, idempotent provider adapters for approved external actions."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from email.message import EmailMessage
from typing import Any

from jarvis.amaura.models import GovernanceError
from jarvis.amaura.network import request_form_json, request_json, validate_public_url
from jarvis.amaura.n8n import get_n8n_client

Transport = Callable[..., tuple[int, dict[str, Any], dict[str, str]]]


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode()


def _receipt_key(value: str | None = None) -> bytes:
    raw = value if value is not None else os.environ.get(
        "AMAURA_PROVIDER_RECEIPT_KEY",
        "",
    )
    encoded = raw.encode()
    if len(encoded) < 32:
        raise GovernanceError(
            "AMAURA_PROVIDER_RECEIPT_KEY must contain at least 32 bytes"
        )
    return encoded


@dataclass(frozen=True, slots=True)
class ProviderReceipt:
    provider: str
    operation: str
    external_id: str
    idempotency_key: str
    payload_sha256: str
    status: str
    created_at: str
    signature: str
    thread_id: str = ""

    def to_dict(self) -> dict[str, str]:
        return asdict(self)

    def verify(self, *, key: str | None = None) -> bool:
        unsigned = {
            name: getattr(self, name)
            for name in (
                "provider",
                "operation",
                "external_id",
                "idempotency_key",
                "payload_sha256",
                "status",
                "created_at",
                "thread_id",
            )
        }
        expected = hmac.new(
            _receipt_key(key),
            _canonical_bytes(unsigned),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(self.signature, expected)

    @classmethod
    def issue(
        cls,
        *,
        provider: str,
        operation: str,
        external_id: str,
        idempotency_key: str,
        payload: Any,
        status: str,
        thread_id: str = "",
        key: str | None = None,
    ) -> ProviderReceipt:
        if not all(
            value.strip()
            for value in (
                provider,
                operation,
                external_id,
                idempotency_key,
                status,
            )
        ):
            raise GovernanceError("Provider receipt fields may not be empty")
        unsigned = {
            "provider": provider,
            "operation": operation,
            "external_id": external_id,
            "idempotency_key": idempotency_key,
            "payload_sha256": hashlib.sha256(
                _canonical_bytes(payload)
            ).hexdigest(),
            "status": status,
            "created_at": datetime.now(UTC).isoformat(),
            "thread_id": thread_id,
        }
        signature = hmac.new(
            _receipt_key(key),
            _canonical_bytes(unsigned),
            hashlib.sha256,
        ).hexdigest()
        return cls(**unsigned, signature=signature)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> ProviderReceipt:
        try:
            return cls(
                provider=str(value["provider"]),
                operation=str(value["operation"]),
                external_id=str(value["external_id"]),
                idempotency_key=str(value["idempotency_key"]),
                payload_sha256=str(value["payload_sha256"]),
                status=str(value["status"]),
                created_at=str(value["created_at"]),
                signature=str(value["signature"]),
                thread_id=str(value.get("thread_id", "")),
            )
        except KeyError as exc:
            raise GovernanceError("Provider receipt is incomplete") from exc


class GmailAdapter:
    """Send one approved email with renewable OAuth credentials and a signed receipt."""

    endpoint = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
    token_endpoint = "https://oauth2.googleapis.com/token"

    def __init__(
        self,
        *,
        access_token: str | None = None,
        transport: Transport = request_json,
        token_transport: Transport = request_form_json,
        receipt_key: str | None = None,
    ):
        self.access_token = access_token if access_token is not None else os.environ.get("AMAURA_GMAIL_ACCESS_TOKEN", "")
        self.client_id = os.environ.get("AMAURA_GMAIL_CLIENT_ID", "").strip()
        self.client_secret = os.environ.get("AMAURA_GMAIL_CLIENT_SECRET", "").strip()
        self.refresh_token = os.environ.get("AMAURA_GMAIL_REFRESH_TOKEN", "").strip()
        self.transport = transport
        self.token_transport = token_transport
        self.receipt_key = receipt_key

    @property
    def _has_refresh_credentials(self) -> bool:
        return bool(self.client_id and self.client_secret and self.refresh_token)

    @property
    def configured(self) -> bool:
        return bool(self.access_token or self._has_refresh_credentials)

    def _resolve_access_token(self, *, force_refresh: bool = False) -> str:
        if self.access_token and not force_refresh:
            return self.access_token
        if not self._has_refresh_credentials:
            raise GovernanceError("Gmail OAuth access or refresh credentials are not configured")
        status, response, _ = self.token_transport(
            self.token_endpoint,
            payload={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": self.refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=20,
        )
        if status != 200:
            raise GovernanceError(f"Gmail OAuth refresh failed with HTTP {status}")
        token = str(response.get("access_token", "")).strip()
        if not token:
            raise GovernanceError("Gmail OAuth refresh returned no access token")
        self.access_token = token
        return token

    def send(
        self,
        *,
        recipient: str,
        subject: str,
        body: str,
        idempotency_key: str,
        sender: str = "",
    ) -> ProviderReceipt:
        if not self.configured:
            raise GovernanceError("Gmail is not configured")
        if "@" not in recipient or not body.strip() or not idempotency_key.strip():
            raise GovernanceError("Gmail delivery requires recipient, body, and idempotency key")
        message = EmailMessage()
        message["To"] = recipient
        if sender:
            message["From"] = sender
        message["Subject"] = subject
        message.set_content(body)
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode().rstrip("=")

        def attempt(token: str):
            return self.transport(
                self.endpoint,
                method="POST",
                payload={"raw": raw},
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-Amaura-Idempotency-Key": idempotency_key,
                },
            )

        status, response, _ = attempt(self._resolve_access_token())
        # A definite 401 proves rejection before acceptance. One forced refresh is safe.
        if status == 401 and self._has_refresh_credentials:
            status, response, _ = attempt(self._resolve_access_token(force_refresh=True))
        if status not in {200, 201}:
            raise GovernanceError(f"Gmail delivery failed with HTTP {status}")
        external_id = str(response.get("id", "")).strip()
        thread_id = str(response.get("threadId", "")).strip()
        if not external_id:
            raise GovernanceError("Gmail returned no message identifier")
        return ProviderReceipt.issue(
            provider="gmail", operation="send_email", external_id=external_id,
            thread_id=thread_id, idempotency_key=idempotency_key,
            payload={"recipient": recipient, "subject": subject, "body": body},
            status="sent", key=self.receipt_key,
        )


class N8nEmailAdapter:
    """Send one approved email through a hardened n8n webhook."""

    def __init__(self, receipt_key: str | None = None):
        self.client = get_n8n_client()
        self.receipt_key = receipt_key

    @property
    def configured(self) -> bool:
        return self.client.configured

    def send(self, *, recipient: str, subject: str, body: str, idempotency_key: str, sender: str = "") -> ProviderReceipt:
        if not self.configured:
            raise GovernanceError("n8n is not configured")
        receipt_payload = {"recipient": recipient, "subject": subject, "body": body}
        payload_sha256 = hashlib.sha256(_canonical_bytes(receipt_payload)).hexdigest()
        result = self.client.trigger_webhook(
            os.environ.get("N8N_WEBHOOK_EMAIL", "amaura-email"),
            {
                "to": recipient, "from": sender, "subject": subject, "body": body,
                "idempotency_key": idempotency_key, "payload_sha256": payload_sha256,
            },
        )
        external_id = str(result.get("id", "")).strip()
        if not external_id:
            raise GovernanceError("n8n did not return a provider message ID")
        if result.get("recipient") != recipient:
            raise GovernanceError("n8n did not confirm the approved recipient")
        if result.get("idempotency_key") != idempotency_key:
            raise GovernanceError("n8n did not confirm the idempotency key")
        if result.get("payload_sha256") != payload_sha256:
            raise GovernanceError("n8n did not confirm the approved payload digest")
        return ProviderReceipt.issue(
            provider="n8n", operation="send_email", external_id=external_id,
            thread_id=str(result.get("threadId", "")).strip(),
            idempotency_key=idempotency_key, payload=receipt_payload,
            status="sent", key=self.receipt_key,
        )


class N8nCRMAdapter:
    """Synchronize CRM state through the durable outbox with exact receipt binding."""

    def __init__(self, receipt_key: str | None = None):
        self.client = get_n8n_client()
        self.receipt_key = receipt_key

    @property
    def configured(self) -> bool:
        return self.client.configured and bool(os.environ.get("N8N_WEBHOOK_CRM", "").strip())

    def sync(self, *, lead_id: str, data: dict[str, Any], idempotency_key: str) -> ProviderReceipt:
        if not self.configured:
            raise GovernanceError("n8n CRM synchronization is not configured")
        receipt_payload = {"lead_id": lead_id, "data": data}
        payload_sha256 = hashlib.sha256(_canonical_bytes(receipt_payload)).hexdigest()
        result = self.client.sync_crm(lead_id, data, idempotency_key=idempotency_key)
        external_id = str(result.get("id", "")).strip()
        if not external_id:
            raise GovernanceError("n8n CRM did not return an external record identifier")
        if result.get("lead_id") != lead_id:
            raise GovernanceError("n8n CRM did not confirm the lead identifier")
        if result.get("idempotency_key") != idempotency_key:
            raise GovernanceError("n8n CRM did not confirm the idempotency key")
        if result.get("payload_sha256") != payload_sha256:
            raise GovernanceError("n8n CRM did not confirm the payload digest")
        return ProviderReceipt.issue(
            provider="n8n", operation="sync_crm", external_id=external_id,
            idempotency_key=idempotency_key, payload=receipt_payload,
            status="synced", key=self.receipt_key,
        )


class IMessageAdapter:
    """Send one founder-approved iMessage from the durable outbox."""

    def __init__(self, receipt_key: str | None = None):
        self.receipt_key = receipt_key

    @property
    def configured(self) -> bool:
        import sys
        return os.environ.get("AMAURA_ENABLE_IMESSAGE", "0") == "1" and sys.platform == "darwin"

    def send(self, *, recipient: str, body: str, idempotency_key: str) -> ProviderReceipt:
        if not self.configured:
            raise GovernanceError("iMessage delivery is not enabled on macOS")
        if not recipient.strip() or not body.strip() or not idempotency_key.strip():
            raise GovernanceError("iMessage requires recipient, body, and idempotency key")
        from jarvis.tools.communication import send_imessage_local
        result = send_imessage_local(recipient, body)
        if result.startswith("❌"):
            raise GovernanceError(f"iMessage delivery failed: {result}")
        external_id = "imessage-" + hashlib.sha256(idempotency_key.encode()).hexdigest()[:24]
        return ProviderReceipt.issue(
            provider="imessage", operation="send_imessage", external_id=external_id,
            idempotency_key=idempotency_key,
            payload={"recipient": recipient, "body": body}, status="sent",
            key=self.receipt_key,
        )


class PrivatePublicationAdapter:
    """Create a private provider draft; it never performs a public publish."""

    def __init__(
        self,
        *,
        endpoint: str | None = None,
        access_token: str | None = None,
        transport: Transport = request_json,
        receipt_key: str | None = None,
    ):
        self.endpoint = (
            endpoint
            if endpoint is not None
            else os.environ.get("AMAURA_PUBLICATION_ENDPOINT", "")
        )
        self.access_token = (
            access_token
            if access_token is not None
            else os.environ.get("AMAURA_PUBLICATION_ACCESS_TOKEN", "")
        )
        self.transport = transport
        self.receipt_key = receipt_key

    @property
    def configured(self) -> bool:
        return bool(self.endpoint and self.access_token)

    def create_private_draft(
        self,
        *,
        payload: dict[str, Any],
        idempotency_key: str,
    ) -> ProviderReceipt:
        if not self.configured:
            raise GovernanceError("Private publication adapter is not configured")
        validate_public_url(self.endpoint, resolve=True)
        if payload.get("visibility") not in {"private", "draft"}:
            raise GovernanceError(
                "Publication adapter accepts only private or draft visibility"
            )
        if not idempotency_key.strip():
            raise GovernanceError("Publication idempotency key is required")
        status, response, _ = self.transport(
            self.endpoint,
            method="POST",
            payload=payload,
            headers={
                "Authorization": f"Bearer {self.access_token}",
                "X-Amaura-Idempotency-Key": idempotency_key,
            },
        )
        if status not in {200, 201, 202}:
            raise GovernanceError(
                f"Private publication draft failed with HTTP {status}"
            )
        external_id = str(response.get("id", "")).strip()
        visibility = str(response.get("visibility", "")).strip().lower()
        if not external_id or visibility not in {"private", "draft"}:
            raise GovernanceError(
                "Provider did not confirm a private publication draft"
            )
        return ProviderReceipt.issue(
            provider=str(response.get("provider", "private-publication")),
            operation="create_private_draft",
            external_id=external_id,
            idempotency_key=idempotency_key,
            payload=payload,
            status=visibility,
            key=self.receipt_key,
        )


class ApprovedPublicationAdapter:
    """Publish one founder-approved immutable package through an official endpoint.

    The endpoint must echo the provider idempotency key and payload digest. This
    makes ambiguous public side effects fail closed instead of being replayed.
    """

    def __init__(
        self,
        *,
        endpoint: str | None = None,
        access_token: str | None = None,
        transport: Transport = request_json,
        receipt_key: str | None = None,
    ):
        self.endpoint = endpoint if endpoint is not None else os.environ.get(
            "AMAURA_PUBLIC_PUBLISH_ENDPOINT", ""
        )
        self.access_token = access_token if access_token is not None else os.environ.get(
            "AMAURA_PUBLIC_PUBLISH_ACCESS_TOKEN", ""
        )
        self.transport = transport
        self.receipt_key = receipt_key

    @property
    def configured(self) -> bool:
        return (
            os.environ.get("AMAURA_ENABLE_PUBLICATION", "0") == "1"
            and os.environ.get("AMAURA_ENABLE_PUBLIC_PUBLISH", "0") == "1"
            and bool(self.endpoint and self.access_token)
        )

    def publish(
        self,
        *,
        payload: dict[str, Any],
        idempotency_key: str,
    ) -> ProviderReceipt:
        if not self.configured:
            raise GovernanceError("Approved public publication is not configured")
        if payload.get("visibility") != "public":
            raise GovernanceError("Public publication adapter accepts only public visibility")
        if not idempotency_key.strip():
            raise GovernanceError("Publication idempotency key is required")
        validate_public_url(self.endpoint, resolve=True)
        payload_sha256 = hashlib.sha256(_canonical_bytes(payload)).hexdigest()
        status, response, _ = self.transport(
            self.endpoint,
            method="POST",
            payload=payload,
            headers={
                "Authorization": f"Bearer {self.access_token}",
                "X-Amaura-Idempotency-Key": idempotency_key,
                "X-Amaura-Payload-SHA256": payload_sha256,
            },
        )
        if status not in {200, 201, 202}:
            raise GovernanceError(f"Approved publication failed with HTTP {status}")
        external_id = str(response.get("id", "")).strip()
        visibility = str(response.get("visibility", "")).strip().lower()
        echoed_key = str(response.get("idempotency_key", "")).strip()
        echoed_hash = str(response.get("payload_sha256", "")).strip().lower()
        if not external_id or visibility not in {"public", "published"}:
            raise GovernanceError("Provider did not confirm a public publication")
        if not hmac.compare_digest(echoed_key, idempotency_key):
            raise GovernanceError("Provider did not confirm the publication idempotency key")
        if not hmac.compare_digest(echoed_hash, payload_sha256):
            raise GovernanceError("Provider did not confirm the publication payload digest")
        return ProviderReceipt.issue(
            provider=str(response.get("provider", "approved-publication")),
            operation="publish_content",
            external_id=external_id,
            idempotency_key=idempotency_key,
            payload=payload,
            status=visibility,
            key=self.receipt_key,
        )


def verify_provider_receipt(
    value: ProviderReceipt | dict[str, Any],
    *,
    expected_operation: str,
    expected_idempotency_key: str = "",
    expected_payload: Any | None = None,
    key: str | None = None,
) -> ProviderReceipt:
    receipt = value if isinstance(value, ProviderReceipt) else ProviderReceipt.from_dict(value)
    if not receipt.verify(key=key):
        raise GovernanceError("Provider receipt signature is invalid")
    if receipt.operation != expected_operation:
        raise GovernanceError("Provider receipt operation does not match")
    if expected_idempotency_key and not hmac.compare_digest(
        receipt.idempotency_key,
        expected_idempotency_key,
    ):
        raise GovernanceError("Provider receipt idempotency key does not match")
    if expected_payload is not None:
        expected_hash = hashlib.sha256(_canonical_bytes(expected_payload)).hexdigest()
        if not hmac.compare_digest(receipt.payload_sha256, expected_hash):
            raise GovernanceError("Provider receipt payload does not match")
    return receipt


class ProviderMatrix:
    """Dispatch durable outbox events to explicitly configured providers."""

    def __init__(self):
        from jarvis.amaura.channels import (
            AssistedOutreachAdapter, LinkedInPublicationAdapter, MetaPublicationAdapter, TelegramNotificationAdapter,
        )
        from jarvis.amaura.nexus_bridge import NexusDeliveryAdapter
        from jarvis.amaura.workspace_integrations import GoogleCalendarAdapter, GoogleDriveAdapter, GitHubAdapter, PostHogAdapter

        self.gmail = GmailAdapter()
        self.n8n = N8nEmailAdapter()
        self.crm = N8nCRMAdapter()
        self.imessage = IMessageAdapter()
        self.private_pub = PrivatePublicationAdapter()
        self.public_pub = ApprovedPublicationAdapter()
        self.assisted = AssistedOutreachAdapter()
        self.telegram = TelegramNotificationAdapter()
        self.linkedin = LinkedInPublicationAdapter()
        self.meta = MetaPublicationAdapter()
        self.calendar = GoogleCalendarAdapter()
        self.drive = GoogleDriveAdapter()
        self.github = GitHubAdapter()
        self.analytics = PostHogAdapter()
        self.nexus = NexusDeliveryAdapter()

    def dispatch(self, event: dict[str, Any]) -> ProviderReceipt:
        provider = event["provider"]
        operation = event["operation"]
        payload = event["payload"]
        idempotency_key = event["idempotency_key"]
        if operation == "send_email":
            if provider == "n8n" or (provider == "auto" and self.n8n.configured):
                return self.n8n.send(
                    recipient=payload["recipient"], subject=payload["subject"],
                    body=payload["body"], idempotency_key=idempotency_key,
                    sender=payload.get("sender", ""),
                )
            if provider == "gmail" or (provider == "auto" and self.gmail.configured):
                return self.gmail.send(
                    recipient=payload["recipient"], subject=payload["subject"],
                    body=payload["body"], idempotency_key=idempotency_key,
                    sender=payload.get("sender", ""),
                )
            raise GovernanceError(f"No configured provider for send_email (requested: {provider})")
        if operation == "send_imessage":
            if provider != "imessage":
                raise GovernanceError("iMessage delivery requires the imessage provider")
            return self.imessage.send(
                recipient=payload["recipient"], body=payload["body"],
                idempotency_key=idempotency_key,
            )
        if operation == "sync_crm":
            if provider != "n8n":
                raise GovernanceError("CRM synchronization requires the n8n provider")
            return self.crm.sync(
                lead_id=payload["lead_id"], data=payload["data"],
                idempotency_key=idempotency_key,
            )
        if operation == "create_private_draft":
            return self.private_pub.create_private_draft(payload=payload, idempotency_key=idempotency_key)
        if operation == "publish_content":
            if provider != "approved-publication":
                raise GovernanceError("Public publication requires the approved-publication provider")
            return self.public_pub.publish(payload=payload, idempotency_key=idempotency_key)
        if operation == "prepare_assisted_message":
            if provider != "assisted-browser":
                raise GovernanceError("Assisted messaging requires the assisted-browser provider")
            return self.assisted.prepare(channel=payload["channel"], recipient=payload["recipient"],
                                         subject=payload.get("subject", ""), body=payload["body"],
                                         idempotency_key=idempotency_key)
        if operation == "send_telegram_notification":
            if provider != "telegram":
                raise GovernanceError("Founder notification requires Telegram")
            return self.telegram.send(text=payload["text"], idempotency_key=idempotency_key)
        if operation == "create_calendar_event":
            return self.calendar.create_event(summary=payload["summary"], start=payload["start"], end=payload["end"],
                                              description=payload.get("description", ""), attendees=payload.get("attendees", []),
                                              calendar_id=payload.get("calendar_id", "primary"), idempotency_key=idempotency_key)
        if operation == "upload_drive_file":
            return self.drive.upload_file(path=payload["path"], folder_id=payload.get("folder_id", ""),
                                          name=payload.get("name", ""), mime_type=payload.get("mime_type", "application/octet-stream"),
                                          idempotency_key=idempotency_key)
        if operation == "create_github_issue":
            return self.github.create_issue(owner=payload["owner"], repo=payload["repo"], title=payload["title"],
                                            body=payload.get("body", ""), labels=payload.get("labels", []),
                                            idempotency_key=idempotency_key)
        if operation == "dispatch_github_workflow":
            return self.github.dispatch_workflow(owner=payload["owner"], repo=payload["repo"], workflow_id=payload["workflow_id"],
                                                 ref=payload["ref"], inputs=payload.get("inputs", {}), idempotency_key=idempotency_key)
        if operation == "publish_linkedin_text":
            return self.linkedin.publish_text(text=payload["text"], idempotency_key=idempotency_key)
        if operation == "publish_facebook_text":
            return self.meta.publish_facebook_text(text=payload["text"], idempotency_key=idempotency_key)
        if operation == "publish_instagram_media":
            return self.meta.publish_instagram_media(media_url=payload["media_url"], caption=payload.get("caption", ""),
                                                     media_type=payload.get("media_type", "IMAGE"), idempotency_key=idempotency_key)
        if operation == "capture_analytics_event":
            return self.analytics.capture(event=payload["event"], distinct_id=payload["distinct_id"],
                                          properties=payload.get("properties", {}), idempotency_key=idempotency_key)
        if operation == "run_nexus_delivery":
            return self.nexus.run(repository_path=payload["repository_path"], objective=payload["objective"],
                                  acceptance_criteria=payload.get("acceptance_criteria", []),
                                  timeout_seconds=payload.get("timeout_seconds", 1800), idempotency_key=idempotency_key)
        raise GovernanceError(f"Unknown operation in matrix: {operation}")


def dispatch_outbox_event(event: dict[str, Any]) -> ProviderReceipt:
    matrix = ProviderMatrix()
    return matrix.dispatch(event)


__all__ = [
    "ApprovedPublicationAdapter",
    "GmailAdapter",
    "PrivatePublicationAdapter",
    "N8nEmailAdapter",
    "N8nCRMAdapter",
    "IMessageAdapter",
    "ProviderReceipt",
    "verify_provider_receipt",
]
