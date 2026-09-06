"""Strict runtime validation for model-supplied tool arguments.

The model-facing JSON schemas are treated as executable security contracts.
Unknown fields and incorrect types are rejected before path normalization or
handler dispatch.  This intentionally implements the small JSON-Schema subset
used by Jarvis tool definitions without introducing another runtime dependency.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from typing import Any, TypeAlias


class ToolArgumentValidationError(ValueError):
    """Raised when a tool call violates its published argument contract."""


JsonRuntimeType: TypeAlias = type[Any] | tuple[type[Any], ...]

_TYPE_NAMES: dict[str, JsonRuntimeType] = {
    "object": dict,
    "array": list,
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "null": type(None),
}


def _fail(path: str, message: str) -> None:
    raise ToolArgumentValidationError(f"{path}: {message}")


def _type_matches(value: Any, expected: str) -> bool:
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))
    python_type = _TYPE_NAMES.get(expected)
    if python_type is None:
        _fail("schema", f"unsupported JSON schema type {expected!r}")
    assert python_type is not None
    return isinstance(value, python_type)


def _validate(value: Any, schema: Mapping[str, Any], path: str) -> None:
    if "enum" in schema and value not in schema["enum"]:
        _fail(path, f"must be one of {schema['enum']!r}")

    expected = schema.get("type")
    if isinstance(expected, list):
        if not any(_type_matches(value, item) for item in expected):
            _fail(path, f"expected one of {expected!r}, got {type(value).__name__}")
    elif isinstance(expected, str) and not _type_matches(value, expected):
        _fail(path, f"expected {expected}, got {type(value).__name__}")

    if expected == "object" or (expected is None and isinstance(value, dict)):
        if not isinstance(value, dict):
            return
        properties = schema.get("properties", {})
        if not isinstance(properties, Mapping):
            _fail(path, "schema properties must be an object")
        required = schema.get("required", [])
        for key in required:
            if key not in value:
                _fail(path, f"missing required property {key!r}")
        # Model tool contracts are closed by default unless additionalProperties is explicitly allowed.
        allow_additional = bool(schema.get("additionalProperties", False))
        if not allow_additional:
            unknown = sorted(set(value) - set(properties))
            if unknown:
                _fail(path, f"unexpected properties: {', '.join(unknown)}")
        for key, item in value.items():
            child_schema = properties.get(key)
            if child_schema is None and allow_additional:
                continue
            if not isinstance(child_schema, Mapping):
                _fail(f"{path}.{key}", "invalid property schema")
            _validate(item, child_schema, f"{path}.{key}")
        return

    if expected == "array":
        items = schema.get("items", {})
        if not isinstance(items, Mapping):
            _fail(path, "array items schema must be an object")
        if "minItems" in schema and len(value) < int(schema["minItems"]):
            _fail(path, f"requires at least {schema['minItems']} items")
        if "maxItems" in schema and len(value) > int(schema["maxItems"]):
            _fail(path, f"allows at most {schema['maxItems']} items")
        for index, item in enumerate(value):
            _validate(item, items, f"{path}[{index}]")
        return

    if expected == "string":
        if "minLength" in schema and len(value) < int(schema["minLength"]):
            _fail(path, f"must contain at least {schema['minLength']} characters")
        if "maxLength" in schema and len(value) > int(schema["maxLength"]):
            _fail(path, f"must contain at most {schema['maxLength']} characters")
        pattern = schema.get("pattern")
        if isinstance(pattern, str) and re.fullmatch(pattern, value) is None:
            _fail(path, "does not match the required pattern")

    if expected in {"integer", "number"}:
        if "minimum" in schema and value < schema["minimum"]:
            _fail(path, f"must be >= {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            _fail(path, f"must be <= {schema['maximum']}")


def _coerce_types(args: dict, schema: Mapping[str, Any]) -> dict:
    if not isinstance(args, dict):
        return args
    res = dict(args)
    props = schema.get("properties", {})
    for k, v in list(res.items()):
        prop_schema = props.get(k)
        if isinstance(prop_schema, dict):
            expected = prop_schema.get("type")
            if expected == "integer" and isinstance(v, str) and (v.strip().isdigit() or (v.strip().startswith("-") and v.strip()[1:].isdigit())):
                res[k] = int(v.strip())
            elif expected == "number" and isinstance(v, str):
                try:
                    res[k] = float(v.strip())
                except ValueError:
                    pass
            elif expected == "boolean" and isinstance(v, str):
                if v.lower() in ("true", "1"):
                    res[k] = True
                elif v.lower() in ("false", "0"):
                    res[k] = False
    return res


def validate_tool_arguments(name: str, args: Any, schema: Mapping[str, Any]) -> dict[str, Any]:
    """Return a validated shallow copy of *args* or raise fail-closed."""
    if not isinstance(args, dict):
        raise ToolArgumentValidationError(f"tool {name!r} arguments must be a JSON object, got {type(args).__name__}")
    args = _coerce_types(args, schema)
    _validate(args, schema, f"tool {name}")
    return dict(args)


__all__ = ["ToolArgumentValidationError", "validate_tool_arguments"]
