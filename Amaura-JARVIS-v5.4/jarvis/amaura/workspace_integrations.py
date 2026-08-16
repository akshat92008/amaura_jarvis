"""Governed free-tier workspace integrations for Calendar, Drive, GitHub and analytics."""

from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import quote

from jarvis.amaura.models import GovernanceError
from jarvis.amaura.network import decode_json_object, request_bytes, request_json
from jarvis.amaura.oauth import OAuthTokenProvider


def _receipt(**kwargs: Any):
    from jarvis.amaura.integrations import ProviderReceipt

    return ProviderReceipt.issue(**kwargs)


class GoogleCalendarAdapter:
    endpoint = "https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events"

    def __init__(
        self,
        *,
        token_provider: OAuthTokenProvider | None = None,
        transport=request_json,
        receipt_key: str | None = None,
    ) -> None:
        self.tokens = token_provider or OAuthTokenProvider("AMAURA_GOOGLE")
        self.transport = transport
        self.receipt_key = receipt_key

    @property
    def configured(self) -> bool:
        return self.tokens.configured

    def create_event(
        self,
        *,
        summary: str,
        start: dict[str, str],
        end: dict[str, str],
        idempotency_key: str,
        description: str = "",
        attendees: list[str] | None = None,
        calendar_id: str = "primary",
    ) -> Any:
        if not self.configured:
            raise GovernanceError("Google Calendar OAuth is not configured")
        if not summary.strip() or not isinstance(start, dict) or not isinstance(end, dict):
            raise GovernanceError("Calendar event requires summary, start, and end")
        payload: dict[str, Any] = {
            "summary": summary.strip(),
            "description": description.strip(),
            "start": start,
            "end": end,
        }
        clean_attendees = [value.strip() for value in (attendees or []) if "@" in value]
        if clean_attendees:
            payload["attendees"] = [{"email": value} for value in clean_attendees]
        endpoint = self.endpoint.format(calendar_id=quote(calendar_id.strip() or "primary", safe=""))

        def attempt(token: str):
            return self.transport(
                endpoint,
                method="POST",
                payload=payload,
                headers={"Authorization": f"Bearer {token}", "X-Amaura-Idempotency-Key": idempotency_key},
                timeout=30,
            )

        status, response, _ = self.tokens.request_with_refresh(attempt)
        if status not in {200, 201}:
            raise GovernanceError(f"Google Calendar event creation failed with HTTP {status}")
        external_id = str(response.get("id", "")).strip()
        if not external_id:
            raise GovernanceError("Google Calendar returned no event identifier")
        return _receipt(
            provider="google-calendar",
            operation="create_calendar_event",
            external_id=external_id,
            thread_id=str(response.get("htmlLink", "")),
            idempotency_key=idempotency_key,
            payload={**payload, "calendar_id": calendar_id.strip() or "primary"},
            status="created",
            key=self.receipt_key,
        )


class GoogleDriveAdapter:
    endpoint = (
        "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&fields=id,webViewLink,name,mimeType"
    )

    def __init__(
        self,
        *,
        token_provider: OAuthTokenProvider | None = None,
        transport=request_bytes,
        receipt_key: str | None = None,
    ) -> None:
        self.tokens = token_provider or OAuthTokenProvider("AMAURA_GOOGLE")
        self.transport = transport
        self.receipt_key = receipt_key

    @property
    def configured(self) -> bool:
        return self.tokens.configured

    def upload_file(
        self,
        *,
        path: str,
        idempotency_key: str,
        folder_id: str = "",
        name: str = "",
        mime_type: str = "application/octet-stream",
    ) -> Any:
        if not self.configured:
            raise GovernanceError("Google Drive OAuth is not configured")
        source = Path(path).expanduser().resolve()
        if not source.is_file():
            raise GovernanceError("Drive upload source does not exist")
        max_bytes = int(os.environ.get("AMAURA_DRIVE_MAX_UPLOAD_BYTES", "10485760"))
        if source.stat().st_size > max(1, min(max_bytes, 100_000_000)):
            raise GovernanceError("Drive upload exceeds configured size limit")
        metadata: dict[str, Any] = {"name": name.strip() or source.name}
        if folder_id.strip():
            metadata["parents"] = [folder_id.strip()]
        boundary = "amaura-" + uuid.uuid4().hex
        raw = source.read_bytes()
        body = (
            f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n".encode()
            + json.dumps(metadata, sort_keys=True).encode()
            + f"\r\n--{boundary}\r\nContent-Type: {mime_type}\r\n\r\n".encode()
            + raw
            + f"\r\n--{boundary}--\r\n".encode()
        )

        def attempt(token: str):
            return self.transport(
                self.endpoint,
                method="POST",
                body=body,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": f"multipart/related; boundary={boundary}",
                    "X-Amaura-Idempotency-Key": idempotency_key,
                },
                timeout=60,
                max_response_bytes=2_000_000,
            )

        status, response_raw, _ = self.tokens.request_with_refresh(attempt)
        response = decode_json_object(response_raw, allow_empty=True)
        if status not in {200, 201}:
            raise GovernanceError(f"Google Drive upload failed with HTTP {status}")
        external_id = str(response.get("id", "")).strip()
        if not external_id:
            raise GovernanceError("Google Drive returned no file identifier")
        receipt_payload = {
            "name": metadata["name"],
            "folder_id": folder_id.strip(),
            "mime_type": mime_type,
            "source_sha256": __import__("hashlib").sha256(raw).hexdigest(),
        }
        return _receipt(
            provider="google-drive",
            operation="upload_drive_file",
            external_id=external_id,
            thread_id=str(response.get("webViewLink", "")),
            idempotency_key=idempotency_key,
            payload=receipt_payload,
            status="uploaded",
            key=self.receipt_key,
        )


