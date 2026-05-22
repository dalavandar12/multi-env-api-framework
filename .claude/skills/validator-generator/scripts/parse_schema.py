"""Load and validate a schema YAML file.

The output is an in-memory normalized form that emit_validator.py walks to
produce Python code. Catches mistakes early (missing top-level keys,
unsupported types, conflicting modifiers) so emission never has to guess.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

LOG = logging.getLogger(__name__)


class SchemaError(Exception):
    """Raised when a schema YAML is missing required keys or unsupported types."""


_REQUIRED_TOP_LEVEL = ("component", "validator_name", "shape")

_PRIMITIVE_TYPES = {
    "string", "integer", "number", "boolean",
    "number_or_null", "string_or_null",
}
_CONTAINER_TYPES = {"object", "array"}
_ALL_TYPES = _PRIMITIVE_TYPES | _CONTAINER_TYPES

_PRIMITIVE_MODIFIERS = {
    "string":          {"non_empty"},
    "integer":         {"min", "max"},
    "number":          {"min", "max"},
    "number_or_null":  set(),
    "string_or_null":  set(),
    "boolean":         set(),
}


def load(path: Path) -> dict[str, Any]:
    """Read + validate the schema YAML; return the parsed dict."""
    if not path.exists():
        raise SchemaError(f"schema file not found: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise SchemaError(f"could not parse {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SchemaError(f"{path} top-level must be a mapping")
    missing = [k for k in _REQUIRED_TOP_LEVEL if k not in data]
    if missing:
        raise SchemaError(f"{path} missing required key(s): {missing}")
    _validate_node(data["shape"], path_for_errors="shape")
    LOG.info("Loaded schema for component=%s validator=%s",
             data["component"], data["validator_name"])
    return dict(data)


def _validate_node(node: Any, *, path_for_errors: str) -> None:
    """Recursively check that every field declaration is well-formed."""
    if not isinstance(node, dict):
        raise SchemaError(f"{path_for_errors} must be a mapping, got {type(node).__name__}")
    t = node.get("type")
    if t is None:
        raise SchemaError(f"{path_for_errors} is missing 'type'")
    if t not in _ALL_TYPES:
        raise SchemaError(
            f"{path_for_errors}.type='{t}' is not supported. "
            f"Allowed: {sorted(_ALL_TYPES)}"
        )

    if t == "object":
        required = node.get("required") or []
        if not isinstance(required, list):
            raise SchemaError(f"{path_for_errors}.required must be a list")
        fields = node.get("fields") or {}
        if not isinstance(fields, dict):
            raise SchemaError(f"{path_for_errors}.fields must be a mapping")
        for key in required:
            if key not in fields:
                LOG.warning(
                    "%s lists '%s' as required but does not define it in 'fields' — "
                    "the assertion will check presence only.",
                    path_for_errors, key,
                )
        for name, sub in fields.items():
            _validate_node(sub, path_for_errors=f"{path_for_errors}.fields.{name}")
        return

    if t == "array":
        item_type = node.get("item_type")
        if not isinstance(item_type, str):
            raise SchemaError(f"{path_for_errors}.item_type must be a string")
        if item_type not in _ALL_TYPES and item_type != "any":
            raise SchemaError(
                f"{path_for_errors}.item_type='{item_type}' unsupported. "
                f"Use one of {sorted(_ALL_TYPES)} or 'any'."
            )
        for mod in ("min_length", "max_length"):
            if mod in node and not isinstance(node[mod], int):
                raise SchemaError(f"{path_for_errors}.{mod} must be int")
        return

    # Primitive — allowed modifiers only
    allowed = _PRIMITIVE_MODIFIERS.get(t, set())
    extras = set(node.keys()) - {"type"} - allowed
    if extras:
        raise SchemaError(
            f"{path_for_errors}: unsupported modifier(s) for type '{t}': {sorted(extras)}. "
            f"Allowed for {t}: {sorted(allowed) or 'none'}"
        )
