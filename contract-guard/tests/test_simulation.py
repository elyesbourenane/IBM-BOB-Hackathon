"""
Tests for ContractGuard Phase 3D — What-If / Pre-Change Simulation.

Validates:
- Pure in-memory simulation without modifying any files or git state.
- Simulation of breaking rename (paymentAmount -> totalAmount).
- Simulation of compatible addition (new optional field).
- Simulation of endpoint removal.
- Handling of invalid inputs.
- CLI: contract-guard what-if <workspace_root> --change-kind field_renamed ...
- MCP: get_blast_radius with simulation parameters.
- Deterministic output.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from contract_guard.mcp_server import handle_get_blast_radius
from contract_guard.simulation import WhatIfResult, simulate_what_if


def _init_git(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "ContractGuard Tester"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@contractguard.dev"], cwd=path, check=True, capture_output=True)


@pytest.fixture
def clean_workspace(tmp_path: Path) -> Path:
    """
    Clean baseline workspace: producer and consumers are in sync with 'paymentAmount'.
    """
    ws = tmp_path / "clean_ws"
    ws.mkdir()
    _init_git(ws)

    # Producer
    prod_dir = ws / "payment-service" / "docs"
    prod_dir.mkdir(parents=True)
    prod_file = prod_dir / "openapi.yaml"
    prod_file.write_text(
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

    # Consumer 2: payment-client
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

    return ws


def test_simulation_breaking_rename_no_mutation(clean_workspace: Path):
    prod_path = clean_workspace / "payment-service" / "docs" / "openapi.yaml"
    initial_content = prod_path.read_text(encoding="utf-8")

    result = simulate_what_if(
        workspace_root=str(clean_workspace),
        producer="payment-service",
        endpoint="/api/payments/{id}",
        field="paymentAmount",
        change_kind="field_renamed",
        new_value="totalAmount",
        method="GET",
    )

    # Invariant: producer file MUST NOT be touched
    assert prod_path.read_text(encoding="utf-8") == initial_content

    assert result.simulated is True
    assert result.compatibility == "breaking"
    assert result.release_status == "BLOCKED"
    assert result.semver["recommendation"] == "MAJOR"
    assert result.direct_consumers == 2
    assert len(result.affected_consumers) == 2
    assert len(result.findings) == 1
    assert result.findings[0]["change_kind"] == "field_renamed"

    # Formats
    txt = result.format_text()
    assert "WHAT-IF SIMULATION" in txt
    assert "BREAKING" in txt

    md = result.format_markdown()
    assert "CONTRACTGUARD WHAT-IF SIMULATION" in md
    assert "SIMULATED / NOT APPLIED" in md

    d = json.loads(result.to_json())
    assert d["simulated"] is True
    assert d["compatibility"] == "breaking"


def test_simulation_compatible_addition(clean_workspace: Path):
    result = simulate_what_if(
        workspace_root=str(clean_workspace),
        producer="payment-service",
        endpoint="/api/payments/{id}",
        field="bonusField",
        change_kind="field_added",
        new_value="bonusField",
        method="GET",
    )

    assert result.simulated is True
    assert result.compatibility == "compatible"
    assert result.release_status == "READY"
    assert result.semver["recommendation"] == "MINOR"
    assert len(result.affected_consumers) == 0


def test_simulation_endpoint_removed(clean_workspace: Path):
    result = simulate_what_if(
        workspace_root=str(clean_workspace),
        producer="payment-service",
        endpoint="/api/payments/{id}",
        field="",
        change_kind="endpoint_removed",
        method="GET",
    )

    assert result.simulated is True
    assert result.compatibility == "breaking"
    assert result.release_status == "BLOCKED"
    assert result.semver["recommendation"] == "MAJOR"
    assert len(result.affected_consumers) == 2


def test_simulation_invalid_inputs(clean_workspace: Path):
    # Invalid change_kind
    with pytest.raises(ValueError, match="Unsupported change_kind"):
        simulate_what_if(
            workspace_root=str(clean_workspace),
            producer="payment-service",
            change_kind="unknown_kind",
        )

    # Missing producer contract
    with pytest.raises(FileNotFoundError):
        simulate_what_if(
            workspace_root=str(clean_workspace),
            producer="non-existent-service",
            change_kind="field_renamed",
            field="f",
            new_field="nf",
        )


def test_cli_what_if_breaking(clean_workspace: Path):
    res = subprocess.run(
        [
            sys.executable,
            "-m",
            "contract_guard",
            "what-if",
            str(clean_workspace),
            "--producer",
            "payment-service",
            "--endpoint",
            "/api/payments/{id}",
            "--field",
            "paymentAmount",
            "--new-field",
            "totalAmount",
            "--change-kind",
            "field_renamed",
        ],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 1  # BLOCKED simulation -> exit 1
    assert "WHAT-IF SIMULATION" in res.stdout
    assert "BREAKING" in res.stdout


def test_cli_what_if_compatible(clean_workspace: Path):
    res = subprocess.run(
        [
            sys.executable,
            "-m",
            "contract_guard",
            "what-if",
            str(clean_workspace),
            "--producer",
            "payment-service",
            "--endpoint",
            "/api/payments/{id}",
            "--field",
            "bonusField",
            "--change-kind",
            "field_optional_added",
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0  # READY simulation -> exit 0
    data = json.loads(res.stdout)
    assert data["compatibility"] == "compatible"
    assert data["release_status"] == "READY"


def test_mcp_get_blast_radius_simulation(clean_workspace: Path):
    res = handle_get_blast_radius({
        "workspace_root": str(clean_workspace),
        "producer": "payment-service",
        "change_kind": "field_renamed",
        "endpoint": "/api/payments/{id}",
        "field": "paymentAmount",
        "new_value": "totalAmount",
    })

    assert res["simulated"] is True
    assert res["compatibility"] == "breaking"
    assert res["release_status"] == "BLOCKED"
    assert res["affected_consumers"] == 2


def test_simulation_canonical_rename_no_duplicates(clean_workspace: Path):
    result = simulate_what_if(
        workspace_root=str(clean_workspace),
        producer="payment-service",
        endpoint="/api/payments/{id}",
        field="paymentAmount",
        change_kind="field_renamed",
        new_value="totalAmount",
        method="GET",
    )

    assert result.compatibility == "breaking"
    assert result.status == "BLOCKED"
    assert len(result.affected_consumers) == 2
    # Exactly one canonical finding, no duplicate rename findings
    assert len(result.findings) == 1
    assert result.findings[0]["change_kind"] == "field_renamed"
    assert result.findings[0]["affected_field"] == "paymentAmount"
    # No field_removed finding alongside the rename
    assert not any(f["change_kind"] == "field_removed" for f in result.findings)


def test_simulation_field_removed_entirely(clean_workspace: Path):
    result = simulate_what_if(
        workspace_root=str(clean_workspace),
        producer="payment-service",
        endpoint="/api/payments/{id}",
        field="paymentAmount",
        change_kind="field_removed",
        method="GET",
    )

    assert result.compatibility == "breaking"
    assert result.status == "BLOCKED"
    assert len(result.affected_consumers) == 2
    assert len(result.findings) == 1
    assert result.findings[0]["change_kind"] == "field_removed"
    assert result.findings[0]["affected_field"] == "paymentAmount"


@pytest.fixture
def ref_workspace(tmp_path: Path) -> Path:
    """
    Workspace where producer and 3 consumers use $ref schemas for PaymentResponse.
    Baseline has id: string, status: string.
    """
    ws = tmp_path / "ref_ws"
    ws.mkdir()
    _init_git(ws)

    # Producer
    prod_dir = ws / "payment-service" / "docs"
    prod_dir.mkdir(parents=True)
    prod_file = prod_dir / "openapi.yaml"
    prod_file.write_text(
        textwrap.dedent("""
        openapi: "3.1.0"
        info:
          title: Payment Service
          version: "1.0.0"
        paths:
          /api/payments/{id}:
            get:
              responses:
                "200":
                  content:
                    application/json:
                      schema:
                        $ref: "#/components/schemas/PaymentResponse"
        components:
          schemas:
            PaymentResponse:
              type: object
              required:
                - id
                - status
              properties:
                id:
                  type: string
                status:
                  type: string
        """).strip(),
        encoding="utf-8",
    )

    # 3 Consumers
    for name in ["order-service", "payment-client", "reporting-service"]:
        c_dir = ws / name
        (c_dir / "contracts").mkdir(parents=True)
        (c_dir / "contracts" / "payment-service.yaml").write_text(
            textwrap.dedent("""
            openapi: "3.1.0"
            info:
              title: Payment Service Consumer Contract
              version: "1.0.0"
            paths:
              /api/payments/{id}:
                get:
                  responses:
                    "200":
                      content:
                        application/json:
                          schema:
                            $ref: "#/components/schemas/PaymentResponse"
            components:
              schemas:
                PaymentResponse:
                  type: object
                  required:
                    - id
                    - status
                  properties:
                    id:
                      type: string
                    status:
                      type: string
            """).strip(),
            encoding="utf-8",
        )
        (c_dir / "contractguard.yaml").write_text(
            textwrap.dedent(f"""
            service: {name}
            dependencies:
              - service: payment-service
                consumer_contract: contracts/payment-service.yaml
                producer_contract: ../payment-service/docs/openapi.yaml
            """).strip(),
            encoding="utf-8",
        )

    return ws


def test_scenario_a_field_renamed(ref_workspace: Path):
    """Scenario A: status -> paymentStatus flags 3/3 affected consumers with single canonical field_renamed."""
    prod_path = ref_workspace / "payment-service" / "docs" / "openapi.yaml"
    before = prod_path.read_text(encoding="utf-8")

    res = simulate_what_if(
        workspace_root=str(ref_workspace),
        producer="payment-service",
        endpoint="/api/payments/{id}",
        field="status",
        new_field="paymentStatus",
        change_kind="field_renamed",
        method="GET",
    )

    assert res.compatibility == "breaking"
    assert res.status == "BLOCKED"
    assert len(res.affected_consumers) == 3
    assert set(res.affected_consumers) == {"order-service", "payment-client", "reporting-service"}
    assert len(res.findings) == 1
    assert res.findings[0]["change_kind"] == "field_renamed"
    assert res.findings[0]["affected_field"] == "status"
    assert not any(f["change_kind"] == "field_removed" for f in res.findings)

    # Non-mutating
    assert prod_path.read_text(encoding="utf-8") == before


def test_scenario_b_field_removed(ref_workspace: Path):
    """Scenario B: removal of status flags 3/3 affected consumers with field_removed."""
    prod_path = ref_workspace / "payment-service" / "docs" / "openapi.yaml"
    before = prod_path.read_text(encoding="utf-8")

    res = simulate_what_if(
        workspace_root=str(ref_workspace),
        producer="payment-service",
        endpoint="/api/payments/{id}",
        field="status",
        change_kind="field_removed",
        method="GET",
    )

    assert res.compatibility == "breaking"
    assert res.status == "BLOCKED"
    assert len(res.affected_consumers) == 3
    assert set(res.affected_consumers) == {"order-service", "payment-client", "reporting-service"}
    assert len(res.findings) == 1
    assert res.findings[0]["change_kind"] == "field_removed"
    assert res.findings[0]["affected_field"] == "status"

    # Non-mutating
    assert prod_path.read_text(encoding="utf-8") == before


def test_scenario_c_required_field_added(ref_workspace: Path):
    """Scenario C: adding required paymentStatus flags 3/3 affected consumers with field_required_added."""
    prod_path = ref_workspace / "payment-service" / "docs" / "openapi.yaml"
    before = prod_path.read_text(encoding="utf-8")

    res = simulate_what_if(
        workspace_root=str(ref_workspace),
        producer="payment-service",
        endpoint="/api/payments/{id}",
        field="extraCode",
        change_kind="field_required_added",
        method="GET",
    )

    assert res.compatibility == "breaking"
    assert res.status == "BLOCKED"
    assert len(res.affected_consumers) == 3
    assert set(res.affected_consumers) == {"order-service", "payment-client", "reporting-service"}
    assert any(f["change_kind"] == "field_required_added" for f in res.findings)

    # Non-mutating
    assert prod_path.read_text(encoding="utf-8") == before


def test_scenario_d_optional_field_added(ref_workspace: Path):
    """Scenario D: adding optional paymentStatus leaves 3 consumers compatible and 0 affected."""
    prod_path = ref_workspace / "payment-service" / "docs" / "openapi.yaml"
    before = prod_path.read_text(encoding="utf-8")

    res = simulate_what_if(
        workspace_root=str(ref_workspace),
        producer="payment-service",
        endpoint="/api/payments/{id}",
        field="extraCode",
        change_kind="field_optional_added",
        method="GET",
    )

    assert res.compatibility == "compatible"
    assert res.status == "READY"
    assert len(res.affected_consumers) == 0
    assert len(res.compatible_consumers) == 3

    # Non-mutating
    assert prod_path.read_text(encoding="utf-8") == before


def test_scenario_e_type_changed(ref_workspace: Path):
    """Scenario E: status string -> integer flags 3/3 affected consumers with field_type_changed."""
    prod_path = ref_workspace / "payment-service" / "docs" / "openapi.yaml"
    before = prod_path.read_text(encoding="utf-8")

    res = simulate_what_if(
        workspace_root=str(ref_workspace),
        producer="payment-service",
        endpoint="/api/payments/{id}",
        field="status",
        new_value="integer",
        change_kind="field_type_changed",
        method="GET",
    )

    assert res.compatibility == "breaking"
    assert res.status == "BLOCKED"
    assert len(res.affected_consumers) == 3
    assert set(res.affected_consumers) == {"order-service", "payment-client", "reporting-service"}
    assert any(f["change_kind"] == "field_type_changed" for f in res.findings)

    # Non-mutating
    assert prod_path.read_text(encoding="utf-8") == before


def test_scenario_f_endpoint_removed(ref_workspace: Path):
    """Scenario F: endpoint removal flags 3/3 affected consumers with endpoint_removed."""
    prod_path = ref_workspace / "payment-service" / "docs" / "openapi.yaml"
    before = prod_path.read_text(encoding="utf-8")

    res = simulate_what_if(
        workspace_root=str(ref_workspace),
        producer="payment-service",
        endpoint="/api/payments/{id}",
        change_kind="endpoint_removed",
        method="GET",
    )

    assert res.compatibility == "breaking"
    assert res.status == "BLOCKED"
    assert len(res.affected_consumers) == 3
    assert set(res.affected_consumers) == {"order-service", "payment-client", "reporting-service"}
    assert any(f["change_kind"] == "endpoint_removed" for f in res.findings)

    # Non-mutating
    assert prod_path.read_text(encoding="utf-8") == before

