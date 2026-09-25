"""Tests for the compatibility rules engine."""

from __future__ import annotations

import pytest

from contract_guard.models import ChangeKind, Severity
from contract_guard.rules import (
    check_optional_added,
    check_removed_fields,
    check_required_added,
    check_type_changes,
    _detect_renames,
)

ENDPOINT = "GET /payments/{id}"


# ---------------------------------------------------------------------------
# check_removed_fields
# ---------------------------------------------------------------------------


class TestRemovedFields:
    def test_missing_field_is_breaking(self):
        producer = {"currency": {"type": "string", "_required": True}}
        consumer = {
            "amount": {"type": "number", "_required": True},
            "currency": {"type": "string", "_required": True},
        }
        findings = check_removed_fields(producer, consumer, ENDPOINT)
        assert len(findings) == 1
        f = findings[0]
        assert f.change_kind == ChangeKind.FIELD_REMOVED
        assert f.affected_field == "amount"
        assert f.is_breaking is True
        assert f.severity == Severity.BREAKING

    def test_no_removal_when_all_present(self):
        props = {"amount": {"type": "number", "_required": True}}
        findings = check_removed_fields(props, props, ENDPOINT)
        assert findings == []

    def test_multiple_missing_fields(self):
        producer = {}
        consumer = {
            "a": {"type": "string", "_required": False},
            "b": {"type": "number", "_required": True},
        }
        findings = check_removed_fields(producer, consumer, ENDPOINT)
        assert len(findings) == 2
        kinds = {f.change_kind for f in findings}
        assert kinds == {ChangeKind.FIELD_REMOVED}


# ---------------------------------------------------------------------------
# check_type_changes
# ---------------------------------------------------------------------------


class TestTypeChanges:
    def test_type_change_is_breaking(self):
        producer = {"amount": {"type": "string", "_required": True}}
        consumer = {"amount": {"type": "number", "_required": True}}
        findings = check_type_changes(producer, consumer, ENDPOINT)
        assert len(findings) == 1
        f = findings[0]
        assert f.change_kind == ChangeKind.FIELD_TYPE_CHANGED
        assert f.affected_field == "amount"
        assert f.is_breaking is True

    def test_same_type_no_finding(self):
        props = {"amount": {"type": "number", "_required": True}}
        findings = check_type_changes(props, props, ENDPOINT)
        assert findings == []

    def test_missing_type_in_producer_skipped(self):
        producer = {"amount": {"_required": True}}  # no type
        consumer = {"amount": {"type": "number", "_required": True}}
        findings = check_type_changes(producer, consumer, ENDPOINT)
        assert findings == []

    def test_missing_type_in_consumer_skipped(self):
        producer = {"amount": {"type": "number", "_required": True}}
        consumer = {"amount": {"_required": True}}  # no type
        findings = check_type_changes(producer, consumer, ENDPOINT)
        assert findings == []


# ---------------------------------------------------------------------------
# check_required_added
# ---------------------------------------------------------------------------


class TestRequiredAdded:
    def test_newly_required_field_is_breaking(self):
        producer = {"status": {"type": "string", "_required": True}}
        consumer = {"status": {"type": "string", "_required": False}}
        findings = check_required_added(producer, consumer, ENDPOINT)
        assert len(findings) == 1
        f = findings[0]
        assert f.change_kind == ChangeKind.FIELD_REQUIRED_ADDED
        assert f.is_breaking is True

    def test_both_required_no_finding(self):
        props = {"status": {"type": "string", "_required": True}}
        findings = check_required_added(props, props, ENDPOINT)
        assert findings == []

    def test_producer_optional_consumer_required_no_finding(self):
        # Producer relaxes a required field — not a breaking change from required perspective
        producer = {"status": {"type": "string", "_required": False}}
        consumer = {"status": {"type": "string", "_required": True}}
        findings = check_required_added(producer, consumer, ENDPOINT)
        assert findings == []


# ---------------------------------------------------------------------------
# check_optional_added
# ---------------------------------------------------------------------------


class TestOptionalAdded:
    def test_new_optional_field_is_compatible(self):
        producer = {
            "amount": {"type": "number", "_required": True},
            "transactionId": {"type": "string", "_required": False},
        }
        consumer = {"amount": {"type": "number", "_required": True}}
        findings = check_optional_added(producer, consumer, ENDPOINT)
        assert len(findings) == 1
        f = findings[0]
        assert f.change_kind == ChangeKind.FIELD_OPTIONAL_ADDED
        assert f.affected_field == "transactionId"
        assert f.is_breaking is False
        assert f.severity == Severity.COMPATIBLE

    def test_new_required_field_not_flagged_as_optional_added(self):
        # Required new field in producer — not the consumer's field — should NOT
        # be flagged as optional_added (it shows up as removed from consumer's view)
        producer = {
            "amount": {"type": "number", "_required": True},
            "mandatoryNew": {"type": "string", "_required": True},
        }
        consumer = {"amount": {"type": "number", "_required": True}}
        findings = check_optional_added(producer, consumer, ENDPOINT)
        assert findings == []

    def test_no_new_fields_no_finding(self):
        props = {"amount": {"type": "number", "_required": True}}
        findings = check_optional_added(props, props, ENDPOINT)
        assert findings == []


# ---------------------------------------------------------------------------
# Rename detection
# ---------------------------------------------------------------------------


class TestRenameDetection:
    def test_rename_detected(self):
        producer = {"paymentAmount": {"type": "number", "_required": True}}
        consumer = {"amount": {"type": "number", "_required": True}}
        findings, renamed_c, renamed_p = _detect_renames(producer, consumer, ENDPOINT)
        assert len(findings) == 1
        f = findings[0]
        assert f.change_kind == ChangeKind.FIELD_RENAMED
        assert f.affected_field == "amount"
        assert "paymentAmount" in f.detail
        assert f.is_breaking is True
        assert "amount" in renamed_c
        assert "paymentAmount" in renamed_p

    def test_ambiguous_rename_not_detected(self):
        # Two producer fields of same type — can't determine which is the rename
        producer = {
            "paymentAmount": {"type": "number", "_required": True},
            "totalAmount": {"type": "number", "_required": True},
        }
        consumer = {"amount": {"type": "number", "_required": True}}
        findings, _, _ = _detect_renames(producer, consumer, ENDPOINT)
        assert findings == []

    def test_no_rename_when_type_differs(self):
        producer = {"paymentAmount": {"type": "string", "_required": True}}
        consumer = {"amount": {"type": "number", "_required": True}}
        findings, _, _ = _detect_renames(producer, consumer, ENDPOINT)
        assert findings == []

    def test_no_rename_when_both_present(self):
        props = {"amount": {"type": "number", "_required": True}}
        findings, _, _ = _detect_renames(props, props, ENDPOINT)
        assert findings == []
