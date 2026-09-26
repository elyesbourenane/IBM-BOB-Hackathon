"""Tests for the SemVer recommendation engine."""

from __future__ import annotations

import pytest

from contract_guard.models import ChangeKind, Finding, Severity
from contract_guard.versioning import (
    bump_version,
    calculate_semver_recommendation,
    parse_semver,
)


def test_parse_semver():
    assert parse_semver("1.4.0") == (1, 4, 0)
    assert parse_semver("v2.1.3") == (2, 1, 3)
    assert parse_semver("0.1.0-alpha") == (0, 1, 0)
    assert parse_semver("1.0.0+build123") == (1, 0, 0)
    assert parse_semver("invalid") is None
    assert parse_semver("") is None
    assert parse_semver(None) is None


def test_bump_version():
    assert bump_version("1.4.0", "major") == "2.0.0"
    assert bump_version("1.4.0", "minor") == "1.5.0"
    assert bump_version("1.4.0", "patch") == "1.4.1"
    assert bump_version("1.4.0", "none") == "1.4.0"
    assert bump_version("invalid", "major") is None


def test_semver_breaking_recommends_major():
    findings = [
        Finding(
            endpoint="GET /payments/{id}",
            affected_field="paymentAmount",
            change_kind=ChangeKind.FIELD_RENAMED,
            detail="Renamed to totalAmount",
        )
    ]
    rec = calculate_semver_recommendation(findings, current_version="1.4.0")
    assert rec.bump == "major"
    assert rec.current_version == "1.4.0"
    assert rec.recommended_version == "2.0.0"
    assert "breaking" in rec.reason.lower()


def test_semver_compatible_addition_recommends_minor():
    findings = [
        Finding(
            endpoint="GET /payments/{id}",
            affected_field="note",
            change_kind=ChangeKind.FIELD_OPTIONAL_ADDED,
            detail="Added optional field",
        )
    ]
    rec = calculate_semver_recommendation(findings, current_version="1.4.0")
    assert rec.bump == "minor"
    assert rec.current_version == "1.4.0"
    assert rec.recommended_version == "1.5.0"
    assert "backward-compatible" in rec.reason.lower()


def test_semver_patch_when_contract_modified_no_differences():
    rec = calculate_semver_recommendation(findings=[], has_contract_changes=True, current_version="1.4.0")
    assert rec.bump == "patch"
    assert rec.current_version == "1.4.0"
    assert rec.recommended_version == "1.4.1"
    assert "metadata" in rec.reason.lower() or "contract modified" in rec.reason.lower()


def test_semver_none_when_no_changes():
    rec = calculate_semver_recommendation(findings=[], has_contract_changes=False, current_version="1.4.0")
    assert rec.bump == "none"
    assert rec.current_version == "1.4.0"
    assert rec.recommended_version == "1.4.0"
    assert "no api contract changes" in rec.reason.lower()


def test_semver_without_current_version_does_not_invent():
    # If no current version is provided, it must NOT invent one
    findings = [
        Finding(
            endpoint="GET /payments/{id}",
            affected_field="paymentAmount",
            change_kind=ChangeKind.FIELD_RENAMED,
            detail="Renamed to totalAmount",
        )
    ]
    rec = calculate_semver_recommendation(findings, current_version=None)
    assert rec.bump == "major"
    assert rec.current_version is None
    assert rec.recommended_version is None
    assert "breaking" in rec.reason.lower()


def test_semver_with_dict_findings():
    # Verify calculate_semver_recommendation works with serialized dict findings
    dict_findings = [
        {
            "endpoint": "GET /p",
            "affected_field": "x",
            "change_kind": "field_removed",
            "severity": "breaking",
            "detail": "Field removed",
        }
    ]
    rec = calculate_semver_recommendation(dict_findings, current_version="3.2.1")
    assert rec.bump == "major"
    assert rec.recommended_version == "4.0.0"
