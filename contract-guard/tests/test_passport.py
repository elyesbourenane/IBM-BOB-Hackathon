"""
Tests for ContractGuard Phase 3C — Change Passport / Unified Impact Report.

Validates:
- Generation of deterministic ChangePassport unifying semantic change, blast radius,
  dependency graph, repair mission, SemVer, and release verification.
- Deterministic passport_id generation across runs.
- JSON, Markdown, and Text formatters.
- CLI command: contract-guard passport <workspace_root> --format {text,json,markdown}.
- Passport reflects post-repair READY state.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from contract_guard.discovery import discover_and_check
from contract_guard.evidence import evaluate_release_gate, generate_evidence
from contract_guard.passport import ChangePassport, generate_change_passport


def _init_git(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "ContractGuard Tester"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@contractguard.dev"], cwd=path, check=True, capture_output=True)


@pytest.fixture
def breaking_workspace(tmp_path: Path) -> Path:
    """
    Workspace with paymentAmount renamed to totalAmount in producer.
    2 consumers expecting paymentAmount.
    """
    ws = tmp_path / "breaking_ws"
    ws.mkdir()
    _init_git(ws)

    # Producer
    prod_dir = ws / "payment-service" / "docs"
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
                          - totalAmount
                        properties:
                          id: { type: string }
                          totalAmount: { type: number }
        """).strip(),
        encoding="utf-8",
    )

    # Consumer 1: order-service
    c1 = ws / "order-service"
    (c1 / "contracts").mkdir(parents=True)
    (c1 / "contracts" / "payment-service.yaml").write_text(
        textwrap.dedent("""
        openapi: "3.1.0"
        info:
          title: Payment Service (Consumer Contract)
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
        """).strip(),
        encoding="utf-8",
    )
    (c1 / "contractguard.yaml").write_text(
        textwrap.dedent("""
        service: order-service
        dependencies:
          - service: payment-service
            consumer_contract: contracts/payment-service.yaml
            producer_contract: ../payment-service/docs/openapi.yaml
        """).strip(),
        encoding="utf-8",
    )

    # Consumer 2: payment-client with source and tests
    c2 = ws / "payment-client"
    (c2 / "contracts").mkdir(parents=True)
    (c2 / "contracts" / "payment-service.yaml").write_text(
        textwrap.dedent("""
        openapi: "3.1.0"
        info:
          title: Payment Service (Consumer Contract)
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
        """).strip(),
        encoding="utf-8",
    )
    (c2 / "contractguard.yaml").write_text(
        textwrap.dedent("""
        service: payment-client
        dependencies:
          - service: payment-service
            consumer_contract: contracts/payment-service.yaml
            producer_contract: ../payment-service/docs/openapi.yaml
        """).strip(),
        encoding="utf-8",
    )
    src_dir = c2 / "src" / "main" / "java"
    src_dir.mkdir(parents=True)
    (src_dir / "PaymentDto.java").write_text(
        "public class PaymentDto { private Double paymentAmount; }",
        encoding="utf-8",
    )
    test_dir = c2 / "src" / "test" / "java"
    test_dir.mkdir(parents=True)
    (test_dir / "PaymentDtoTest.java").write_text(
        "public class PaymentDtoTest { void testAmount() { dto.getPaymentAmount(); } }",
        encoding="utf-8",
    )

    return ws


