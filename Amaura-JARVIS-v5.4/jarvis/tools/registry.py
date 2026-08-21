"""
Tool Registry — unifies all tool categories into a single dispatch system.

The public registry API is deliberately defined before category imports. Some
coding tools import Amaura helpers, while Amaura's semantic runtime imports the
registry through direct_action. Publishing stable mutable registry objects first
breaks that import cycle without weakening semantic initialization.
"""

from jarvis.tools.result import ToolResult, parse_tool_result
from jarvis.tools.schema_validation import ToolArgumentValidationError, validate_tool_arguments
from jarvis.tools.security import secure_tool_arguments

# These objects must never be rebound: modules imported during registry bootstrap
# may retain references to them. Category imports populate them in-place below.
ALL_DISPATCH: dict[str, object] = {}
ALL_TOOL_DEFINITIONS: list[dict] = []
_TOOL_ARGUMENT_SCHEMAS: dict[str, dict] = {}


def execute_tool(name: str, args: dict) -> str:
    """Execute a tool behind its published, closed argument contract."""
    if name not in ALL_DISPATCH:
        return ToolResult.failure(f"Unknown tool: {name}", code="UNKNOWN_TOOL").to_json()
    try:
        validated_args = validate_tool_arguments(name, args, _TOOL_ARGUMENT_SCHEMAS[name])
        secured_args = secure_tool_arguments(name, validated_args)
        handler = ALL_DISPATCH[name]
        if not callable(handler):
            return ToolResult.failure(f"Tool handler is not callable: {name}", code="TOOL_EXCEPTION").to_json()
        result = handler(**secured_args)
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


# Category imports intentionally happen only after the stable public API above.
from jarvis.fleet import FLEET_DISPATCH, FLEET_TOOL_DEFINITIONS
from jarvis.hud import HUD_DISPATCH, HUD_TOOL_DEFINITIONS
from jarvis.tools.advanced_coding import ADVANCED_CODING_DISPATCH, ADVANCED_CODING_TOOL_DEFINITIONS
from jarvis.tools.agent_factory import AGENT_FACTORY_DISPATCH, AGENT_FACTORY_TOOL_DEFINITIONS
from jarvis.tools.amaura import AMAURA_DISPATCH, AMAURA_TOOL_DEFINITIONS
from jarvis.tools.app_builder import APP_BUILDER_DISPATCH, APP_BUILDER_TOOL_DEFINITIONS
from jarvis.tools.ast_indexer import AST_DISPATCH, AST_TOOL_DEFINITIONS
from jarvis.tools.browser import BROWSER_DISPATCH, BROWSER_TOOL_DEFINITIONS
from jarvis.tools.coding import CODING_DISPATCH, CODING_TOOL_DEFINITIONS
from jarvis.tools.communication import COMMUNICATION_DISPATCH, COMMUNICATION_TOOL_DEFINITIONS
from jarvis.tools.desktop import DESKTOP_DISPATCH, DESKTOP_TOOL_DEFINITIONS
from jarvis.tools.documents import DOCUMENT_DISPATCH, DOCUMENT_TOOL_DEFINITIONS
from jarvis.tools.research import RESEARCH_DISPATCH, RESEARCH_TOOL_DEFINITIONS
from jarvis.tools.resilient_research import RESILIENT_RESEARCH_DISPATCH
from jarvis.tools.tdd_loop import TDD_DISPATCH, TDD_TOOL_DEFINITIONS
from jarvis.tools.vector_memory import VECTOR_MEMORY_DISPATCH, VECTOR_MEMORY_TOOL_DEFINITIONS
from jarvis.tools.vision import VISION_DISPATCH, VISION_TOOL_DEFINITIONS
from jarvis.voice.duplex_voice import VOICE_DISPATCH, VOICE_TOOL_DEFINITIONS


def _merge_unique_definitions(*groups: list[dict]) -> list[dict]:
    """Merge schemas by name with explicit last-provider precedence.

    Dispatch gives later specialist modules precedence. Tool schemas follow the
    same rule so a model never sees conflicting contracts.
    """
    merged: dict[str, dict] = {}
    for group in groups:
        for definition in group:
            name = definition.get("function", {}).get("name", "")
            if not name:
                raise ValueError("Tool definitions require a non-empty function name")
            merged[name] = definition
    return list(merged.values())


ALL_TOOL_DEFINITIONS.extend(
    _merge_unique_definitions(
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
)

ALL_DISPATCH.update(
    {
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
        # Same public schemas; these last-provider handlers add a hard timeout
        # boundary around network search so third-party hangs cannot freeze JARVIS.
        **RESILIENT_RESEARCH_DISPATCH,
    }
)

_TOOL_ARGUMENT_SCHEMAS.update(
    {
        definition["function"]["name"]: definition["function"].get("parameters", {"type": "object", "properties": {}})
        for definition in ALL_TOOL_DEFINITIONS
    }
)


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
