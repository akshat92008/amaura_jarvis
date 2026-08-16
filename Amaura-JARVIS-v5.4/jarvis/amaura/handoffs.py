"""Founder-controlled packets for premium or external execution surfaces."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jarvis.amaura.models import GovernanceError

_SAFE_ID = re.compile(r"[^A-Za-z0-9_.-]+")


@dataclass(frozen=True, slots=True)
class HandoffPacket:
    handoff_id: str
    provider: str
    objective: str
    created_at: str
    payload_sha256: str
    json_path: str
    markdown_path: str
    requires_founder_action: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _safe_fragment(value: str) -> str:
    cleaned = _SAFE_ID.sub("-", value.strip()).strip("-.")
    return cleaned[:80] or "handoff"


def _handoff_root() -> Path:
    configured = os.environ.get("AMAURA_HANDOFF_DIR", "")
    if configured:
        root = Path(configured).expanduser().resolve()
    else:
        data_dir = Path(os.environ.get("AMAURA_DATA_DIR", ".amaura-data")).expanduser().resolve()
        root = data_dir / "handoffs"
    root.mkdir(parents=True, exist_ok=True)
    return root


def create_handoff(
    *,
    provider: str,
    objective: str,
    instructions: list[str],
    context: dict[str, Any],
    acceptance_criteria: list[str],
    prohibited_actions: list[str] | None = None,
) -> HandoffPacket:
    """Create an immutable packet; never logs credentials or drives a consumer UI."""
    if not objective.strip() or not instructions or not acceptance_criteria:
        raise GovernanceError("A handoff requires an objective, instructions and acceptance criteria")
    prohibited_actions = prohibited_actions or [
        "Do not expose credentials or private data.",
        "Do not publish, deploy, merge or spend money without founder approval.",
        "Do not operate outside the explicitly assigned workspace.",
    ]
    created_at = datetime.now(UTC).isoformat()
    stable_payload = {
        "provider": provider,
        "objective": objective,
        "instructions": instructions,
        "context": context,
        "acceptance_criteria": acceptance_criteria,
        "prohibited_actions": prohibited_actions,
        "requires_founder_action": True,
    }
    encoded = json.dumps(stable_payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    digest = hashlib.sha256(encoded).hexdigest()
    canonical = {**stable_payload, "created_at": created_at}
    handoff_id = f"{_safe_fragment(provider)}-{digest[:12]}"
    provider_dir = _handoff_root() / _safe_fragment(provider)
    provider_dir.mkdir(parents=True, exist_ok=True)
    json_path = provider_dir / f"{handoff_id}.json"
    markdown_path = provider_dir / f"{handoff_id}.md"
    if json_path.exists():
        existing = json.loads(json_path.read_text(encoding="utf-8"))
        created_at = str(existing.get("created_at", created_at))
        canonical["created_at"] = created_at
    else:
        json_path.write_text(
            json.dumps({**canonical, "payload_sha256": digest}, indent=2, default=str) + "\n", encoding="utf-8"
        )
    if not markdown_path.exists():
        lines = [
            f"# {provider} handoff: {objective}",
            "",
            f"- Handoff ID: `{handoff_id}`",
            f"- Created: `{created_at}`",
            f"- Payload SHA-256: `{digest}`",
            "- Execution: founder-controlled external surface",
            "",
            "## Instructions",
        ]
        lines.extend(f"{index}. {instruction}" for index, instruction in enumerate(instructions, 1))
        lines.extend(["", "## Acceptance criteria"])
        lines.extend(f"- [ ] {criterion}" for criterion in acceptance_criteria)
        lines.extend(["", "## Prohibited actions"])
        lines.extend(f"- {item}" for item in prohibited_actions)
        lines.extend(["", "## Context", "", "```json", json.dumps(context, indent=2, default=str), "```", ""])
        markdown_path.write_text("\n".join(lines), encoding="utf-8")
    return HandoffPacket(
        handoff_id=handoff_id,
        provider=provider,
        objective=objective,
        created_at=created_at,
        payload_sha256=digest,
        json_path=str(json_path),
        markdown_path=str(markdown_path),
    )


def create_antigravity_packet(
    *,
    objective: str,
    repository: str,
    plan: list[str],
    acceptance_criteria: list[str],
    allowed_paths: list[str] | None = None,
) -> HandoffPacket:
    repository_path = Path(repository).expanduser().resolve()
    if not repository_path.exists() or not repository_path.is_dir():
        raise GovernanceError("Antigravity handoff repository must be an existing directory")
    return create_handoff(
        provider="antigravity",
        objective=objective,
        instructions=plan,
        context={
            "repository": str(repository_path),
            "allowed_paths": allowed_paths or ["."],
            "delivery_requirements": ["diff", "test evidence", "risk summary", "rollback instructions"],
        },
        acceptance_criteria=acceptance_criteria,
    )


def create_flow_packet(
    *,
    objective: str,
    scenes: list[dict[str, Any]],
    acceptance_criteria: list[str],
    aspect_ratio: str = "16:9",
) -> HandoffPacket:
    if not scenes:
        raise GovernanceError("Flow handoff requires at least one scene")
    normalised_scenes = []
    for index, scene in enumerate(scenes, 1):
        prompt = str(scene.get("prompt", "")).strip()
        if not prompt:
            raise GovernanceError(f"Flow scene {index} has no prompt")
        normalised_scenes.append(
            {
                "scene": index,
                "prompt": prompt,
                "duration_seconds": max(1, min(int(scene.get("duration_seconds", 8)), 30)),
                "camera": str(scene.get("camera", "")),
                "continuity": str(scene.get("continuity", "")),
                "negative_prompt": str(scene.get("negative_prompt", "")),
            }
        )
    return create_handoff(
        provider="google-flow",
        objective=objective,
        instructions=[
            "Generate each approved scene using the supplied prompt and continuity constraints.",
            "Export source clips without adding unapproved factual claims or text overlays.",
            "Return clips to the governed Amaura media workspace for FFmpeg assembly and QA.",
        ],
        context={"aspect_ratio": aspect_ratio, "scenes": normalised_scenes},
        acceptance_criteria=acceptance_criteria,
        prohibited_actions=[
            "Do not depict a real person without permission.",
            "Do not use copyrighted characters, logos or unlicensed source media.",
            "Do not publish generated clips directly.",
        ],
    )


__all__ = ["HandoffPacket", "create_antigravity_packet", "create_flow_packet", "create_handoff"]