def test_generate_passport_breaking(breaking_workspace: Path):
    passport = generate_change_passport(str(breaking_workspace), producer_filter="payment-service")

    assert passport.passport_id.startswith("passport-payment-service-")
    assert passport.producer == "payment-service"
    assert passport.release_status == "BLOCKED"
    assert passport.semver.get("recommendation") == "MAJOR"
    assert passport.impact.get("affected_consumers") == 2
    assert len(passport.impact.get("confirmed_source_files")) == 1
    assert len(passport.impact.get("confirmed_test_files")) == 1
    assert passport.verification.get("breaking_findings") == 2
    assert passport.repair_mission is not None
    assert passport.dependency_graph is not None

    # Evidence ID assertions
    assert passport.evidence_id is not None
    assert passport.evidence_id.startswith("cg-ev-")

    # Test JSON output
    data = json.loads(passport.to_json())
    assert data["passport_id"] == passport.passport_id
    assert data["release_status"] == "BLOCKED"
    assert data["impact"]["affected_consumers"] == 2
    assert data["evidence_id"] == passport.evidence_id

    # Test Markdown formatting
    md = passport.format_markdown()
    assert "CONTRACTGUARD CHANGE PASSPORT" in md
    assert "payment-service" in md
    assert "BLOCKED" in md
    assert passport.evidence_id in md

    # Test Text formatting
    txt = passport.format_text()
    assert "CHANGE PASSPORT" in txt
    assert "BLOCKED" in txt
    assert passport.evidence_id in txt


def test_passport_deterministic_id(breaking_workspace: Path):
    p1 = generate_change_passport(str(breaking_workspace), producer_filter="payment-service")
    p2 = generate_change_passport(str(breaking_workspace), producer_filter="payment-service")
    assert p1.passport_id == p2.passport_id


def test_passport_evidence_id_deterministic(breaking_workspace: Path):
    p1 = generate_change_passport(str(breaking_workspace), producer_filter="payment-service")
    p2 = generate_change_passport(str(breaking_workspace), producer_filter="payment-service")
    assert p1.evidence_id == p2.evidence_id
    assert p1.evidence_id.startswith("cg-ev-")


def test_passport_evidence_id_consistency_with_generate_evidence(breaking_workspace: Path):
    passport = generate_change_passport(str(breaking_workspace), producer_filter="payment-service")

    report = discover_and_check(str(breaking_workspace), producer_filter="payment-service")
    verification = evaluate_release_gate(
        report=report,
        producer_service="payment-service",
        test_results={"status": "PASS", "details": "Automated tests: PASS"},
    )
    direct_evidence = generate_evidence(
        report=report,
        verification=verification,
    )

    assert passport.evidence_id == direct_evidence.evidence_id


def test_cli_passport_text(breaking_workspace: Path):
    res = subprocess.run(
        [sys.executable, "-m", "contract_guard", "passport", str(breaking_workspace)],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 1  # BLOCKED -> exit 1
    assert "CHANGE PASSPORT" in res.stdout
    assert "BLOCKED" in res.stdout


def test_cli_passport_json(breaking_workspace: Path):
    res = subprocess.run(
        [sys.executable, "-m", "contract_guard", "passport", str(breaking_workspace), "--format", "json"],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 1
    data = json.loads(res.stdout)
    assert data["release_status"] == "BLOCKED"
    assert data["producer"] == "payment-service"
    assert data["evidence_id"].startswith("cg-ev-")


def test_cli_passport_markdown(breaking_workspace: Path):
    res = subprocess.run(
        [sys.executable, "-m", "contract_guard", "passport", str(breaking_workspace), "--format", "markdown"],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 1
    assert "CONTRACTGUARD CHANGE PASSPORT" in res.stdout


def test_cli_passport_matches_cli_evidence(breaking_workspace: Path, tmp_path: Path):
    res_pass = subprocess.run(
        [sys.executable, "-m", "contract_guard", "passport", str(breaking_workspace), "--format", "json"],
        capture_output=True,
        text=True,
    )
    passport_data = json.loads(res_pass.stdout)

    ev_dir = tmp_path / "ev_out"
    res_ev = subprocess.run(
        [
            sys.executable,
            "-m",
            "contract_guard",
            "evidence",
            str(breaking_workspace),
            "--producer",
            "payment-service",
            "--output-dir",
            str(ev_dir),
        ],
        capture_output=True,
        text=True,
    )
    ev_data = json.loads((ev_dir / "contractguard-evidence.json").read_text(encoding="utf-8"))
    assert passport_data["evidence_id"] == ev_data["evidence_id"]
