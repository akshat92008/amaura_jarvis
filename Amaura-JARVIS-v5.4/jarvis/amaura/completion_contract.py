"""Evidence-to-deliverable completion contracts for governed Amaura workers.

A tool result is evidence, not a completed acceptance criterion.  This module
builds a bounded synthesis packet and validates the worker's criterion-specific
deliverable before independent review.
"""

from __future__ import annotations

import json
import re
from typing import Any, Protocol


class CompletionContractError(ValueError):
    """Raised when a worker tries to submit an incomplete completion contract."""


class EvidenceReader(Protocol):
    def get_text(self, reference: str) -> str: ...


_PUBLIC_RESEARCH_TOOLS = {
    "deep_research",
    "summarize_url",
    "web_fetch",
    "web_search",
    "search_web",
    "search_web_fast",
    "search_web_slow",
    "browser_navigate",
    "browser_extract_content",
}


def _criterion_requirements(criterion: str) -> dict[str, bool]:
    text = " ".join(str(criterion).lower().split())
    return {
        "source_register": "source register" in text or ("source" in text and "register" in text),
        "amaura_relevance": "amaura" in text
        and any(term in text for term in ("relevance", "relevant", "implication", "application", "fit", "explained")),
        "originality": any(
            term in text
            for term in (
                "competitor copying",
                "copy competitor",
                "copying competitor",
                "no competitor copying",
                "no copying",
                "non-copying",
                "non copying",
                "originality",
                "original",
            )
        ),
    }


