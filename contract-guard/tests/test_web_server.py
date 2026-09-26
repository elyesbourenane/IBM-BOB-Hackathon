"""
Tests for the ContractGuard Command Center web server (Phase 3G).

These tests verify that the Flask API endpoints correctly wrap
the existing ContractGuard deterministic engine without duplicating logic.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

# Ensure the project source is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


@pytest.fixture
def workspace(tmp_path):
    """Create a minimal multi-consumer workspace for web server testing."""
    # --- Producer: payment-service ---
    prod_dir = tmp_path / "payment-service" / "docs"
    prod_dir.mkdir(parents=True)
    (prod_dir / "openapi.yaml").write_text(
        """
openapi: "3.0.0"
info:
  title: Payment Service
  version: "1.0.0"
paths:
  /api/payments/{id}:
    get:
      summary: Get payment
      responses:
        '200':
          description: OK
          content:
            application/json:
              schema:
                type: object
                required:
                  - paymentId
                  - paymentAmount
                properties:
                  paymentId:
                    type: string
                  paymentAmount:
                    type: number
        """,
        encoding="utf-8",
    )

    # --- Consumer: order-service (compatible) ---
    order_dir = tmp_path / "order-service"
    order_dir.mkdir(parents=True)
    contracts_dir = order_dir / "contracts"
    contracts_dir.mkdir()
    (contracts_dir / "payment-service.yaml").write_text(
        """
openapi: "3.0.0"
info:
  title: Payment Service (order-service consumer copy)
  version: "1.0.0"
paths:
  /api/payments/{id}:
    get:
      summary: Get payment
      responses:
        '200':
          description: OK
          content:
            application/json:
              schema:
                type: object
                required:
                  - paymentId
                  - paymentAmount
                properties:
                  paymentId:
                    type: string
                  paymentAmount:
                    type: number
        """,
        encoding="utf-8",
    )
    (order_dir / "contractguard.yaml").write_text(
        f"""
service: order-service
dependencies:
  - service: payment-service
    consumer_contract: contracts/payment-service.yaml
    producer_contract: ../payment-service/docs/openapi.yaml
        """,
        encoding="utf-8",
    )

    # --- Consumer: reporting-service (also compatible) ---
    report_dir = tmp_path / "reporting-service"
    report_dir.mkdir(parents=True)
    report_contracts = report_dir / "contracts"
    report_contracts.mkdir()
    (report_contracts / "payment-service.yaml").write_text(
        """
openapi: "3.0.0"
info:
  title: Payment Service (reporting consumer copy)
  version: "1.0.0"
paths:
  /api/payments/{id}:
    get:
      summary: Get payment
      responses:
        '200':
          description: OK
          content:
            application/json:
              schema:
                type: object
                required:
                  - paymentId
                  - paymentAmount
                properties:
                  paymentId:
                    type: string
                  paymentAmount:
                    type: number
        """,
        encoding="utf-8",
    )
    (report_dir / "contractguard.yaml").write_text(
        f"""
