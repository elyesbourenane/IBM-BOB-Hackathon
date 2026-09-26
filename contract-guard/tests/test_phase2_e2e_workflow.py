"""
End-to-End Integration Test for Phase 2:
Verifies the complete Git-aware PR and change safety workflow:
    Producer Contract Change (paymentAmount -> totalAmount)
        ↓
    Git Change Detection
        ↓
    ContractGuard PR Analysis
        ↓
    Consumer Discovery (3 consumers)
        ↓
    Deterministic Breaking Compatibility Analysis (field_renamed)
        ↓
    Blast Radius Calculation (3 affected consumers)
        ↓
    SemVer Recommendation (MAJOR: 1.4.0 -> 2.0.0)
        ↓
    Release Verdict BLOCKED (exit code 1)
        ↓
    Machine-readable JSON & PR-ready Markdown
        ↓
    Evidence enriched with Git metadata
        ↓
    Bob repairs affected consumers
        ↓
    ContractGuard PR re-analysis
        ↓
    Verdict READY (exit code 0)
        ↓
    MCP analyze_git_change verification
"""

from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path

import pytest

from contract_guard.git import get_current_sha, inspect_git_status
from contract_guard.mcp_server import handle_analyze_git_change
from contract_guard.pr import analyze_pr


def _init_git(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "ContractGuard Tester"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@contractguard.dev"], cwd=path, check=True, capture_output=True)


def test_phase2_full_git_pr_workflow(tmp_path: Path):
    # =========================================================================
    # Step 1: Set up Multi-Repo Git Workspace Baseline
    # =========================================================================
    repo = tmp_path / "workspace"
    repo.mkdir()
    _init_git(repo)

    # Producer: payment-service
    prod_dir = repo / "payment-service" / "docs"
    prod_dir.mkdir(parents=True)
    prod_contract = prod_dir / "openapi.yaml"
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
        """).lstrip(),
        encoding="utf-8",
    )

    # Consumers: payment-client, order-service, reporting-service
    consumers = ["payment-client", "order-service", "reporting-service"]
    consumer_contracts: dict[str, Path] = {}

    for c in consumers:
        c_dir = repo / c
        c_contracts = c_dir / "contracts"
        c_contracts.mkdir(parents=True)
        c_contract = c_contracts / "payment-service.yaml"
        c_contract.write_text(
            textwrap.dedent("""
            openapi: "3.1.0"
            info:
              title: Consumer Contract
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
            """).lstrip(),
            encoding="utf-8",
        )
        consumer_contracts[c] = c_contract
        (c_dir / "contractguard.yaml").write_text(
            f"service: {c}\ndependencies:\n  - service: payment-service\n    consumer_contract: contracts/payment-service.yaml\n    producer_contract: ../payment-service/docs/openapi.yaml\n",
            encoding="utf-8",
        )

    # Commit baseline
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Baseline API 1.4.0"], cwd=repo, check=True, capture_output=True)
    base_sha = get_current_sha(repo)
    assert base_sha is not None

    # Baseline PR analysis should be READY
    baseline_pr = analyze_pr(repo, base_ref=base_sha)
    assert baseline_pr.is_ready is True
    assert baseline_pr.verdict == "READY"
    assert len(baseline_pr.consumers_checked) == 3
    assert len(baseline_pr.affected_consumers) == 0

    # =========================================================================
    # Step 2: Developer makes breaking contract change (paymentAmount -> totalAmount)
    # =========================================================================
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
        """).lstrip(),
        encoding="utf-8",
    )

    # =========================================================================
    # Step 3: Git detects changed contracts
    # =========================================================================
    status = inspect_git_status(repo)
    assert status.is_repo is True
    assert len(status.changed_contracts) == 1
    assert "payment-service/docs/openapi.yaml" in status.changed_contracts[0].replace("\\", "/")

    # =========================================================================
    # Step 4: ContractGuard PR Analysis executes deterministically
    # =========================================================================
    pr_blocked = analyze_pr(repo, base_ref=base_sha)

    # 4.1 Verdict and counts
    assert pr_blocked.is_ready is False
    assert pr_blocked.verdict == "BLOCKED"
    assert len(pr_blocked.consumers_checked) == 3
    assert len(pr_blocked.compatible_consumers) == 0
    assert len(pr_blocked.affected_consumers) == 3
    assert set(pr_blocked.affected_consumers) == {"payment-client", "order-service", "reporting-service"}

    # 4.2 Breaking findings
    assert len(pr_blocked.breaking_findings) == 3
    first_finding = pr_blocked.breaking_findings[0]
    assert first_finding["endpoint"] == "GET /api/payments/{id}"
    assert first_finding["change_kind"] == "field_renamed"

    # 4.3 SemVer recommendation: MAJOR
    assert pr_blocked.semver.bump == "major"
    assert pr_blocked.semver.current_version == "1.4.0"
    assert pr_blocked.semver.recommended_version == "2.0.0"

    # 4.4 Machine-readable JSON output
    json_data = json.loads(pr_blocked.to_json())
    assert json_data["verdict"] == "BLOCKED"
    assert json_data["consumers_checked"] == 3
    assert json_data["affected_consumers"] == 3
    assert json_data["semver"]["bump"] == "major"
    assert json_data["semver"]["recommended_version"] == "2.0.0"
    assert json_data["evidence_id"].startswith("cg-ev-")

    # 4.5 PR-ready Markdown output
    md_output = pr_blocked.to_markdown()
    assert "# ContractGuard PR Analysis" in md_output
    assert "**Verdict:** `BLOCKED`" in md_output
    assert "### GET /api/payments/{id}" in md_output
    assert "`field_renamed`" in md_output
    assert "**MAJOR**" in md_output
    assert "`1.4.0 -> 2.0.0`" in md_output
    assert pr_blocked.evidence_id in md_output

    # 4.6 MCP analyze_git_change tool validation
    mcp_result = handle_analyze_git_change({
        "workspace_root": str(repo),
        "base_ref": base_sha,
    })
    assert mcp_result["verdict"] == "BLOCKED"
    assert mcp_result["affected_consumers"] == 3
    assert mcp_result["semver"]["bump"] == "major"

    # =========================================================================
    # Step 5: Bob repairs affected consumers
    # =========================================================================
    for c, c_contract in consumer_contracts.items():
        c_contract.write_text(
            textwrap.dedent("""
            openapi: "3.1.0"
            info:
              title: Consumer Contract
              version: "2.0.0"
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
            """).lstrip(),
            encoding="utf-8",
        )

    # =========================================================================
    # Step 6: Deterministic Re-analysis: PR is now READY
    # =========================================================================
    pr_repaired = analyze_pr(repo, base_ref=base_sha)
    assert pr_repaired.is_ready is True
    assert pr_repaired.verdict == "READY"
    assert len(pr_repaired.consumers_checked) == 3
    assert len(pr_repaired.compatible_consumers) == 3
    assert len(pr_repaired.affected_consumers) == 0
    assert len(pr_repaired.breaking_findings) == 0

    # SemVer MUST remain MAJOR because the producer contract change is breaking
    assert pr_repaired.semver.bump == "major"
    assert pr_repaired.semver.recommended_version == "2.0.0"
    assert "Producer contract contains a breaking change, but all discovered consumers are compatible." in pr_repaired.semver.reason

    # Evidence ID is deterministically regenerated
    assert pr_repaired.evidence_id.startswith("cg-ev-")

    # MCP tool also confirms READY with MAJOR bump
    mcp_repaired = handle_analyze_git_change({
        "workspace_root": str(repo),
        "base_ref": base_sha,
    })
    assert mcp_repaired["verdict"] == "READY"
    assert mcp_repaired["affected_consumers"] == 0
    assert mcp_repaired["semver"]["bump"] == "major"
    assert mcp_repaired["semver"]["recommended_version"] == "2.0.0"
