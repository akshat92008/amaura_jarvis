"""
Tool Registry — unifies all tool categories into a single dispatch system.
Combines Coding, Advanced Coding, Agent Factory, Desktop, Research, Documents, Communication,
App Builder, TDD Loop, AST Indexer, Vision, Vector Memory, Fleet, Browser, HUD, and Duplex Voice tools.
"""

from jarvis.tools.coding import CODING_TOOL_DEFINITIONS, CODING_DISPATCH
from jarvis.tools.advanced_coding import ADVANCED_CODING_TOOL_DEFINITIONS, ADVANCED_CODING_DISPATCH
from jarvis.tools.agent_factory import AGENT_FACTORY_TOOL_DEFINITIONS, AGENT_FACTORY_DISPATCH
from jarvis.tools.desktop import DESKTOP_TOOL_DEFINITIONS, DESKTOP_DISPATCH
from jarvis.tools.research import RESEARCH_TOOL_DEFINITIONS, RESEARCH_DISPATCH
from jarvis.tools.documents import DOCUMENT_TOOL_DEFINITIONS, DOCUMENT_DISPATCH
from jarvis.tools.communication import COMMUNICATION_TOOL_DEFINITIONS, COMMUNICATION_DISPATCH

# ── New Master Modules ────────────────────────────────────────────────────────
from jarvis.tools.app_builder import APP_BUILDER_TOOL_DEFINITIONS, APP_BUILDER_DISPATCH
from jarvis.tools.tdd_loop import TDD_TOOL_DEFINITIONS, TDD_DISPATCH
from jarvis.tools.ast_indexer import AST_TOOL_DEFINITIONS, AST_DISPATCH
from jarvis.tools.vision import VISION_TOOL_DEFINITIONS, VISION_DISPATCH
from jarvis.tools.vector_memory import VECTOR_MEMORY_TOOL_DEFINITIONS, VECTOR_MEMORY_DISPATCH
from jarvis.fleet import FLEET_TOOL_DEFINITIONS, FLEET_DISPATCH
from jarvis.tools.browser import BROWSER_TOOL_DEFINITIONS, BROWSER_DISPATCH
from jarvis.hud import HUD_TOOL_DEFINITIONS, HUD_DISPATCH
from jarvis.voice.duplex_voice import VOICE_TOOL_DEFINITIONS, VOICE_DISPATCH
from jarvis.tools.amaura import AMAURA_TOOL_DEFINITIONS, AMAURA_DISPATCH


# ── Combined Tool Definitions ──────────────────────────────────────────────────

def _merge_unique_definitions(*groups: list[dict]) -> list[dict]:
    """Merge schemas by name with explicit last-provider precedence.

    The dispatch registry already gives later specialist modules precedence.  Tool
    schemas must follow the same rule so a model never sees conflicting contracts.
    """
    merged: dict[str, dict] = {}
    for group in groups:
        for definition in group:
            name = definition.get("function", {}).get("name", "")
            if not name:
                raise ValueError("Tool definitions require a non-empty function name")
            merged[name] = definition
    return list(merged.values())


ALL_TOOL_DEFINITIONS = _merge_unique_definitions(
    CODING_TOOL_DEFINITIONS,
    ADVANCED_CODING_TOOL_DEFINITIONS,
    AGENT_FACTORY_TOOL_DEFINITIONS,
    DESKTOP_TOOL_DEFINITIONS,
    RESEARCH_TOOL_DEFINITIONS,
    DOCUMENT_TOOL_DEFINITIONS,
    COMMUNICATION_TOOL_DEFINITIONS,
    APP_BUILDER_TOOL_DEFINITIONS,
    TDD_TOOL_DEFINITIONS,
    AST_TOOL_DEFINITIONS,
    VISION_TOOL_DEFINITIONS,
    VECTOR_MEMORY_TOOL_DEFINITIONS,
    FLEET_TOOL_DEFINITIONS,
    BROWSER_TOOL_DEFINITIONS,
    HUD_TOOL_DEFINITIONS,
    VOICE_TOOL_DEFINITIONS,
    AMAURA_TOOL_DEFINITIONS,
)


