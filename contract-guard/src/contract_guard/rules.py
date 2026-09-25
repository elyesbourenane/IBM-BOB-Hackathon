"""
Compatibility rules engine.

Each rule is a pure function:

    def check_*(producer_props, consumer_props, endpoint, root_*) -> list[Finding]

Rules are collected and run by the Comparator.
"""

from __future__ import annotations

from typing import Any

from .models import ChangeKind, Finding


# ---------------------------------------------------------------------------
# Individual rules
# ---------------------------------------------------------------------------


def check_removed_fields(
    producer_props: dict[str, dict[str, Any]],
    consumer_props: dict[str, dict[str, Any]],
    endpoint: str,
) -> list[Finding]:
    """Fields present in the consumer but absent in the producer are REMOVED."""
    findings: list[Finding] = []
    for field_path in consumer_props:
        if field_path not in producer_props:
            findings.append(
                Finding(
                    endpoint=endpoint,
                    affected_field=field_path,
                    change_kind=ChangeKind.FIELD_REMOVED,
                    detail=(
                        f"Field '{field_path}' is expected by the consumer "
                        f"but is not present in the producer response."
                    ),
                )
            )
    return findings


def check_type_changes(
    producer_props: dict[str, dict[str, Any]],
    consumer_props: dict[str, dict[str, Any]],
    endpoint: str,
) -> list[Finding]:
    """Fields present in both but with different 'type' values are TYPE_CHANGED."""
    findings: list[Finding] = []
    for field_path, consumer_schema in consumer_props.items():
        producer_schema = producer_props.get(field_path)
        if producer_schema is None:
            continue  # handled by removed_fields
        p_type = producer_schema.get("type")
        c_type = consumer_schema.get("type")
        if p_type is not None and c_type is not None and p_type != c_type:
            findings.append(
                Finding(
                    endpoint=endpoint,
                    affected_field=field_path,
                    change_kind=ChangeKind.FIELD_TYPE_CHANGED,
                    detail=(
                        f"Producer type is '{p_type}', "
                        f"consumer expects '{c_type}'."
                    ),
                )
            )
    return findings


def check_required_added(
    producer_props: dict[str, dict[str, Any]],
    consumer_props: dict[str, dict[str, Any]],
    endpoint: str,
) -> list[Finding]:
    """
    Fields that are optional in the consumer but required in the producer
    are newly required — a breaking change for request bodies / general
    compatibility; also relevant when the consumer's own schema reflects
    what it *sends* and the producer now mandates more.

    For *response* fields, a field becoming required in the producer is
    actually fine for consumers. However, this rule focuses on the case
    where a field is newly required that the consumer did NOT list as
    required, which can signal a contract drift.

    We flag it when: producer marks required AND consumer does NOT.
    """
    findings: list[Finding] = []
    for field_path, producer_schema in producer_props.items():
        consumer_schema = consumer_props.get(field_path)
        if consumer_schema is None:
            continue  # new field — handled elsewhere
        p_required = producer_schema.get("_required", False)
        c_required = consumer_schema.get("_required", False)
        if p_required and not c_required:
            findings.append(
                Finding(
                    endpoint=endpoint,
                    affected_field=field_path,
                    change_kind=ChangeKind.FIELD_REQUIRED_ADDED,
                    detail=(
                        f"Field '{field_path}' is now required in the producer "
                        f"but was optional (or absent from required list) in the consumer."
                    ),
                )
            )
    return findings


def check_optional_added(
    producer_props: dict[str, dict[str, Any]],
    consumer_props: dict[str, dict[str, Any]],
    endpoint: str,
) -> list[Finding]:
    """Fields present in the producer but absent in the consumer are NEW OPTIONAL fields."""
    findings: list[Finding] = []
    for field_path, producer_schema in producer_props.items():
        if field_path not in consumer_props:
            is_required = producer_schema.get("_required", False)
            if not is_required:
                findings.append(
                    Finding(
                        endpoint=endpoint,
                        affected_field=field_path,
                        change_kind=ChangeKind.FIELD_OPTIONAL_ADDED,
                        detail=(
                                f"Field '{field_path}' is new in the producer response "
                                f"and is optional - existing consumers are unaffected."
                            ),
                    )
                )
            # If required AND missing from consumer → covered by check_removed_fields
            # (from the consumer's perspective the required field is simply absent)
    return findings


# ---------------------------------------------------------------------------
# Rename detection heuristic
# ---------------------------------------------------------------------------

def _detect_renames(
    producer_props: dict[str, dict[str, Any]],
    consumer_props: dict[str, dict[str, Any]],
    endpoint: str,
) -> tuple[list[Finding], set[str], set[str]]:
    """
    Heuristic: if a consumer field is missing from the producer but a producer
    field of the same type is missing from the consumer, treat it as a rename.

    Returns (findings, renamed_consumer_fields, renamed_producer_fields).
    """
    findings: list[Finding] = []
    renamed_consumer: set[str] = set()
    renamed_producer: set[str] = set()

    # Only consider top-level fields for rename detection to keep it simple
    consumer_missing = {
        k for k in consumer_props if k not in producer_props and "." not in k
    }
    producer_new = {
        k for k in producer_props if k not in consumer_props and "." not in k
    }

    for c_field in list(consumer_missing):
        c_type = consumer_props[c_field].get("type")
        candidates = [
            p for p in producer_new
            if producer_props[p].get("type") == c_type
            and p not in renamed_producer
        ]
        if len(candidates) == 1:
            p_field = candidates[0]
            findings.append(
                Finding(
                    endpoint=endpoint,
                    affected_field=c_field,
                    change_kind=ChangeKind.FIELD_RENAMED,
                    detail=(
                        f"Consumer expects '{c_field}' but producer now uses "
                        f"'{p_field}' (same type '{c_type}')."
                    ),
                )
            )
            renamed_consumer.add(c_field)
            renamed_producer.add(p_field)

    return findings, renamed_consumer, renamed_producer


# ---------------------------------------------------------------------------
# All rules together
# ---------------------------------------------------------------------------

ALL_RULES = [
    check_removed_fields,
    check_type_changes,
    check_required_added,
    check_optional_added,
]
