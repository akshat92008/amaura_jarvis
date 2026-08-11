"""Small OAuth helpers for long-running free-tier integrations."""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from jarvis.amaura.models import GovernanceError
from jarvis.amaura.network import request_form_json


@dataclass(frozen=True, slots=True)
class OAuthSnapshot:
    configured: bool
    has_access_token: bool
    has_refresh_token: bool
    expires_at: str


class OAuthTokenProvider:
    """Resolve renewable OAuth access tokens without logging credentials.

    The provider accepts an environment prefix such as ``AMAURA_GOOGLE`` and
    reads ``<PREFIX>_ACCESS_TOKEN``, ``_CLIENT_ID``, ``_CLIENT_SECRET`` and
    ``_REFRESH_TOKEN``.  Tokens are cached in memory only.
    """

    def __init__(
        self,
        prefix: str,
        *,
        token_endpoint: str = "https://oauth2.googleapis.com/token",
        token_transport=request_form_json,
        access_token: str | None = None,
    ) -> None:
        normalized = str(prefix).strip().upper().rstrip("_")
        if not normalized:
            raise ValueError("OAuth environment prefix is required")
        self.prefix = normalized
        self.token_endpoint = token_endpoint
        self.token_transport = token_transport
        self._access_token = (
            access_token
            if access_token is not None
            else os.environ.get(f"{normalized}_ACCESS_TOKEN", "")
        ).strip()
        self._client_id = os.environ.get(f"{normalized}_CLIENT_ID", "").strip()
        self._client_secret = os.environ.get(f"{normalized}_CLIENT_SECRET", "").strip()
        self._refresh_token = os.environ.get(f"{normalized}_REFRESH_TOKEN", "").strip()
        self._expires_at: datetime | None = None
        self._lock = threading.RLock()

    @property
    def has_refresh_credentials(self) -> bool:
        return bool(self._client_id and self._client_secret and self._refresh_token)

    @property
    def configured(self) -> bool:
        return bool(self._access_token or self.has_refresh_credentials)

    def snapshot(self) -> OAuthSnapshot:
        return OAuthSnapshot(
            configured=self.configured,
            has_access_token=bool(self._access_token),
            has_refresh_token=self.has_refresh_credentials,
            expires_at=self._expires_at.isoformat() if self._expires_at else "",
        )

    def token(self, *, force_refresh: bool = False) -> str:
        with self._lock:
            if (
                self._access_token
                and not force_refresh
                and (
                    self._expires_at is None
                    or self._expires_at > datetime.now(UTC) + timedelta(seconds=60)
                )
            ):
                return self._access_token
            if not self.has_refresh_credentials:
                if self._access_token and not force_refresh:
                    return self._access_token
                raise GovernanceError(f"{self.prefix} OAuth credentials are not configured")
            status, response, _ = self.token_transport(
                self.token_endpoint,
                payload={
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "refresh_token": self._refresh_token,
                    "grant_type": "refresh_token",
                },
                timeout=20,
            )
            if status != 200:
                raise GovernanceError(
                    f"{self.prefix} OAuth refresh failed with HTTP {status}"
                )
            token = str(response.get("access_token", "")).strip()
            if not token:
                raise GovernanceError(
                    f"{self.prefix} OAuth refresh returned no access token"
                )
            expires_in = response.get("expires_in", 3600)
            try:
                lifetime = max(60, min(int(expires_in), 86_400))
            except (TypeError, ValueError):
                lifetime = 3600
            self._access_token = token
            self._expires_at = datetime.now(UTC) + timedelta(seconds=lifetime)
            return token

    def authorized_headers(self, *, force_refresh: bool = False) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token(force_refresh=force_refresh)}"}

    def request_with_refresh(
        self,
        request: Any,
        *,
        retry_statuses: tuple[int, ...] = (401,),
    ) -> Any:
        """Run a callable once, refreshing only after a definite auth rejection."""
        result = request(self.token())
        status = result[0] if isinstance(result, tuple) and result else None
        if status in retry_statuses and self.has_refresh_credentials:
            result = request(self.token(force_refresh=True))
        return result


__all__ = ["OAuthSnapshot", "OAuthTokenProvider"]