# ── Combined Dispatch ────────────────────────────────────────────────────────

ALL_DISPATCH = {
    **CODING_DISPATCH,
    **ADVANCED_CODING_DISPATCH,
    **AGENT_FACTORY_DISPATCH,
    **DESKTOP_DISPATCH,
    **RESEARCH_DISPATCH,
    **DOCUMENT_DISPATCH,
    **COMMUNICATION_DISPATCH,
    **APP_BUILDER_DISPATCH,
    **TDD_DISPATCH,
    **AST_DISPATCH,
    **VISION_DISPATCH,
    **VECTOR_MEMORY_DISPATCH,
    **FLEET_DISPATCH,
    **BROWSER_DISPATCH,
    **HUD_DISPATCH,
    **VOICE_DISPATCH,
    **AMAURA_DISPATCH,
}


import json

from jarvis.tools.result import ToolResult, parse_tool_result
from jarvis.tools.security import secure_tool_arguments
from jarvis.tools.schema_validation import ToolArgumentValidationError, validate_tool_arguments


_TOOL_ARGUMENT_SCHEMAS = {
    definition["function"]["name"]: definition["function"].get("parameters", {"type": "object", "properties": {}})
    for definition in ALL_TOOL_DEFINITIONS
}


def execute_tool(name: str, args: dict) -> str:
    """Execute a tool behind its published, closed argument contract."""
    if name not in ALL_DISPATCH:
        return ToolResult.failure(f"Unknown tool: {name}", code="UNKNOWN_TOOL").to_json()
    try:
        validated_args = validate_tool_arguments(name, args, _TOOL_ARGUMENT_SCHEMAS[name])
        secured_args = secure_tool_arguments(name, validated_args)
        result = ALL_DISPATCH[name](**secured_args)
        return parse_tool_result(result).to_json()
    except ToolArgumentValidationError as exc:
        return ToolResult.failure(str(exc), code="INVALID_TOOL_ARGUMENTS").to_json()
    except PermissionError as exc:
        return ToolResult.failure(str(exc), code="WORKSPACE_BOUNDARY").to_json()
    except FileNotFoundError as exc:
        return ToolResult.failure(f"File not found: {exc}", code="FILE_NOT_FOUND").to_json()
    except ValueError as exc:
        return ToolResult.failure(str(exc), code="INVALID_TOOL_ARGUMENTS").to_json()
    except Exception as exc:
        return ToolResult.failure(f"Tool error ({name}): {exc}", code="TOOL_EXCEPTION").to_json()


def get_tool_count() -> dict:
    """Return tool counts by category."""
    return {
        "coding": len(CODING_TOOL_DEFINITIONS),
        "advanced_coding": len(ADVANCED_CODING_TOOL_DEFINITIONS),
        "agent_factory": len(AGENT_FACTORY_TOOL_DEFINITIONS),
        "desktop": len(DESKTOP_TOOL_DEFINITIONS),
        "research": len(RESEARCH_TOOL_DEFINITIONS),
        "documents": len(DOCUMENT_TOOL_DEFINITIONS),
        "communication": len(COMMUNICATION_TOOL_DEFINITIONS),
        "app_builder": len(APP_BUILDER_TOOL_DEFINITIONS),
        "tdd_loop": len(TDD_TOOL_DEFINITIONS),
        "ast_indexer": len(AST_TOOL_DEFINITIONS),
        "vision": len(VISION_TOOL_DEFINITIONS),
        "vector_memory": len(VECTOR_MEMORY_TOOL_DEFINITIONS),
        "fleet": len(FLEET_TOOL_DEFINITIONS),
        "browser": len(BROWSER_TOOL_DEFINITIONS),
        "hud": len(HUD_TOOL_DEFINITIONS),
        "duplex_voice": len(VOICE_TOOL_DEFINITIONS),
        "amaura_company_os": len(AMAURA_TOOL_DEFINITIONS),
        "total": len(ALL_TOOL_DEFINITIONS),
    }
