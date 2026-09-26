"""
Tests for ContractGuard Phase 3A Repair Mission.

Validates:
- Semantic change representation (rename, endpoint removal, additive compatible)
- Mission generation for multi-consumer workspace
- Confirmation of source/test files without inventing fake files
- Deterministic acceptance criteria and stable mission IDs
- CLI command: text, json, markdown formats and exit codes
- MCP tool: get_repair_mission success and error handling
- End-to-end workflow from breaking change to repair mission to resolution
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from contract_guard.mcp_server import _dispatch, handle_get_repair_mission
from contract_guard.mission import (
    AffectedConsumerMission,
    RepairMission,
    SemanticChange,
    create_semantic_change,
    generate_repair_mission,
)
from contract_guard.models import ChangeKind, Finding, Severity


# ---------------------------------------------------------------------------
# 1. Semantic Change Unit Tests
# ---------------------------------------------------------------------------

def test_semantic_change_field_rename():
    finding = Finding(
        endpoint="GET /api/payments/{id}",
        affected_field="paymentAmount",
        change_kind=ChangeKind.FIELD_RENAMED,
        detail="Consumer expects 'paymentAmount' but producer now uses 'totalAmount' (same type 'number').",
    )
    change = create_semantic_change(finding, producer_service="payment-service")

    assert change.producer_service == "payment-service"
    assert change.endpoint == "GET /api/payments/{id}"
    assert change.method == "GET"
    assert change.change_kind == "field_renamed"
    assert change.field == "paymentAmount"
    assert change.old_value == "paymentAmount"
    assert change.new_value == "totalAmount"
    assert change.compatibility == "breaking"
    assert "renaming" in change.reason.lower()


def test_semantic_change_endpoint_removal():
    finding = Finding(
        endpoint="DELETE /api/payments/{id}",
        affected_field="",
        change_kind=ChangeKind.ENDPOINT_REMOVED,
        detail="Endpoint 'DELETE /api/payments/{id}' is expected by consumer but is not present in producer specification.",
    )
    change = create_semantic_change(finding, producer_service="payment-service")

    assert change.endpoint == "DELETE /api/payments/{id}"
    assert change.method == "DELETE"
    assert change.change_kind == "endpoint_removed"
    assert change.old_value == "DELETE /api/payments/{id}"
    assert change.new_value is None
    assert change.compatibility == "breaking"


def test_semantic_change_additive_compatible():
    finding = Finding(
        endpoint="GET /api/payments/{id}",
        affected_field="notes",
        change_kind=ChangeKind.FIELD_OPTIONAL_ADDED,
        detail="Field 'notes' is new in the producer response and is optional - existing consumers are unaffected.",
    )
    change = create_semantic_change(finding, producer_service="payment-service")

    assert change.endpoint == "GET /api/payments/{id}"
    assert change.method == "GET"
    assert change.change_kind == "field_optional_added"
    assert change.field == "notes"
    assert change.old_value is None
    assert change.new_value == "notes"
    assert change.compatibility == "compatible"


def test_semantic_change_field_type_changed():
    finding = Finding(
        endpoint="GET /api/payments/{id}",
        affected_field="status",
        change_kind=ChangeKind.FIELD_TYPE_CHANGED,
        detail="Producer type is 'integer', consumer expects 'string'.",
    )
    change = create_semantic_change(finding, producer_service="payment-service")

    assert change.change_kind == "field_type_changed"
    assert change.old_value == "string"
    assert change.new_value == "integer"
    assert change.compatibility == "breaking"


def _init_git(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "ContractGuard Tester"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@contractguard.dev"], cwd=path, check=True, capture_output=True)


@pytest.fixture
def payment_workspace(tmp_path: Path) -> Path:
    """
    Sets up a 4-service Git workspace:
    - payment-service (producer) with paymentAmount -> totalAmount
    - payment-client (consumer) with Java source & tests
    - order-service (consumer) contract only
    - reporting-service (consumer) contract only
    """
    ws = tmp_path / "payment_workspace"
    ws.mkdir()
    _init_git(ws)

    # Producer: payment-service baseline with paymentAmount
    prod_dir = ws / "payment-service" / "docs"
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

    # Consumer 1: payment-client (has source and test files)
    pc_dir = ws / "payment-client"
    (pc_dir / "contracts").mkdir(parents=True)
    (pc_dir / "contracts" / "payment-service.yaml").write_text(
        textwrap.dedent("""
        openapi: "3.1.0"
        info:
          title: Payment Service Consumer
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
        """).lstrip(),
        encoding="utf-8",
    )
    (pc_dir / "contractguard.yaml").write_text(
        textwrap.dedent("""
        service: payment-client
        dependencies:
          - service: payment-service
            consumer_contract: contracts/payment-service.yaml
            producer_contract: ../payment-service/docs/openapi.yaml
        """).lstrip(),
        encoding="utf-8",
    )
    # Source file referencing paymentAmount
    src_main = pc_dir / "src" / "main" / "java"
    src_main.mkdir(parents=True)
    (src_main / "PaymentResponse.java").write_text(
        "public class PaymentResponse { private Double paymentAmount; public Double getPaymentAmount() { return paymentAmount; } }",
        encoding="utf-8",
    )
    # Test file referencing paymentAmount
    src_test = pc_dir / "src" / "test" / "java"
    src_test.mkdir(parents=True)
    (src_test / "PaymentClientTest.java").write_text(
        "public class PaymentClientTest { void testPayment() { assertThat(resp.getPaymentAmount()).isNotNull(); } }",
        encoding="utf-8",
    )

    # Consumer 2: order-service (contract only, no source files)
    order_dir = ws / "order-service"
    (order_dir / "contracts").mkdir(parents=True)
    (order_dir / "contracts" / "payment-service.yaml").write_text(
        textwrap.dedent("""
        openapi: "3.1.0"
        info:
          title: Order Service Consumer
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
        """).lstrip(),
        encoding="utf-8",
    )
    (order_dir / "contractguard.yaml").write_text(
        textwrap.dedent("""
        service: order-service
        dependencies:
          - service: payment-service
            consumer_contract: contracts/payment-service.yaml
            producer_contract: ../payment-service/docs/openapi.yaml
        """).lstrip(),
        encoding="utf-8",
    )

    # Consumer 3: reporting-service (contract only, no source files)
    rep_dir = ws / "reporting-service"
    (rep_dir / "contracts").mkdir(parents=True)
    (rep_dir / "contracts" / "payment-service.yaml").write_text(
        textwrap.dedent("""
        openapi: "3.1.0"
        info:
          title: Reporting Service Consumer
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
        """).lstrip(),
        encoding="utf-8",
    )
    (rep_dir / "contractguard.yaml").write_text(
        textwrap.dedent("""
        service: reporting-service
        dependencies:
          - service: payment-service
            consumer_contract: contracts/payment-service.yaml
            producer_contract: ../payment-service/docs/openapi.yaml
        """).lstrip(),
        encoding="utf-8",
    )

    # Commit baseline API 1.4.0 in Git
    subprocess.run(["git", "add", "."], cwd=ws, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Baseline API 1.4.0"], cwd=ws, check=True, capture_output=True)

    # Introduce breaking change: paymentAmount -> totalAmount
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

    return ws


# ---------------------------------------------------------------------------
# 3. Mission Generator & Invariants Tests
# ---------------------------------------------------------------------------

def test_mission_generation_contains_correct_data(payment_workspace: Path):
    mission = generate_repair_mission(payment_workspace)

    # Producer & Severity & Status
    assert mission.producer == "payment-service"
    assert mission.severity == "breaking"
    assert mission.status == "BLOCKED"

    # SemVer recommendation
    assert mission.semver["bump"] == "major"
    assert mission.semver["current_version"] == "1.4.0"
    assert mission.semver["recommended_version"] == "2.0.0"

    # Semantic change details
    assert mission.change.endpoint == "GET /api/payments/{id}"
    assert mission.change.change_kind == "field_renamed"
    assert mission.change.field == "paymentAmount"
    assert mission.change.old_value == "paymentAmount"
    assert mission.change.new_value == "totalAmount"
    assert mission.change.compatibility == "breaking"

    # Affected consumers
    assert len(mission.affected_consumers) == 3
    consumer_map = {c.service: c for c in mission.affected_consumers}
    assert set(consumer_map.keys()) == {"payment-client", "order-service", "reporting-service"}

    # Payment client has confirmed source and test files
    pc = consumer_map["payment-client"]
    assert "GET /api/payments/{id}" in pc.affected_endpoints
    assert "paymentAmount" in pc.affected_fields
    assert any("PaymentResponse.java" in f for f in pc.confirmed_source_files)
    assert any("PaymentClientTest.java" in f for f in pc.confirmed_test_files)

    # Crucial test requirement: DO NOT INVENT SOURCE FILES
    order_svc = consumer_map["order-service"]
    assert order_svc.confirmed_source_files == []
    assert order_svc.confirmed_test_files == []

    reporting_svc = consumer_map["reporting-service"]
    assert reporting_svc.confirmed_source_files == []
    assert reporting_svc.confirmed_test_files == []

    # Required actions are instructions for Bob
    assert "Update consumer contract" in mission.required_actions
    assert "Update affected DTO/model mapping if present" in mission.required_actions
    assert "Re-run ContractGuard verification" in mission.required_actions

    # Acceptance criteria are exact and deterministic
    assert mission.acceptance_criteria == [
        "All discovered consumer contracts compatible",
        "No breaking findings remain",
        "Affected tests pass when available",
        "ContractGuard verification returns READY",
    ]


def test_mission_id_is_stable_and_not_random(payment_workspace: Path):
    mission_1 = generate_repair_mission(payment_workspace)
    mission_2 = generate_repair_mission(payment_workspace)

    assert mission_1.mission_id == mission_2.mission_id
    assert mission_1.mission_id.startswith("mission-payment-service-")
    assert len(mission_1.mission_id) > len("mission-payment-service-")


# ---------------------------------------------------------------------------
# 4. CLI Tests
# ---------------------------------------------------------------------------

def test_cli_mission_text(payment_workspace: Path):
    proc = subprocess.run(
        [sys.executable, "-m", "contract_guard", "mission", str(payment_workspace), "--format", "text"],
        capture_output=True,
        text=True,
    )
    # BLOCKED returns exit code 1
    assert proc.returncode == 1
    out = proc.stdout
    assert "CONTRACTGUARD REPAIR MISSION" in out
    assert "payment-service" in out
    assert "BLOCKED" in out
    assert "paymentAmount" in out
    assert "totalAmount" in out
    assert "payment-client" in out
    assert "order-service" in out
    assert "reporting-service" in out


def test_cli_mission_json(payment_workspace: Path):
    proc = subprocess.run(
        [sys.executable, "-m", "contract_guard", "mission", str(payment_workspace), "--format", "json"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1
    data = json.loads(proc.stdout)
    assert data["mission_id"].startswith("mission-payment-service-")
    assert data["status"] == "BLOCKED"
    assert data["change"]["old_value"] == "paymentAmount"
    assert data["change"]["new_value"] == "totalAmount"
    assert len(data["affected_consumers"]) == 3


def test_cli_mission_markdown(payment_workspace: Path):
    out_file = payment_workspace / "mission.md"
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "contract_guard",
            "mission",
            str(payment_workspace),
            "--format",
            "markdown",
            "--output",
            str(out_file),
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1
    assert out_file.exists()
    content = out_file.read_text(encoding="utf-8")
    assert "# ContractGuard Repair Mission" in content
    assert "## Semantic Change" in content
    assert "## Affected Consumers (3)" in content
    assert "## Required Actions" in content
    assert "## Acceptance Criteria" in content


def test_cli_mission_nonexistent_workspace(tmp_path: Path):
    proc = subprocess.run(
        [sys.executable, "-m", "contract_guard", "mission", str(tmp_path / "does_not_exist")],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2
    assert "ERROR:" in proc.stderr


# ---------------------------------------------------------------------------
# 5. MCP Tool Tests
# ---------------------------------------------------------------------------

def test_mcp_get_repair_mission_success(payment_workspace: Path):
    data = handle_get_repair_mission({"workspace_root": str(payment_workspace)})
    assert not data.get("isError")
    assert data["producer"] == "payment-service"
    assert data["status"] == "BLOCKED"
    assert len(data["affected_consumers"]) == 3
    assert data["change"]["change_kind"] == "field_renamed"
    assert data["change"]["new_value"] == "totalAmount"


def test_mcp_get_repair_mission_error_handling(tmp_path: Path):
    # Missing workspace_root argument
    missing_arg = handle_get_repair_mission({})
    assert missing_arg.get("isError") is True

    # Nonexistent workspace path
    not_found = handle_get_repair_mission({"workspace_root": str(tmp_path / "ghost_dir")})
    assert not_found.get("isError") is True
    assert "Workspace root not found" in not_found["content"][0]["text"]


def test_mcp_stdio_dispatch_get_repair_mission(payment_workspace: Path):
    msg = {
        "jsonrpc": "2.0",
        "id": "req-123",
        "method": "tools/call",
        "params": {
            "name": "get_repair_mission",
            "arguments": {"workspace_root": str(payment_workspace)},
        },
    }
    resp = _dispatch(msg)
    assert resp is not None
    assert resp["id"] == "req-123"
    result = resp["result"]
    assert not result.get("isError")
    mission_dict = json.loads(result["content"][0]["text"])
    assert mission_dict["producer"] == "payment-service"
    assert mission_dict["status"] == "BLOCKED"


def test_mcp_tools_list_includes_repair_mission():
    msg = {
        "jsonrpc": "2.0",
        "id": "list-1",
        "method": "tools/list",
    }
    resp = _dispatch(msg)
    assert resp is not None
    tools = resp["result"]["tools"]
    tool_names = [t["name"] for t in tools]
    assert len(tool_names) == 8
    assert "get_repair_mission" in tool_names


# ---------------------------------------------------------------------------
# 6. End-to-End Workflow: Breaking Change -> Mission -> Bob Repairs -> READY
# ---------------------------------------------------------------------------

def test_e2e_breaking_to_mission_to_repair(payment_workspace: Path):
    # Step 1: Breaking change detected -> generate mission
    mission = generate_repair_mission(payment_workspace)
    assert mission.status == "BLOCKED"
    assert len(mission.affected_consumers) == 3
    assert mission.semver["bump"] == "major"
    assert mission.semver["recommended_version"] == "2.0.0"

    # Step 2: Bob executes repair on consumer contracts
    # Update payment-client contract
    pc_contract = payment_workspace / "payment-client" / "contracts" / "payment-service.yaml"
    pc_contract.write_text(
        pc_contract.read_text(encoding="utf-8").replace("paymentAmount", "totalAmount"),
        encoding="utf-8",
    )
    # Update order-service contract
    order_contract = payment_workspace / "order-service" / "contracts" / "payment-service.yaml"
    order_contract.write_text(
        order_contract.read_text(encoding="utf-8").replace("paymentAmount", "totalAmount"),
        encoding="utf-8",
    )
    # Update reporting-service contract
    rep_contract = payment_workspace / "reporting-service" / "contracts" / "payment-service.yaml"
    rep_contract.write_text(
        rep_contract.read_text(encoding="utf-8").replace("paymentAmount", "totalAmount"),
        encoding="utf-8",
    )

    # Step 3: Re-generate mission post-repair
    post_repair_mission = generate_repair_mission(payment_workspace)
    assert post_repair_mission.status == "READY"
    assert len(post_repair_mission.affected_consumers) == 0
    # Crucial Phase 2 invariant: SemVer remains MAJOR (1.4.0 -> 2.0.0)
    assert post_repair_mission.semver["bump"] == "major"
    assert post_repair_mission.semver["recommended_version"] == "2.0.0"
    assert "all discovered consumers are compatible" in post_repair_mission.semver["reason"].lower()
