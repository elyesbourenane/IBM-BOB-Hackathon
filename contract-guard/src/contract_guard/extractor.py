"""Extract normalised endpoint/schema information from an OpenAPI document."""

from __future__ import annotations

from typing import Any

from .loader import resolve_schema


def _http_methods() -> frozenset[str]:
    return frozenset({"get", "put", "post", "delete", "patch", "options", "head"})


def iter_endpoints(doc: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    """
    Yield (method, path, operation_object) tuples for every operation in the doc.
    """
    results: list[tuple[str, str, dict[str, Any]]] = []
    for path, path_item in (doc.get("paths") or {}).items():
        if not isinstance(path_item, dict):
            continue
        for method in _http_methods():
            operation = path_item.get(method)
            if isinstance(operation, dict):
                results.append((method.upper(), path, operation))
    return results


def get_response_schema(
    operation: dict[str, Any],
    root: dict[str, Any],
    status: str = "200",
) -> dict[str, Any] | None:
    """
    Return the JSON schema for the given response status code, or None if absent.
    Handles application/json content type and $ref resolution.
    """
    responses = operation.get("responses") or {}
    response = responses.get(status) or responses.get(int(status))
    if not isinstance(response, dict):
        return None
    if "$ref" in response:
        response = resolve_schema(response, root)
    content = response.get("content") or {}
    json_content = content.get("application/json") or {}
    schema = json_content.get("schema")
    if not isinstance(schema, dict):
        return None
    return resolve_schema(schema, root)


def flatten_properties(
    schema: dict[str, Any],
    root: dict[str, Any],
    prefix: str = "",
) -> dict[str, dict[str, Any]]:
    """
    Recursively walk an object schema and return a flat map of
    dot-separated field paths → property schemas.

    Only descends into 'object' type (or schemas with 'properties').
    """
    result: dict[str, dict[str, Any]] = {}
    schema = resolve_schema(schema, root)
    props = schema.get("properties") or {}
    required_fields: set[str] = set(schema.get("required") or [])

    for name, prop_schema in props.items():
        full_name = f"{prefix}.{name}" if prefix else name
        prop_schema = resolve_schema(prop_schema, root)
        # Store type + required flag together for rule evaluation
        enriched = dict(prop_schema)
        enriched["_required"] = name in required_fields
        result[full_name] = enriched

        # Recurse into nested objects
        prop_type = prop_schema.get("type")
        if prop_type == "object" or (
            prop_type is None and "properties" in prop_schema
        ):
            nested = flatten_properties(prop_schema, root, prefix=full_name)
            result.update(nested)

    return result
