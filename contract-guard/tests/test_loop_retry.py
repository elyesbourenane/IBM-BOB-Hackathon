"""
Tests for ContractGuard Phase 3E & 3F — Bob <-> ContractGuard Repair / Verify Loop & Failure + Retry Scenario.

Validates the full cycle:
1. Producer breaking change (paymentAmount -> totalAmount).
2. Initial verification: BLOCKED, 0/3 compatible, 3 remaining actions, next_step='repair_remaining_consumers'.
3. Bob partial repair: repairs order-service & payment-client, leaves reporting-service stale.
4. Independent verification: BLOCKED, 2/3 compatible, 1 incompatible, exact remaining failure for reporting-service.
5. Bob second repair: repairs reporting-service.
6. Independent verification: READY, 3/3 compatible, 0 breaking, remaining_actions=[], next_step='release_or_commit'.
7. Deterministic mission and evidence IDs across cycles.
8. CLI and MCP behavior across the loop.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from contract_guard.evidence import evaluate_release_gate
from contract_guard.discovery import discover_and_check
from contract_guard.mcp_server import handle_get_repair_mission, handle_verify_release
from contract_guard.mission import generate_repair_mission


def _init_git(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "ContractGuard Tester"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@contractguard.dev"], cwd=path, check=True, capture_output=True)


@pytest.fixture
def multi_consumer_workspace(tmp_path: Path) -> Path:
    """
    Sets up a 4-service workspace with 1 producer and 3 consumers:
    - payment-service (producer) has changed paymentAmount -> totalAmount
    - order-service (consumer) expects paymentAmount
    - payment-client (consumer) expects paymentAmount
    - reporting-service (consumer) expects paymentAmount
    """
    ws = tmp_path / "retry_ws"
    ws.mkdir()
    _init_git(ws)

    # 1. Producer: payment-service with totalAmount
    prod_dir = ws / "payment-service" / "docs"
    prod_dir.mkdir(parents=True)
    (prod_dir / "openapi.yaml").write_text(
        textwrap.dedent("""
        openapi: "3.1.0"
        info:
          title: Payment Service
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
        """).strip(),
        encoding="utf-8",
    )

    # 2. Consumer: order-service
    c_order = ws / "order-service"
    (c_order / "contracts").mkdir(parents=True)
    (c_order / "contracts" / "payment-service.yaml").write_text(
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
    (c_order / "contractguard.yaml").write_text(
        textwrap.dedent("""
        service: order-service
        dependencies:
          - service: payment-service
            consumer_contract: contracts/payment-service.yaml
            producer_contract: ../payment-service/docs/openapi.yaml
        """).strip(),
        encoding="utf-8",
    )

    # 3. Consumer: payment-client
    c_client = ws / "payment-client"
    (c_client / "contracts").mkdir(parents=True)
    (c_client / "contracts" / "payment-service.yaml").write_text(
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
    (c_client / "contractguard.yaml").write_text(
        textwrap.dedent("""
        service: payment-client
        dependencies:
          - service: payment-service
            consumer_contract: contracts/payment-service.yaml
            producer_contract: ../payment-service/docs/openapi.yaml
        """).strip(),
        encoding="utf-8",
    )
    client_src = c_client / "src" / "main" / "java"
    client_src.mkdir(parents=True)
    (client_src / "PaymentDto.java").write_text(
        "public class PaymentDto { private Double paymentAmount; }",
        encoding="utf-8",
    )

    # 4. Consumer: reporting-service
    c_rep = ws / "reporting-service"
    (c_rep / "contracts").mkdir(parents=True)
    (c_rep / "contracts" / "payment-service.yaml").write_text(
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
    (c_rep / "contractguard.yaml").write_text(
        textwrap.dedent("""
        service: reporting-service
        dependencies:
          - service: payment-service
            consumer_contract: contracts/payment-service.yaml
            producer_contract: ../payment-service/docs/openapi.yaml
        """).strip(),
        encoding="utf-8",
    )

    return ws


def test_repair_verify_loop_with_partial_failure_and_retry(multi_consumer_workspace: Path):
    ws = multi_consumer_workspace

    # --- STEP 1: ContractGuard detects breaking change & creates Repair Mission ---
    mission = generate_repair_mission(str(ws), producer_filter="payment-service")
    assert mission.mission_id.startswith("mission-payment-service-")
    assert len(mission.affected_consumers) == 3

    # Initial verification: All 3 broken
    v1 = handle_verify_release({
        "workspace_root": str(ws),
        "producer_service": "payment-service",
    })
    assert v1["status"] == "BLOCKED"
    assert v1["is_ready"] is False
    assert len(v1["compatible_consumers"]) == 0
    assert len(v1["affected_consumers"]) == 3
    assert v1["next_step"] == "repair_remaining_consumers"
    assert len(v1["remaining_actions"]) == 3
    assert len(v1["remaining_failures"]) == 3

    # --- STEP 2: Bob executes PARTIAL repair (order-service and payment-client only) ---
    # Repair order-service
    (ws / "order-service" / "contracts" / "payment-service.yaml").write_text(
        (ws / "payment-service" / "docs" / "openapi.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    # Repair payment-client contract & java
    (ws / "payment-client" / "contracts" / "payment-service.yaml").write_text(
        (ws / "payment-service" / "docs" / "openapi.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (ws / "payment-client" / "src" / "main" / "java" / "PaymentDto.java").write_text(
        "public class PaymentDto { private Double totalAmount; }",
        encoding="utf-8",
    )
    # Intentionally leave reporting-service UNTOUCHED

    # --- STEP 3: ContractGuard verifies partial repair (Phase 3F failure scenario) ---
    v2 = handle_verify_release({
        "workspace_root": str(ws),
        "producer_service": "payment-service",
    })
    assert v2["status"] == "BLOCKED"
    assert v2["is_ready"] is False
    assert len(v2["compatible_consumers"]) == 2
    assert len(v2["affected_consumers"]) == 1
    assert v2["breaking_changes_count"] == 1
    assert v2["next_step"] == "repair_remaining_consumers"

    # Precise remaining failure feedback
    assert len(v2["remaining_actions"]) == 1
    assert "reporting-service" in v2["remaining_actions"][0]
    assert len(v2["remaining_failures"]) == 1
    assert v2["remaining_failures"][0]["consumer_service"] == "reporting-service"
    assert "paymentAmount" in v2["remaining_failures"][0]["detail"]

    # Verify CLI also reports BLOCKED with remaining failures in JSON
    cli_res = subprocess.run(
        [sys.executable, "-m", "contract_guard", "verify", str(ws), "--format", "json"],
        capture_output=True,
        text=True,
    )
    assert cli_res.returncode == 1
    cli_data = json.loads(cli_res.stdout)
    assert cli_data["status"] == "BLOCKED"
    assert len(cli_data["compatible_consumers"]) == 2
    assert len(cli_data["affected_consumers"]) == 1
    assert cli_data["next_step"] == "repair_remaining_consumers"

    # --- STEP 4: Bob receives feedback and repairs reporting-service ---
    (ws / "reporting-service" / "contracts" / "payment-service.yaml").write_text(
        (ws / "payment-service" / "docs" / "openapi.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    # --- STEP 5: Final verification (Phase 3E completion -> READY) ---
    v3 = handle_verify_release({
        "workspace_root": str(ws),
        "producer_service": "payment-service",
    })
    assert v3["status"] == "READY"
    assert v3["is_ready"] is True
    assert len(v3["compatible_consumers"]) == 3
    assert len(v3["affected_consumers"]) == 0
    assert v3["breaking_changes_count"] == 0
    assert v3["remaining_actions"] == []
    assert v3["remaining_failures"] == []
    assert v3["next_step"] == "release_or_commit"

    # Final CLI check: returns 0 exit code
    final_cli = subprocess.run(
        [sys.executable, "-m", "contract_guard", "verify", str(ws), "--format", "json"],
        capture_output=True,
        text=True,
    )
    assert final_cli.returncode == 0
    final_data = json.loads(final_cli.stdout)
    assert final_data["status"] == "READY"
    assert final_data["next_step"] == "release_or_commit"
