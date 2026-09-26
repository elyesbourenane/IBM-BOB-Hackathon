"""Tests for release safety gate and evidence generation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from contract_guard.discovery import DiscoveryReport
from contract_guard.evidence import (
    EvidenceReport,
    ReleaseStatus,
    evaluate_release_gate,
    generate_evidence,
)


def _make_discovery_report(affected: bool = False) -> DiscoveryReport:
    if affected:
        return DiscoveryReport(
            workspace_root="/workspace",
            producer_filter=None,
            configs_found=3,
            consumers_checked=["payment-client", "order-service", "reporting-service"],
            compatible_consumers=[],
            affected_consumers=["payment-client", "order-service", "reporting-service"],
            results=[],
            breaking_findings=[
                {
                    "consumer_service": "payment-client",
                    "producer_service": "payment-service",
                    "endpoint": "GET /api/payments/{id}",
                    "affected_field": "paymentAmount",
                    "change_kind": "field_renamed",
                    "severity": "breaking",
                    "detail": "Renamed to totalAmount",
                    "reason": "Consumer depends on field",
                }
            ],
        )
    return DiscoveryReport(
        workspace_root="/workspace",
        producer_filter=None,
        configs_found=3,
        consumers_checked=["payment-client", "order-service", "reporting-service"],
        compatible_consumers=["payment-client", "order-service", "reporting-service"],
        affected_consumers=[],
        results=[],
        breaking_findings=[],
    )


def test_release_gate_blocked_when_contracts_broken():
    report = _make_discovery_report(affected=True)
    # Even if tests pass (mock tests are green), gate is BLOCKED!
    verification = evaluate_release_gate(
        report,
        producer_service="payment-service",
        test_results={"status": "PASS", "details": "4/4 tests passed"},
    )
    assert verification.status == ReleaseStatus.BLOCKED
    assert not verification.is_ready
    assert verification.contract_checks_status == "FAIL"
    assert any("incompatible" in r.lower() for r in verification.reasons)


def test_release_gate_ready_when_contracts_compatible_and_tests_pass():
    report = _make_discovery_report(affected=False)
    verification = evaluate_release_gate(
        report,
        producer_service="payment-service",
        test_results={"status": "PASS", "details": "4/4 tests passed"},
    )
    assert verification.status == ReleaseStatus.READY
    assert verification.is_ready
    assert verification.contract_checks_status == "PASS"


def test_release_gate_blocked_when_tests_fail_even_if_contracts_pass():
    report = _make_discovery_report(affected=False)
    verification = evaluate_release_gate(
        report,
        producer_service="payment-service",
        test_results={"status": "FAIL", "detail": "AssertionError in payment test"},
    )
    assert verification.status == ReleaseStatus.BLOCKED
    assert not verification.is_ready
    assert any("failed" in r.lower() for r in verification.reasons)


def test_evidence_stable_hash():
    report = _make_discovery_report(affected=True)
    verification = evaluate_release_gate(report)

    ev1 = generate_evidence(report, verification)
    ev2 = generate_evidence(report, verification)
    assert ev1.evidence_id == ev2.evidence_id
    assert ev1.evidence_id.startswith("cg-ev-")

    # Modify findings to verify hash changes
    report_clean = _make_discovery_report(affected=False)
    verification_clean = evaluate_release_gate(report_clean)
    ev3 = generate_evidence(report_clean, verification_clean)
    assert ev3.evidence_id != ev1.evidence_id


def test_evidence_file_generation_and_no_secrets(tmp_path: Path):
    report = _make_discovery_report(affected=True)
    verification = evaluate_release_gate(report)

    evidence = generate_evidence(report, verification, output_dir=tmp_path)
    json_path = tmp_path / "contractguard-evidence.json"
    md_path = tmp_path / "contractguard-report.md"

    assert json_path.exists()
    assert md_path.exists()

    json_content = json_path.read_text(encoding="utf-8")
    md_content = md_path.read_text(encoding="utf-8")

    assert evidence.evidence_id in json_content
    assert evidence.evidence_id in md_content
    assert "payment-client" in json_content
    assert "paymentAmount" in md_content
    assert "[BLOCKED] RELEASE BLOCKED" in md_content

    # Security check: verify no API key or token leaks
    assert "MISTRAL_API_KEY" not in json_content
    assert "Bearer" not in json_content
    assert "password" not in json_content.lower()


def test_evidence_hash_canonical_sorting_stability():
    """Verify that reversing or reordering findings produces the exact same evidence hash."""
    f1 = {
        "consumer_service": "payment-client",
        "producer_service": "payment-service",
        "endpoint": "GET /api/payments/{id}",
        "affected_field": "paymentAmount",
        "change_kind": "field_renamed",
        "severity": "breaking",
        "detail": "Renamed to totalAmount",
        "reason": "Consumer depends on field",
    }
    f2 = {
        "consumer_service": "order-service",
        "producer_service": "payment-service",
        "endpoint": "POST /api/payments",
        "affected_field": "amount",
        "change_kind": "field_removed",
        "severity": "breaking",
        "detail": "Field removed",
        "reason": "Consumer depends on field",
    }

    report1 = DiscoveryReport(
        workspace_root="/workspace",
        producer_filter=None,
        configs_found=2,
        consumers_checked=["payment-client", "order-service"],
        compatible_consumers=[],
        affected_consumers=["payment-client", "order-service"],
        results=[],
        breaking_findings=[f1, f2],
    )
    report2 = DiscoveryReport(
        workspace_root="/workspace",
        producer_filter=None,
        configs_found=2,
        consumers_checked=["order-service", "payment-client"],
        compatible_consumers=[],
        affected_consumers=["order-service", "payment-client"],
        results=[],
        breaking_findings=[f2, f1],  # reversed order
    )

    ev1 = generate_evidence(report1, evaluate_release_gate(report1))
    ev2 = generate_evidence(report2, evaluate_release_gate(report2))

    assert ev1.evidence_id == ev2.evidence_id


def test_evidence_git_and_semver_enrichment(tmp_path: Path):
    report = _make_discovery_report(affected=False)
    verification = evaluate_release_gate(report)

    evidence = generate_evidence(
        report,
        verification,
        output_dir=tmp_path,
        commit_sha="1234567890abcdef1234567890abcdef12345678",
        base_ref="origin/main",
        repository_path="/workspace/my-repo",
        semver={"bump": "minor", "current_version": "1.4.0", "recommended_version": "1.5.0", "reason": "Added field"},
    )

    assert evidence.commit_sha == "1234567890abcdef1234567890abcdef12345678"
    assert evidence.base_ref == "origin/main"
    assert evidence.semver["bump"] == "minor"
    assert evidence.evidence_id.startswith("cg-ev-")

    data = evidence.to_dict()
    assert data["commit_sha"] == "1234567890abcdef1234567890abcdef12345678"
    assert data["base_ref"] == "origin/main"
    assert data["semver"]["recommended_version"] == "1.5.0"

    md = evidence.to_markdown()
    assert "1234567890abcdef1234567890abcdef12345678" in md
    assert "origin/main" in md
    assert "MINOR" in md