service: reporting-service
dependencies:
  - service: payment-service
    consumer_contract: contracts/payment-service.yaml
    producer_contract: ../payment-service/docs/openapi.yaml
        """,
        encoding="utf-8",
    )

    return tmp_path


@pytest.fixture
def client(workspace):
    """Create a Flask test client using the workspace."""
    from contract_guard.web_server import app, _WORKSPACE_ROOT
    import contract_guard.web_server as ws_module

    ws_module._WORKSPACE_ROOT = workspace
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


class TestWebServerUI:
    """Tests for static UI serving."""

    def test_index_page_returns_html(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert b"ContractGuard" in resp.data
        assert b"Command Center" in resp.data

    def test_index_contains_nav_tabs(self, client):
        resp = client.get("/")
        assert b"What-If" in resp.data
        assert b"Blast Radius" in resp.data
        assert b"Repair Mission" in resp.data
        assert b"Verification" in resp.data
        assert b"Change Passport" in resp.data


class TestWhatIfAPI:
    """Tests for /api/what-if endpoint."""

    def test_whatif_breaking_rename(self, client):
        resp = client.post(
            "/api/what-if",
            data=json.dumps({
                "producer": "payment-service",
                "endpoint": "GET /api/payments/{id}",
                "change_kind": "field_renamed",
                "field": "paymentAmount",
                "new_field": "totalAmount",
            }),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["is_simulated"] is True
        assert data["simulated"] is True
        assert data["classification"] == "BREAKING"
        assert data["status"] == "BLOCKED"
        assert "SIMULATED" in data.get("simulation_note", "")

    def test_whatif_compatible_addition(self, client):
        resp = client.post(
            "/api/what-if",
            data=json.dumps({
                "producer": "payment-service",
                "endpoint": "GET /api/payments/{id}",
                "change_kind": "field_optional_added",
                "field": "newOptionalField",
            }),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["is_simulated"] is True
        assert data["classification"] == "COMPATIBLE"
        assert data["status"] == "READY"

    def test_whatif_invalid_change_kind(self, client):
        resp = client.post(
            "/api/what-if",
            data=json.dumps({
                "producer": "payment-service",
                "endpoint": "GET /api/payments/{id}",
                "change_kind": "invalid_kind",
            }),
            content_type="application/json",
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert "error" in data


class TestBlastRadiusAPI:
    """Tests for /api/blast-radius endpoint."""

    def test_blast_radius_returns_graph(self, client):
        resp = client.get("/api/blast-radius?producer=payment-service")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "graph" in data
        assert "nodes" in data["graph"]
        assert "edges" in data["graph"]
        assert "consumers_checked" in data
        assert isinstance(data["consumers_checked"], list)

    def test_blast_radius_has_summary(self, client):
        resp = client.get("/api/blast-radius?producer=payment-service")
        data = resp.get_json()
        assert "summary" in data


class TestRepairMissionAPI:
    """Tests for /api/repair-mission endpoint."""

    def test_repair_mission_returns_structure(self, client):
        resp = client.get("/api/repair-mission?producer=payment-service")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "mission_id" in data
        assert "title" in data
        assert "producer" in data
        assert "status" in data
        assert "required_actions" in data
        assert "acceptance_criteria" in data

    def test_repair_mission_has_change(self, client):
        resp = client.get("/api/repair-mission?producer=payment-service")
        data = resp.get_json()
        assert "change" in data
        assert "change_kind" in data["change"]


class TestVerifyAPI:
    """Tests for /api/verify endpoint."""

    def test_verify_returns_status(self, client):
        resp = client.get("/api/verify?producer=payment-service&test_status=PASS")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "status" in data
        assert data["status"] in ("READY", "BLOCKED")
        assert "is_ready" in data
        assert "consumers_checked" in data
        assert "compatible_consumers" in data

    def test_verify_compatible_workspace_is_ready(self, client):
        """In a compatible workspace, verify returns READY."""
        resp = client.get("/api/verify?producer=payment-service&test_status=PASS")
        data = resp.get_json()
        assert data["status"] == "READY"
        assert data["is_ready"] is True


class TestPassportAPI:
    """Tests for /api/passport endpoint."""

    def test_passport_returns_full_structure(self, client):
        resp = client.get("/api/passport?producer=payment-service")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "passport_id" in data
        assert "producer" in data
        assert "contract" in data
        assert "change" in data
        assert "impact" in data
        assert "release" in data
        assert "verification" in data
        assert "dependency_graph" in data
        assert "repair_mission" in data

    def test_passport_has_release_status(self, client):
        resp = client.get("/api/passport?producer=payment-service")
        data = resp.get_json()
        assert "release_status" in data
        assert data["release_status"] in ("READY", "BLOCKED")


class TestDiscoveryAPI:
    """Tests for /api/discovery endpoint."""

    def test_discovery_returns_consumers(self, client):
        resp = client.get("/api/discovery?producer=payment-service")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "consumers_checked" in data
        assert "results" in data
        assert len(data["results"]) >= 1
