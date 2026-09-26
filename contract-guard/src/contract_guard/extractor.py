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
    Handles application/json, vendor +json content types, and $ref resolution.
    """
    responses = operation.get("responses") or {}
    response = responses.get(status) or responses.get(int(status))
    if not isinstance(response, dict):
        return None
    if "$ref" in response:
        response = resolve_schema(response, root)
    content = response.get("content") or {}
    json_content = content.get("application/json")
    if not json_content or not isinstance(json_content, dict):
        # Support vendor or charset JSON: application/vnd.api+json, application/json;charset=utf-8
        for ct, ct_val in content.items():
            if isinstance(ct, str) and isinstance(ct_val, dict) and ("json" in ct.lower() or ct.endswith("+json")):
                json_content = ct_val
                break

    if not isinstance(json_content, dict):
        return None

    schema = json_content.get("schema")
    if not isinstance(schema, dict):
        return None
    return resolve_schema(schema, root)


def flatten_properties(
    schema: dict[str, Any],
    root: dict[str, Any],
    prefix: str = "",
    seen_refs: set[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """
    Recursively walk an object schema and return a flat map of
    dot-separated field paths → property schemas.

    Only descends into 'object' type (or schemas with 'properties'),
    with circular reference protection. Supports top-level arrays.
    """
    if seen_refs is None:
        seen_refs = set()

    ref = schema.get("$ref") if isinstance(schema, dict) else None
    if ref:
        if ref in seen_refs:
            return {}
        seen_refs.add(ref)

    result: dict[str, dict[str, Any]] = {}
    resolved = resolve_schema(schema, root)
    if not isinstance(resolved, dict):
        return {}

    # Handle array schema at this level
    if resolved.get("type") == "array" or "items" in resolved:
        items = resolved.get("items")
        if isinstance(items, dict):
            items_ref = items.get("$ref")
            if items_ref and items_ref in seen_refs:
                return {}
            items_seen = seen_refs.copy()
            if items_ref:
                items_seen.add(items_ref)
            array_prefix = f"{prefix}[]" if prefix else "[]"
            return flatten_properties(items, root, prefix=array_prefix, seen_refs=items_seen)
        return {}

    props = resolved.get("properties") or {}
    required_fields: set[str] = set(resolved.get("required") or [])

    for name, prop_schema in props.items():
        if not isinstance(prop_schema, dict):
            continue
        full_name = f"{prefix}.{name}" if prefix else name
        prop_ref = prop_schema.get("$ref")
        if prop_ref and prop_ref in seen_refs:
            continue

        resolved_prop = resolve_schema(prop_schema, root)
        if not isinstance(resolved_prop, dict):
            continue

        # Store type + required flag together for rule evaluation
        enriched = dict(resolved_prop)
        enriched["_required"] = name in required_fields
        result[full_name] = enriched

        new_seen = seen_refs.copy()
        if prop_ref:
            new_seen.add(prop_ref)

        # Recurse into nested objects
        prop_type = resolved_prop.get("type")
        if prop_type == "object" or (
            prop_type is None and "properties" in resolved_prop
        ):
            nested = flatten_properties(prop_schema, root, prefix=full_name, seen_refs=new_seen)
            result.update(nested)
        elif prop_type == "array":
            items = resolved_prop.get("items")
            if isinstance(items, dict):
                items_ref = items.get("$ref")
                if items_ref and items_ref in new_seen:
                    continue
                items_seen = new_seen.copy()
                if items_ref:
                    items_seen.add(items_ref)
                nested = flatten_properties(
                    items, root, prefix=f"{full_name}[]", seen_refs=items_seen
                )
                result.update(nested)

    return result