def _is_public_research_evidence(item: dict[str, Any]) -> bool:
    if item.get("success") is not True:
        return False
    tool = str(item.get("tool") or "").strip().lower()
    if tool in _PUBLIC_RESEARCH_TOOLS:
        return True
    return tool.startswith("web_") or tool.startswith("browser_search")


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _nonempty_list_or_text(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return any(_clean_text(item) for item in value)
    return False


def extract_completion_contract(text: str) -> dict[str, Any]:
    """Extract one JSON completion contract without accepting prose-only output."""
    candidate = str(text or "").strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?\s*", "", candidate, count=1, flags=re.IGNORECASE)
        candidate = re.sub(r"\s*```$", "", candidate, count=1)
    start, end = candidate.find("{"), candidate.rfind("}")
    if start < 0 or end <= start:
        raise CompletionContractError("worker completion synthesis returned no JSON object")
    try:
        value = json.loads(candidate[start : end + 1])
    except json.JSONDecodeError as exc:
        raise CompletionContractError("worker completion synthesis returned malformed JSON") from exc
    if not isinstance(value, dict):
        raise CompletionContractError("worker completion contract must be a JSON object")
    return value


def build_completion_packet(
    *,
    task_packet: dict[str, Any],
    draft_summary: str,
    evidence: list[dict[str, Any]],
    evidence_reader: EvidenceReader,
    max_total_payload_chars: int = 48_000,
    max_payload_chars_per_item: int = 4_000,
) -> dict[str, Any]:
    """Load immutable evidence into a bounded packet for the dedicated synthesis pass."""
    successful = [item for item in evidence if item.get("success") is True and item.get("reference")]
    if successful:
        per_item = max(
            600,
            min(max_payload_chars_per_item, max_total_payload_chars // max(1, len(successful))),
        )
    else:
        per_item = max_payload_chars_per_item

    packed_evidence: list[dict[str, Any]] = []
    remaining = max_total_payload_chars
    for item in evidence:
        reference = _clean_text(item.get("reference"))
        payload = ""
        if reference and remaining > 0:
            try:
                payload = evidence_reader.get_text(reference)
            except (OSError, ValueError):
                payload = ""
            payload = payload[: min(per_item, remaining)]
            remaining -= len(payload)
        packed_evidence.append(
            {
                "reference": reference,
                "type": _clean_text(item.get("type")),
                "tool": _clean_text(item.get("tool")),
                "success": item.get("success") is True,
                "excerpt": _clean_text(item.get("excerpt"))[:1000],
                "payload": payload,
            }
        )

    criteria = [str(item) for item in task_packet.get("acceptance_criteria") or []]
    return {
        "task": {
            "objective": _clean_text(task_packet.get("objective")),
            "success_metric": _clean_text(task_packet.get("success_metric")),
            "acceptance_criteria": criteria,
            "action_type": _clean_text(task_packet.get("action_type")),
            "doctrine": list(task_packet.get("doctrine") or []),
        },
        "draft_summary": _clean_text(draft_summary),
        "criterion_requirements": [
            {
                "criterion_index": index,
                "criterion": criterion,
                **_criterion_requirements(criterion),
            }
            for index, criterion in enumerate(criteria, start=1)
        ],
        "evidence": packed_evidence,
    }


def completion_system_prompt() -> str:
    """Return the worker-side synthesis instruction. Reviewer policy is intentionally untouched."""
    return """You are the final completion synthesizer for a governed Amaura worker.
Raw tool output is evidence, not a deliverable. Use ONLY the supplied immutable evidence and task packet.
Do not add facts that are not supported by evidence. If evidence cannot support a criterion, set satisfied=false.
Return exactly one JSON object and no markdown.

Required schema:
{
  "version": 1,
  "summary": "concise overall deliverable summary",
  "criteria": [
    {
      "criterion_index": 1,
      "criterion": "exact acceptance criterion text",
      "satisfied": true,
      "deliverable": "criterion-specific synthesis that actually answers the criterion",
      "evidence_refs": ["evidence://..."],
      "fact_inference_boundary": "what comes directly from sources versus what is Amaura's inference",
      "amaura_relevance": "required only when criterion_requirements.amaura_relevance is true",
      "originality_rationale": {
        "observed_patterns": ["patterns observed in competitors/sources"],
        "category_level_ideas": ["generic category ideas that may be learned from"],
        "amaura_differentiation": ["how Amaura's recommendation differs"],
        "copying_avoidance": ["specific wording/workflows/branding/proprietary elements not to copy"]
      }
    }
  ],
  "source_register": [
    {
      "evidence_ref": "evidence://...",
      "source": "publisher/site/result identity",
      "locator": "URL, query, or other locator present in the evidence",
      "finding": "what this source actually supports",
      "supports_criteria": [1, 2]
    }
  ]
}

Rules:
- Include exactly one criteria object for every acceptance criterion, in order, with exact criterion text.
- Every satisfied criterion needs at least one submitted successful evidence reference.
- fact_inference_boundary is mandatory for every criterion.
- If a source register is required, include every successful public-research evidence item at least once.
- If Amaura relevance is required, explain the concrete opportunity/threat/design/strategy implication for Amaura; do not merely restate the source.
- If originality/non-copying is required, separate generic category patterns from competitor-specific expression and state concrete Amaura differentiation and copying-avoidance rules.
- Never treat the existence of a search/tool call as proof that a semantic criterion is satisfied.
- When in doubt, set satisfied=false. Independent review happens after this contract."""


def validate_completion_contract(
    contract: dict[str, Any],
    *,
    acceptance_criteria: list[str],
    evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    """Fail closed unless the contract structurally maps real evidence to every criterion."""
    if not isinstance(contract, dict):
        raise CompletionContractError("completion contract must be an object")
    summary = _clean_text(contract.get("summary"))
    if not summary:
        raise CompletionContractError("completion contract summary is required")

    submitted_refs = {
        _clean_text(item.get("reference"))
        for item in evidence
        if item.get("success") is True and _clean_text(item.get("reference"))
    }
    criteria_rows = contract.get("criteria")
    if not isinstance(criteria_rows, list) or len(criteria_rows) != len(acceptance_criteria):
        raise CompletionContractError(
            f"completion contract must contain exactly {len(acceptance_criteria)} criterion rows"
        )

    normalized_rows: list[dict[str, Any]] = []
    for index, expected in enumerate(acceptance_criteria, start=1):
        row = criteria_rows[index - 1]
        if not isinstance(row, dict):
            raise CompletionContractError(f"criterion {index} completion row must be an object")
        if row.get("criterion_index") != index:
            raise CompletionContractError(f"criterion {index} has the wrong criterion_index")
        if _clean_text(row.get("criterion")) != expected:
            raise CompletionContractError(f"criterion {index} text does not exactly match the task packet")
        if row.get("satisfied") is not True:
            raise CompletionContractError(f"criterion {index} is not yet satisfied: {expected}")
        if not _clean_text(row.get("deliverable")):
            raise CompletionContractError(f"criterion {index} has no synthesized deliverable")
        if not _clean_text(row.get("fact_inference_boundary")):
            raise CompletionContractError(f"criterion {index} does not separate source facts from worker inference")

        refs = row.get("evidence_refs")
        if not isinstance(refs, list) or not refs:
            raise CompletionContractError(f"criterion {index} has no evidence references")
        clean_refs = [_clean_text(ref) for ref in refs if _clean_text(ref)]
        if len(clean_refs) != len(refs):
            raise CompletionContractError(f"criterion {index} contains an empty evidence reference")
        unknown = set(clean_refs) - submitted_refs
        if unknown:
            raise CompletionContractError(
                f"criterion {index} cites evidence not submitted by this worker: {sorted(unknown)!r}"
            )

        requirements = _criterion_requirements(expected)
        if requirements["amaura_relevance"] and not _clean_text(row.get("amaura_relevance")):
            raise CompletionContractError(f"criterion {index} requires an explicit Amaura relevance synthesis")
        if requirements["originality"]:
            originality = row.get("originality_rationale")
            if not isinstance(originality, dict):
                raise CompletionContractError(f"criterion {index} requires an originality/non-copying rationale")
            for field in (
                "observed_patterns",
                "category_level_ideas",
                "amaura_differentiation",
                "copying_avoidance",
            ):
                if not _nonempty_list_or_text(originality.get(field)):
                    raise CompletionContractError(
                        f"criterion {index} originality rationale is missing {field}"
                    )

        normalized_rows.append({**row, "evidence_refs": clean_refs})

    source_register = contract.get("source_register") or []
    needs_register = any(_criterion_requirements(item)["source_register"] for item in acceptance_criteria)
    if needs_register:
        if not isinstance(source_register, list) or not source_register:
            raise CompletionContractError("a complete source register is required before submission")
        register_refs: set[str] = set()
        for row_index, row in enumerate(source_register, start=1):
            if not isinstance(row, dict):
                raise CompletionContractError(f"source register row {row_index} must be an object")
            reference = _clean_text(row.get("evidence_ref"))
            if reference not in submitted_refs:
                raise CompletionContractError(
                    f"source register row {row_index} cites unknown/failed evidence: {reference or '<empty>'}"
                )
            if not _clean_text(row.get("source")) or not _clean_text(row.get("finding")):
                raise CompletionContractError(
                    f"source register row {row_index} requires source identity and supported finding"
                )
            supports = row.get("supports_criteria")
            if not isinstance(supports, list) or not supports:
                raise CompletionContractError(f"source register row {row_index} must map to acceptance criteria")
            if any(not isinstance(value, int) or value < 1 or value > len(acceptance_criteria) for value in supports):
                raise CompletionContractError(f"source register row {row_index} has invalid criterion indexes")
            register_refs.add(reference)

        research_refs = {
            _clean_text(item.get("reference"))
            for item in evidence
            if _is_public_research_evidence(item) and _clean_text(item.get("reference"))
        }
        missing = research_refs - register_refs
        if missing:
            raise CompletionContractError(
                "source register is incomplete; missing successful public-research evidence refs: "
                + ", ".join(sorted(missing))
            )

    return {
        **contract,
        "version": 1,
        "summary": summary,
        "criteria": normalized_rows,
        "source_register": source_register if isinstance(source_register, list) else [],
    }


__all__ = [
    "CompletionContractError",
    "build_completion_packet",
    "completion_system_prompt",
    "extract_completion_contract",
    "validate_completion_contract",
]
