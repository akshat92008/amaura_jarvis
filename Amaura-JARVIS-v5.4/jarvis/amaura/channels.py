"""Free-first communication and publication adapters.

Restricted social channels use an assisted handoff: Amaura prepares the exact
approved payload, stores an immutable local packet, and optionally opens the
conversation.  It never clicks Send or attempts to evade platform controls.
Official publishing adapters are available when the founder configures the
required free developer credentials and account permissions.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import webbrowser
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from urllib.parse import quote, urlencode, urlsplit

from jarvis.amaura.models import GovernanceError
from jarvis.amaura.network import decode_json_object, request_bytes, request_json


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")


def _safe_path_component(value: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip("-.")
    return clean[:80] or "handoff"


def _provider_receipt(**kwargs: Any):
    # Lazy import avoids a module cycle: ProviderMatrix imports these adapters.
    from jarvis.amaura.integrations import ProviderReceipt

    return ProviderReceipt.issue(**kwargs)


@dataclass(frozen=True, slots=True)
class AssistedHandoff:
    handoff_id: str
    channel: str
    recipient: str
    subject: str
    body: str
    launch_url: str
    payload_sha256: str
    created_at: str
    file_path: str
    requires_founder_send: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AssistedOutreachAdapter:
    """Prepare an immutable founder-reviewed browser handoff."""

    supported_channels = {"whatsapp", "linkedin", "instagram", "facebook", "email"}

    def __init__(self, *, handoff_dir: str | Path | None = None, receipt_key: str | None = None) -> None:
        configured = handoff_dir or os.environ.get("AMAURA_HANDOFF_DIR", "")
        default = Path(os.environ.get("AMAURA_DATA_DIR", ".amaura-data")) / "handoffs"
        self.handoff_dir = Path(configured).expanduser() if configured else default
        self.handoff_dir.mkdir(parents=True, exist_ok=True)
        self.receipt_key = receipt_key

    @property
    def configured(self) -> bool:
        return True

    @staticmethod
    def _launch_url(channel: str, recipient: str, subject: str, body: str) -> str:
        clean_recipient = recipient.strip()
        if channel == "whatsapp":
            digits = re.sub(r"\D", "", clean_recipient)
            if not 8 <= len(digits) <= 15:
                raise GovernanceError("WhatsApp recipient must be an international phone number")
            return f"https://wa.me/{digits}?{urlencode({'text': body})}"
        if channel == "email":
            if "@" not in clean_recipient:
                raise GovernanceError("Email handoff requires a valid recipient")
            return f"mailto:{quote(clean_recipient)}?{urlencode({'subject': subject, 'body': body})}"
        if channel in {"linkedin", "instagram", "facebook"}:
            if not clean_recipient.startswith(("http://", "https://")):
                raise GovernanceError(f"{channel.title()} handoff requires the public profile URL")
            parsed = urlsplit(clean_recipient)
            allowed = {
                "linkedin": ("linkedin.com",),
                "instagram": ("instagram.com",),
                "facebook": ("facebook.com", "fb.com"),
            }[channel]
            host = (parsed.hostname or "").lower()
            if not any(host == item or host.endswith("." + item) for item in allowed):
                raise GovernanceError(f"Recipient URL is not a {channel.title()} URL")
            return clean_recipient
        raise GovernanceError(f"Unsupported assisted channel: {channel}")

    def prepare(
        self,
        *,
        channel: str,
        recipient: str,
        subject: str,
        body: str,
        idempotency_key: str,
        open_browser: bool | None = None,
    ):
        normalized = channel.strip().lower()
        if normalized not in self.supported_channels:
            raise GovernanceError(f"Unsupported assisted channel: {normalized}")
        if not body.strip() or not idempotency_key.strip():
            raise GovernanceError("Assisted outreach requires body and idempotency key")
        launch_url = self._launch_url(normalized, recipient, subject, body)
        payload = {
            "channel": normalized,
            "recipient": recipient.strip(),
            "subject": subject,
            "body": body,
            "idempotency_key": idempotency_key,
        }
        payload_hash = hashlib.sha256(_canonical_bytes(payload)).hexdigest()
        handoff_id = "handoff-" + hashlib.sha256(idempotency_key.encode()).hexdigest()[:24]
        packet = {
            "schema": "amaura.assisted-handoff.v1",
            "handoff_id": handoff_id,
            "created_at": datetime.now(UTC).isoformat(),
            "requires_founder_send": True,
            "launch_url": launch_url,
            "payload_sha256": payload_hash,
            "payload": payload,
            "instructions": [
                "Review the exact recipient and message.",
                "Open the launch URL from this packet.",
                "Paste the approved text when the platform cannot prefill it.",
                "Press Send manually.",
                "Record the platform message/thread identifier back in Amaura.",
            ],
        }
        target = self.handoff_dir / f"{_safe_path_component(handoff_id)}.json"
        if target.exists():
            existing = json.loads(target.read_text(encoding="utf-8"))
            if existing.get("payload_sha256") != payload_hash:
                raise GovernanceError("Assisted handoff idempotency collision")
        else:
            fd, temporary_name = tempfile.mkstemp(prefix=".handoff-", suffix=".tmp", dir=self.handoff_dir)
            os.close(fd)
            temporary = Path(temporary_name)
            try:
                temporary.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")
                if os.name == "posix":
                    temporary.chmod(0o600)
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
        should_open = (
            os.environ.get("AMAURA_BROWSER_HANDOFF_OPEN", "0") == "1" if open_browser is None else bool(open_browser)
        )
        if should_open and not webbrowser.open(launch_url, new=2, autoraise=True):
            raise GovernanceError("Browser handoff could not be opened")
        return _provider_receipt(
            provider="assisted-browser",
            operation="prepare_assisted_message",
            external_id=handoff_id,
            thread_id=str(target.resolve()),
            idempotency_key=idempotency_key,
            payload={
                "recipient": recipient.strip(),
                "subject": subject,
                "body": body,
                "channel": normalized,
            },
            status="prepared",
            key=self.receipt_key,
        )


class TelegramNotificationAdapter:
    endpoint_template = "https://api.telegram.org/bot{token}/sendMessage"

    def __init__(
        self,
        *,
        token: str | None = None,
        chat_id: str | None = None,
        transport=request_json,
        receipt_key: str | None = None,
    ) -> None:
        self.token = (token if token is not None else os.environ.get("TELEGRAM_BOT_TOKEN", "")).strip()
        self.chat_id = (chat_id if chat_id is not None else os.environ.get("TELEGRAM_USER_ID", "")).strip()
        self.transport = transport
        self.receipt_key = receipt_key

    @property
    def configured(self) -> bool:
        return bool(self.token and self.chat_id)

    def send(self, *, text: str, idempotency_key: str) -> Any:
        if not self.configured:
            raise GovernanceError("Telegram founder notifications are not configured")
        clean = text.strip()
        if not clean or len(clean) > 4096:
            raise GovernanceError("Telegram message must contain 1-4096 characters")
        status, response, _ = self.transport(
            self.endpoint_template.format(token=self.token),
            method="POST",
            payload={"chat_id": self.chat_id, "text": clean, "disable_web_page_preview": True},
            headers={"X-Amaura-Idempotency-Key": idempotency_key},
            timeout=20,
        )
        if status != 200 or response.get("ok") is not True:
            raise GovernanceError(f"Telegram notification failed with HTTP {status}")
        result = cast(dict[str, Any], response.get("result")) if isinstance(response.get("result"), dict) else {}
        message_id = str(result.get("message_id", "")).strip()
        chat = cast(dict[str, Any], result.get("chat")) if isinstance(result.get("chat"), dict) else {}
        if not message_id or str(chat.get("id", "")) != str(self.chat_id):
            raise GovernanceError("Telegram did not confirm the configured founder chat")
        return _provider_receipt(
            provider="telegram",
            operation="send_telegram_notification",
            external_id=message_id,
            thread_id=str(self.chat_id),
            idempotency_key=idempotency_key,
            payload={"chat_id": self.chat_id, "text": clean},
            status="sent",
            key=self.receipt_key,
        )


class LinkedInPublicationAdapter:
    endpoint = "https://api.linkedin.com/rest/posts"

    def __init__(
        self,
        *,
        access_token: str | None = None,
        author_urn: str | None = None,
        api_version: str | None = None,
        transport=request_bytes,
        receipt_key: str | None = None,
    ) -> None:
        self.access_token = (
            access_token if access_token is not None else os.environ.get("AMAURA_LINKEDIN_ACCESS_TOKEN", "")
        ).strip()
        self.author_urn = (
            author_urn if author_urn is not None else os.environ.get("AMAURA_LINKEDIN_AUTHOR_URN", "")
        ).strip()
        self.api_version = (
            api_version if api_version is not None else os.environ.get("AMAURA_LINKEDIN_VERSION", "")
        ).strip()
        self.transport = transport
        self.receipt_key = receipt_key

    @property
    def configured(self) -> bool:
        return bool(self.access_token and self.author_urn and re.fullmatch(r"20\d{4}", self.api_version))

    def publish_text(self, *, text: str, idempotency_key: str) -> Any:
        if not self.configured:
            raise GovernanceError("LinkedIn publishing credentials, author URN, or API version are missing")
        clean = text.strip()
        if not clean or len(clean) > 3000:
            raise GovernanceError("LinkedIn text post must contain 1-3000 characters")
        payload = {
            "author": self.author_urn,
            "commentary": clean,
            "visibility": "PUBLIC",
            "distribution": {
                "feedDistribution": "MAIN_FEED",
                "targetEntities": [],
                "thirdPartyDistributionChannels": [],
            },
            "lifecycleState": "PUBLISHED",
            "isReshareDisabledByAuthor": False,
        }
        status, raw, headers = self.transport(
            self.endpoint,
            method="POST",
            body=_canonical_bytes(payload),
            headers={
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json",
                "Linkedin-Version": self.api_version,
                "X-Restli-Protocol-Version": "2.0.0",
                "X-Amaura-Idempotency-Key": idempotency_key,
            },
            timeout=30,
        )
        if status != 201:
            response = decode_json_object(raw, allow_empty=True)
            raise GovernanceError(f"LinkedIn publication failed with HTTP {status}: {response.get('message', '')}")
        external_id = str(headers.get("x-restli-id", "")).strip()
        if not external_id:
            response = decode_json_object(raw, allow_empty=True)
            external_id = str(response.get("id", "")).strip()
        if not external_id:
            raise GovernanceError("LinkedIn did not return the post identifier")
        return _provider_receipt(
            provider="linkedin",
            operation="publish_linkedin_text",
            external_id=external_id,
            idempotency_key=idempotency_key,
            payload=payload,
            status="published",
            key=self.receipt_key,
        )


class MetaPublicationAdapter:
    """Publish Facebook page text and Instagram media through Graph API."""

    def __init__(
        self,
        *,
        access_token: str | None = None,
        graph_version: str | None = None,
        page_id: str | None = None,
        instagram_account_id: str | None = None,
        transport=request_json,
        receipt_key: str | None = None,
    ) -> None:
        self.access_token = (
            access_token if access_token is not None else os.environ.get("AMAURA_META_ACCESS_TOKEN", "")
        ).strip()
        self.graph_version = (
            (graph_version if graph_version is not None else os.environ.get("AMAURA_META_GRAPH_VERSION", ""))
            .strip()
            .lstrip("v")
        )
        self.page_id = (page_id if page_id is not None else os.environ.get("AMAURA_FACEBOOK_PAGE_ID", "")).strip()
        self.instagram_account_id = (
            instagram_account_id
            if instagram_account_id is not None
            else os.environ.get("AMAURA_INSTAGRAM_ACCOUNT_ID", "")
        ).strip()
        self.transport = transport
        self.receipt_key = receipt_key

    @property
    def base_url(self) -> str:
        if not re.fullmatch(r"\d{1,2}\.\d", self.graph_version):
            raise GovernanceError("AMAURA_META_GRAPH_VERSION must be explicitly configured, for example 23.0")
        return f"https://graph.facebook.com/v{self.graph_version}"

    @property
    def facebook_configured(self) -> bool:
        return bool(self.access_token and self.page_id and self.graph_version)

    @property
    def instagram_configured(self) -> bool:
        return bool(self.access_token and self.instagram_account_id and self.graph_version)

    def publish_facebook_text(self, *, text: str, idempotency_key: str) -> Any:
        if not self.facebook_configured:
            raise GovernanceError("Facebook Page publishing is not configured")
        clean = text.strip()
        if not clean:
            raise GovernanceError("Facebook publication text is required")
        payload = {"message": clean, "access_token": self.access_token}
        status, response, _ = self.transport(
            f"{self.base_url}/{quote(self.page_id)}/feed",
            method="POST",
            payload=payload,
            headers={"X-Amaura-Idempotency-Key": idempotency_key},
            timeout=30,
        )
        if status not in {200, 201}:
            raise GovernanceError(f"Facebook publication failed with HTTP {status}")
        external_id = str(response.get("id", "")).strip()
        if not external_id:
            raise GovernanceError("Facebook did not return a post identifier")
        receipt_payload = {"page_id": self.page_id, "message": clean}
        return _provider_receipt(
            provider="facebook",
            operation="publish_facebook_text",
            external_id=external_id,
            idempotency_key=idempotency_key,
            payload=receipt_payload,
            status="published",
            key=self.receipt_key,
        )

    def publish_instagram_media(
        self,
        *,
        media_url: str,
        caption: str,
        idempotency_key: str,
        media_type: str = "IMAGE",
    ) -> Any:
        if not self.instagram_configured:
            raise GovernanceError("Instagram publishing is not configured")
        parsed = urlsplit(media_url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise GovernanceError("Instagram media URL must be a public HTTPS URL")
        normalized_type = media_type.strip().upper()
        if normalized_type not in {"IMAGE", "REELS"}:
            raise GovernanceError("Instagram media type must be IMAGE or REELS")
        create_payload: dict[str, Any] = {
            "caption": caption.strip(),
            "access_token": self.access_token,
        }
        if normalized_type == "IMAGE":
            create_payload["image_url"] = media_url
        else:
            create_payload.update({"media_type": "REELS", "video_url": media_url})
        status, response, _ = self.transport(
            f"{self.base_url}/{quote(self.instagram_account_id)}/media",
            method="POST",
            payload=create_payload,
            headers={"X-Amaura-Idempotency-Key": idempotency_key + ":container"},
            timeout=45,
        )
        if status not in {200, 201}:
            raise GovernanceError(f"Instagram container creation failed with HTTP {status}")
        creation_id = str(response.get("id", "")).strip()
        if not creation_id:
            raise GovernanceError("Instagram did not return a creation identifier")
        status, response, _ = self.transport(
            f"{self.base_url}/{quote(self.instagram_account_id)}/media_publish",
            method="POST",
            payload={"creation_id": creation_id, "access_token": self.access_token},
            headers={"X-Amaura-Idempotency-Key": idempotency_key + ":publish"},
            timeout=45,
        )
        if status not in {200, 201}:
            raise GovernanceError(f"Instagram media publication failed with HTTP {status}")
        external_id = str(response.get("id", "")).strip()
        if not external_id:
            raise GovernanceError("Instagram did not return a media identifier")
        receipt_payload = {
            "instagram_account_id": self.instagram_account_id,
            "media_url": media_url,
            "caption": caption.strip(),
            "media_type": normalized_type,
        }
        return _provider_receipt(
            provider="instagram",
            operation="publish_instagram_media",
            external_id=external_id,
            thread_id=creation_id,
            idempotency_key=idempotency_key,
            payload=receipt_payload,
            status="published",
            key=self.receipt_key,
        )


__all__ = [
    "AssistedHandoff",
    "AssistedOutreachAdapter",
    "LinkedInPublicationAdapter",
    "MetaPublicationAdapter",
    "TelegramNotificationAdapter",
]
