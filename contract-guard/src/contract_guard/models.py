"""Data models for contract compatibility results."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Severity(str, Enum):
    BREAKING = "breaking"
    COMPATIBLE = "compatible"


class ChangeKind(str, Enum):
    FIELD_REMOVED = "field_removed"
    FIELD_RENAMED = "field_renamed"
    FIELD_TYPE_CHANGED = "field_type_changed"
    FIELD_REQUIRED_ADDED = "field_required_added"
    FIELD_OPTIONAL_ADDED = "field_optional_added"


# Human-readable explanations for each change kind
_EXPLANATIONS: dict[ChangeKind, tuple[Severity, str]] = {
    ChangeKind.FIELD_REMOVED: (
        Severity.BREAKING,
        "Consumer depends on this field; removing it breaks existing clients.",
    ),
    ChangeKind.FIELD_RENAMED: (
        Severity.BREAKING,
        "Consumer expects the old field name; renaming it is equivalent to removal.",
    ),
    ChangeKind.FIELD_TYPE_CHANGED: (
        Severity.BREAKING,
        "Consumer parses this field with a specific type; changing it may corrupt data.",
    ),
    ChangeKind.FIELD_REQUIRED_ADDED: (
        Severity.BREAKING,
        "Making an optional field required forces consumers to always provide it.",
    ),
    ChangeKind.FIELD_OPTIONAL_ADDED: (
        Severity.COMPATIBLE,
        "New optional field does not break existing consumers that ignore unknown fields.",
    ),
}


@dataclass
class Finding:
    """A single detected difference between producer and consumer contracts."""

    endpoint: str          # e.g. "GET /payments/{id}"
    affected_field: str    # dot-separated path, e.g. "data.amount"
    change_kind: ChangeKind
    detail: str            # specific message, e.g. "producer uses 'paymentAmount'"

    @property
    def severity(self) -> Severity:
        return _EXPLANATIONS[self.change_kind][0]

    @property
    def reason(self) -> str:
        return _EXPLANATIONS[self.change_kind][1]

    @property
    def is_breaking(self) -> bool:
        return self.severity == Severity.BREAKING


@dataclass
class ComparisonReport:
    """Aggregated result of comparing two contracts."""

    findings: list[Finding] = field(default_factory=list)

    @property
    def is_compatible(self) -> bool:
        return not any(f.is_breaking for f in self.findings)

    @property
    def verdict(self) -> str:
        return "compatible" if self.is_compatible else "breaking"
