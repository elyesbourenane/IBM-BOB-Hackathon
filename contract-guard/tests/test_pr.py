"""Tests for Git-aware PR and change safety analysis."""

from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path

import pytest

from contract_guard.pr import analyze_pr


def _setup_git_workspace(tmp_path: Path) -> Path:
    """Create a temporary git workspace with producer and consumer."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True, capture_output=True)

    # 1. Producer service
    prod_dir = repo / "payment-service" / "docs"
    prod_dir.mkdir(parents=True)
    (prod_dir / "openapi.yaml").write_text(
        textwrap.dedent("""
        openapi: "3.1.0"
        info:
          title: Payment Service
          version: "1.4.0"
        paths:
          /api/payments/{id}:
            get:
              responses:
                "200":
                  content:
                    application/json:
                      schema:
                        type: object
                        required:
                          - id
                          - paymentAmount
                        properties:
                          id: { type: string }
                          paymentAmount: { type: number }
        """).lstrip("\n"),
        encoding="utf-8",
    )

    # 2. Consumer service
    client_dir = repo / "payment-client"
    client_dir.mkdir(parents=True)
    (client_dir / "contracts").mkdir()
    (client_dir / "contracts" / "payment-service.yaml").write_text(
        textwrap.dedent("""
        openapi: "3.1.0"
        info:
          title: Payment Client
          version: "1.0.0"
        paths:
          /api/payments/{id}:
            get:
              responses:
                "200":
                  content:
                    application/json:
                      schema:
                        type: object
                        required:
                          - id
                          - paymentAmount
                        properties:
                          id: { type: string }
                          paymentAmount: { type: number }
        """).lstrip("\n"),
        encoding="utf-8",
    )
    (client_dir / "contractguard.yaml").write_text(
        textwrap.dedent("""
        service: payment-client
        dependencies:
          - service: payment-service
            consumer_contract: contracts/payment-service.yaml
            producer_contract: ../payment-service/docs/openapi.yaml
        """).lstrip("\n"),
        encoding="utf-8",
    )

    # Initial commit
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Initial baseline"], cwd=repo, check=True, capture_output=True)
    return repo


def test_pr_analysis_clean_baseline(tmp_path: Path):
    repo = _setup_git_workspace(tmp_path)
    report = analyze_pr(repo)

    assert report.is_ready is True
    assert report.verdict == "READY"
    assert len(report.consumers_checked) == 1
    assert len(report.affected_consumers) == 0
    assert len(report.breaking_findings) == 0
    assert report.semver.bump == "none"
    assert report.evidence_id.startswith("cg-ev-")

    # Verify JSON structure
    data = json.loads(report.to_json())
    assert data["verdict"] == "READY"
    assert data["consumers_checked"] == 1
    assert data["affected_consumers"] == 0

    # Verify Markdown
    md = report.to_markdown()
    assert "# ContractGuard PR Analysis" in md
    assert "**Verdict:** `READY`" in md
    assert "NONE" in md


def test_pr_analysis_breaking_change_blocked(tmp_path: Path):
    repo = _setup_git_workspace(tmp_path)

    # Modify producer contract to rename paymentAmount -> totalAmount
    prod_contract = repo / "payment-service" / "docs" / "openapi.yaml"
    prod_contract.write_text(
        textwrap.dedent("""
        openapi: "3.1.0"
        info:
          title: Payment Service
          version: "1.4.0"
        paths:
          /api/payments/{id}:
            get:
              responses:
                "200":
                  content:
                    application/json:
                      schema:
                        type: object
                        required:
                          - id
                          - totalAmount
                        properties:
                          id: { type: string }
                          totalAmount: { type: number }
        """).lstrip("\n"),
        encoding="utf-8",
    )

    report = analyze_pr(repo)

    assert report.is_ready is False
    assert report.verdict == "BLOCKED"
    assert len(report.consumers_checked) == 1
    assert "payment-client" in report.affected_consumers
    assert len(report.breaking_findings) >= 1
    assert report.breaking_findings[0]["change_kind"] == "field_renamed"

    # SemVer must recommend MAJOR bump
    assert report.semver.bump == "major"
    assert report.semver.current_version == "1.4.0"
    assert report.semver.recommended_version == "2.0.0"

    # Markdown format checks
    md = report.to_markdown()
    assert "**Verdict:** `BLOCKED`" in md
    assert "### GET /api/payments/{id}" in md
    assert "field_renamed" in md
    assert "payment-client" in md
    assert "**MAJOR**" in md
    assert "`1.4.0 -> 2.0.0`" in md
    assert report.evidence_id in md


def test_pr_analysis_compatible_addition(tmp_path: Path):
    repo = _setup_git_workspace(tmp_path)

    # Add optional field to producer
    prod_contract = repo / "payment-service" / "docs" / "openapi.yaml"
    prod_contract.write_text(
        textwrap.dedent("""
        openapi: "3.1.0"
        info:
          title: Payment Service
          version: "1.4.0"
        paths:
          /api/payments/{id}:
            get:
              responses:
                "200":
                  content:
                    application/json:
                      schema:
                        type: object
                        required:
                          - id
                          - paymentAmount
                        properties:
                          id: { type: string }
                          paymentAmount: { type: number }
                          discountCode: { type: string }
        """).lstrip("\n"),
        encoding="utf-8",
    )

    report = analyze_pr(repo)

    assert report.is_ready is True
    assert report.verdict == "READY"
    assert len(report.affected_consumers) == 0
    assert report.semver.bump == "minor"
    assert report.semver.recommended_version == "1.5.0"


def test_pr_analysis_with_base_ref(tmp_path: Path):
    repo = _setup_git_workspace(tmp_path)
    base_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True).stdout.strip()

    # Create new branch
    subprocess.run(["git", "checkout", "-b", "feature/break"], cwd=repo, check=True, capture_output=True)

    # Break contract
    prod_contract = repo / "payment-service" / "docs" / "openapi.yaml"
    prod_contract.write_text(
        textwrap.dedent("""
        openapi: "3.1.0"
        info:
          title: Payment Service
          version: "1.4.0"
        paths:
          /api/payments/{id}:
            get:
              responses:
                "200":
                  content:
                    application/json:
                      schema:
                        type: object
                        required:
                          - id
                          - totalAmount
                        properties:
                          id: { type: string }
                          totalAmount: { type: number }
        """).lstrip("\n"),
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Breaking commit"], cwd=repo, check=True, capture_output=True)

    report = analyze_pr(repo, base_ref=base_sha)

    assert report.is_ready is False
    assert report.verdict == "BLOCKED"
    assert report.base == base_sha
    assert len(report.changed_contracts) == 1
    assert "openapi.yaml" in report.changed_contracts[0]


def test_pr_analysis_no_consumers(tmp_path: Path):
    empty_dir = tmp_path / "empty_dir"
    empty_dir.mkdir()
    report = analyze_pr(empty_dir)

    assert report.is_ready is True
    assert report.verdict == "READY"
    assert report.consumers_checked == []
    assert report.affected_consumers == []