class GitHubAdapter:
    def __init__(self, *, token: str | None = None, transport=request_json, receipt_key: str | None = None) -> None:
        self.token = (token if token is not None else os.environ.get("AMAURA_GITHUB_TOKEN", "")).strip()
        self.transport = transport
        self.receipt_key = receipt_key

    @property
    def configured(self) -> bool:
        return bool(self.token)

    @staticmethod
    def _repo(owner: str, repo: str) -> tuple[str, str]:
        valid = re.compile(r"^[A-Za-z0-9_.-]+$")
        if not valid.fullmatch(owner.strip()) or not valid.fullmatch(repo.strip()):
            raise GovernanceError("Invalid GitHub owner or repository")
        return owner.strip(), repo.strip()

    def _headers(self, idempotency_key: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "X-Amaura-Idempotency-Key": idempotency_key,
        }

    def create_issue(
        self, *, owner: str, repo: str, title: str, body: str, idempotency_key: str, labels: list[str] | None = None
    ) -> Any:
        if not self.configured:
            raise GovernanceError("GitHub token is not configured")
        owner, repo = self._repo(owner, repo)
        payload = {"title": title.strip(), "body": body}
        if labels:
            payload["labels"] = [str(v).strip() for v in labels if str(v).strip()]
        if not payload["title"]:
            raise GovernanceError("GitHub issue title is required")
        status, response, _ = self.transport(
            f"https://api.github.com/repos/{owner}/{repo}/issues",
            method="POST",
            payload=payload,
            headers=self._headers(idempotency_key),
            timeout=30,
        )
        if status != 201:
            raise GovernanceError(f"GitHub issue creation failed with HTTP {status}")
        external_id = str(response.get("id", "")).strip()
        if not external_id:
            raise GovernanceError("GitHub returned no issue identifier")
        return _receipt(
            provider="github",
            operation="create_github_issue",
            external_id=external_id,
            thread_id=str(response.get("html_url", "")),
            idempotency_key=idempotency_key,
            payload={"owner": owner, "repo": repo, **payload},
            status="created",
            key=self.receipt_key,
        )

    def dispatch_workflow(
        self,
        *,
        owner: str,
        repo: str,
        workflow_id: str,
        ref: str,
        idempotency_key: str,
        inputs: dict[str, str] | None = None,
    ) -> Any:
        if not self.configured:
            raise GovernanceError("GitHub token is not configured")
        owner, repo = self._repo(owner, repo)
        workflow = quote(workflow_id.strip(), safe="")
        if not workflow or not ref.strip():
            raise GovernanceError("GitHub workflow and ref are required")
        payload = {"ref": ref.strip(), "inputs": {str(k): str(v) for k, v in (inputs or {}).items()}}
        status, response, headers = self.transport(
            f"https://api.github.com/repos/{owner}/{repo}/actions/workflows/{workflow}/dispatches",
            method="POST",
            payload=payload,
            headers=self._headers(idempotency_key),
            timeout=30,
        )
        if status != 204:
            raise GovernanceError(f"GitHub workflow dispatch failed with HTTP {status}")
        external_id = str(headers.get("x-github-request-id", "")).strip() or "dispatch-" + idempotency_key[-16:]
        return _receipt(
            provider="github",
            operation="dispatch_github_workflow",
            external_id=external_id,
            idempotency_key=idempotency_key,
            payload={"owner": owner, "repo": repo, "workflow_id": workflow_id.strip(), **payload},
            status="accepted",
            key=self.receipt_key,
        )


class PostHogAdapter:
    def __init__(
        self,
        *,
        host: str | None = None,
        project_key: str | None = None,
        transport=request_json,
        receipt_key: str | None = None,
    ) -> None:
        self.host = (
            host if host is not None else os.environ.get("AMAURA_POSTHOG_HOST", "https://us.i.posthog.com")
        ).rstrip("/")
        self.project_key = (
            project_key if project_key is not None else os.environ.get("AMAURA_POSTHOG_PROJECT_KEY", "")
        ).strip()
        self.transport = transport
        self.receipt_key = receipt_key

    @property
    def configured(self) -> bool:
        return bool(self.project_key)

    def capture(self, *, event: str, distinct_id: str, properties: dict[str, Any], idempotency_key: str) -> Any:
        if not self.configured:
            raise GovernanceError("PostHog project key is not configured")
        payload = {
            "api_key": self.project_key,
            "event": event.strip(),
            "properties": {"distinct_id": distinct_id.strip(), **properties},
        }
        if not payload["event"] or not distinct_id.strip():
            raise GovernanceError("Analytics event and distinct id are required")
        status, response, _ = self.transport(
            f"{self.host}/capture/",
            method="POST",
            payload=payload,
            headers={"X-Amaura-Idempotency-Key": idempotency_key},
            timeout=20,
        )
        if status not in {200, 201}:
            raise GovernanceError(f"PostHog capture failed with HTTP {status}")
        return _receipt(
            provider="posthog",
            operation="capture_analytics_event",
            external_id=str(response.get("uuid", "")).strip() or "event-" + idempotency_key[-16:],
            idempotency_key=idempotency_key,
            payload={"event": payload["event"], "distinct_id": distinct_id.strip(), "properties": properties},
            status="accepted",
            key=self.receipt_key,
        )


__all__ = ["GoogleCalendarAdapter", "GoogleDriveAdapter", "GitHubAdapter", "PostHogAdapter"]
