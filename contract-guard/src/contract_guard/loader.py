"""Load and lightly normalise OpenAPI YAML contracts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_contract(path: str | Path) -> dict[str, Any]:
    """Parse an OpenAPI YAML file and return the raw dict."""
    with open(path, encoding="utf-8") as fh:
        doc = yaml.safe_load(fh)
    if not isinstance(doc, dict):
        raise ValueError(f"Expected a YAML mapping, got {type(doc).__name__}: {path}")
    return doc


def resolve_ref(ref: str, root: dict[str, Any]) -> dict[str, Any]:
    """
    Follow a simple local $ref such as '#/components/schemas/PaymentResponse'.
    Only local refs (#/...) are supported.
    """
    if not ref.startswith("#/"):
        raise ValueError(f"External $ref not supported: {ref!r}")
    parts = ref.lstrip("#/").split("/")
    node: Any = root
    for part in parts:
        if not isinstance(node, dict) or part not in node:
            raise KeyError(f"$ref target not found: {ref!r}")
        node = node[part]
    return node


def resolve_schema(schema: dict[str, Any], root: dict[str, Any]) -> dict[str, Any]:
    """Return the schema dict, resolving a top-level $ref if present."""
    if "$ref" in schema:
        return resolve_ref(schema["$ref"], root)
    return schema
