"""Single structured result contract for every tool surface."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ToolResult:
    ok: bool
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    code: str = "OK"
    external_id: str = ""
    retryable: bool = False
    evidence_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["evidence_ids"] = list(self.evidence_ids)
        return payload

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, default=str)

    @classmethod
    def success(cls, output: Any = None, **data: Any) -> ToolResult:
        if output is not None:
            data = {"output": output, **data}
        return cls(ok=True, data=data)

    @classmethod
    def failure(
        cls,
        error: str,
        *,
        code: str = "TOOL_ERROR",
        retryable: bool = False,
        data: dict[str, Any] | None = None,
    ) -> ToolResult:
        return cls(ok=False, data=data or {}, error=str(error), code=code, retryable=retryable)


def parse_tool_result(value: Any) -> ToolResult:
    """Normalize legacy strings/dicts/JSON into the authoritative result type."""
    if isinstance(value, ToolResult):
        return value
    payload: Any = value
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("{"):
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError:
                payload = value
        else:
            if stripped.startswith("❌"):
                return ToolResult.failure(stripped, code="LEGACY_TOOL_ERROR")
            return ToolResult.success(value)
    if isinstance(payload, dict):
        if "ok" in payload:
            evidence = payload.get("evidence_ids") or ()
            raw_data = payload.get("data")
            data_dict: dict[str, Any] = (
                dict(raw_data)
                if isinstance(raw_data, dict)
                else {
                    k: v
                    for k, v in payload.items()
                    if k not in {"ok", "error", "code", "external_id", "retryable", "evidence_ids"}
                }
            )
            return ToolResult(
                ok=bool(payload.get("ok")),
                data=data_dict,
                error=None if payload.get("error") in {None, ""} else str(payload.get("error")),
                code=str(payload.get("code") or ("OK" if payload.get("ok") else "TOOL_ERROR")),
                external_id=str(payload.get("external_id") or ""),
                retryable=bool(payload.get("retryable", False)),
                evidence_ids=tuple(str(item) for item in evidence),
            )
        return ToolResult.success(payload)
    return ToolResult.success(str(payload))


def tool_succeeded(value: Any) -> bool:
    return parse_tool_result(value).ok


__all__ = ["ToolResult", "parse_tool_result", "tool_succeeded"]
