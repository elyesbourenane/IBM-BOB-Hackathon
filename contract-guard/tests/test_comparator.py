"""Integration tests for the Comparator using real YAML contracts."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
import yaml

from contract_guard.comparator import Comparator
from contract_guard.models import ChangeKind, ComparisonReport


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_contract(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(textwrap.dedent(content).lstrip("\n"), encoding="utf-8")
    return p


def _simple_contract(field_name: str, field_type: str, required: bool = True) -> str:
    req_section = (
        f"\n                required:\n                  - {field_name}"
        if required
        else ""
    )
    return f"""
openapi: "3.1.0"
info:
  title: Test
  version: "1.0.0"
paths:
  /items:
    get:
      responses:
        "200":
          content:
            application/json:
              schema:
                type: object{req_section}
                properties:
                  {field_name}:
                    type: {field_type}
"""


# ---------------------------------------------------------------------------
# Demo scenario: paymentAmount vs amount rename
# ---------------------------------------------------------------------------


class TestDemoScenario:
    def test_demo_contracts_are_breaking(self):
        contracts_dir = Path(__file__).parent.parent / "contracts"
        if not (contracts_dir / "producer.yaml").exists():
            pytest.skip("Demo contracts not found")
        report = Comparator(
            contracts_dir / "producer.yaml",
            contracts_dir / "consumer.yaml",
        ).compare()
        assert report.is_compatible is False

    def test_demo_detects_rename(self):
        contracts_dir = Path(__file__).parent.parent / "contracts"
        if not (contracts_dir / "producer.yaml").exists():
            pytest.skip("Demo contracts not found")
        report = Comparator(
            contracts_dir / "producer.yaml",
            contracts_dir / "consumer.yaml",
        ).compare()
        rename_findings = [
            f for f in report.findings if f.change_kind == ChangeKind.FIELD_RENAMED
        ]
        assert len(rename_findings) >= 1
        assert rename_findings[0].affected_field == "amount"


# ---------------------------------------------------------------------------
# Identical contracts
# ---------------------------------------------------------------------------


class TestIdenticalContracts:
    def test_identical_is_compatible(self, tmp_path):
        content = _simple_contract("amount", "number")
        p = _write_contract(tmp_path, "a.yaml", content)
        report = Comparator(p, p).compare()
        assert report.is_compatible is True
        # Only compatible (optional_added) findings allowed
        assert all(not f.is_breaking for f in report.findings)


# ---------------------------------------------------------------------------
# Field removed
# ---------------------------------------------------------------------------


class TestFieldRemoved:
    def test_field_removed_is_breaking(self, tmp_path):
        producer = _write_contract(
            tmp_path, "producer.yaml", _simple_contract("status", "string")
        )
        consumer_content = """
openapi: "3.1.0"
info:
  title: Test
  version: "1.0.0"
paths:
  /items:
    get:
      responses:
        "200":
          content:
            application/json:
              schema:
                type: object
                required:
                  - status
                  - amount
                properties:
                  status:
                    type: string
                  amount:
                    type: number
"""
        consumer = _write_contract(tmp_path, "consumer.yaml", consumer_content)
        report = Comparator(producer, consumer).compare()
        assert report.is_compatible is False
        removed = [f for f in report.findings if f.change_kind == ChangeKind.FIELD_REMOVED]
        assert any(f.affected_field == "amount" for f in removed)


# ---------------------------------------------------------------------------
# Type changed
# ---------------------------------------------------------------------------


class TestTypeChanged:
    def test_type_change_is_breaking(self, tmp_path):
        producer = _write_contract(
            tmp_path, "producer.yaml", _simple_contract("amount", "string")
        )
        consumer = _write_contract(
            tmp_path, "consumer.yaml", _simple_contract("amount", "number")
        )
        report = Comparator(producer, consumer).compare()
        assert report.is_compatible is False
        type_findings = [
            f for f in report.findings if f.change_kind == ChangeKind.FIELD_TYPE_CHANGED
        ]
        assert len(type_findings) == 1
        assert type_findings[0].affected_field == "amount"


# ---------------------------------------------------------------------------
# New optional field
# ---------------------------------------------------------------------------


class TestOptionalFieldAdded:
    def test_new_optional_field_is_compatible(self, tmp_path):
        producer_content = """
openapi: "3.1.0"
info:
  title: Test
  version: "1.0.0"
paths:
  /items:
    get:
      responses:
        "200":
          content:
            application/json:
              schema:
                type: object
                required:
                  - amount
                properties:
                  amount:
                    type: number
                  transactionId:
                    type: string
"""
        consumer = _write_contract(
            tmp_path, "consumer.yaml", _simple_contract("amount", "number")
        )
        producer = _write_contract(tmp_path, "producer.yaml", producer_content)
        report = Comparator(producer, consumer).compare()
        assert report.is_compatible is True
        opt_findings = [
            f for f in report.findings if f.change_kind == ChangeKind.FIELD_OPTIONAL_ADDED
        ]
        assert any(f.affected_field == "transactionId" for f in opt_findings)


# ---------------------------------------------------------------------------
# Newly required field
# ---------------------------------------------------------------------------


class TestRequiredAdded:
    def test_required_added_is_breaking(self, tmp_path):
        producer = _write_contract(
            tmp_path, "producer.yaml", _simple_contract("amount", "number", required=True)
        )
        # Consumer does not mark amount as required
        consumer = _write_contract(
            tmp_path, "consumer.yaml", _simple_contract("amount", "number", required=False)
        )
        report = Comparator(producer, consumer).compare()
        assert report.is_compatible is False
        req_findings = [
            f for f in report.findings if f.change_kind == ChangeKind.FIELD_REQUIRED_ADDED
        ]
        assert len(req_findings) == 1
        assert req_findings[0].affected_field == "amount"


# ---------------------------------------------------------------------------
# Report properties
# ---------------------------------------------------------------------------


class TestComparisonReport:
    def test_verdict_breaking(self, tmp_path):
        producer = _write_contract(
            tmp_path, "producer.yaml", _simple_contract("status", "string")
        )
        consumer = _write_contract(
            tmp_path, "consumer.yaml", _simple_contract("amount", "number")
        )
        report = Comparator(producer, consumer).compare()
        # amount is renamed/removed — breaking
        assert report.verdict in ("breaking",)

    def test_verdict_compatible(self, tmp_path):
        content = _simple_contract("amount", "number")
        p = _write_contract(tmp_path, "a.yaml", content)
        report = Comparator(p, p).compare()
        assert report.verdict == "compatible"


class TestEndpointRemoved:
    def test_removed_endpoint_is_breaking(self, tmp_path):
        consumer_yaml = """
openapi: "3.1.0"
info:
  title: Consumer
  version: "1.0.0"
paths:
  /api/v1/orders/{id}:
    get:
      responses:
        "200":
          content:
            application/json:
              schema:
                type: object
                properties:
                  id: {type: string}
"""
        producer_yaml = """
openapi: "3.1.0"
info:
  title: Producer
  version: "1.0.0"
paths:
  /api/v2/orders/{id}:
    get:
      responses:
        "200":
          content:
            application/json:
              schema:
                type: object
                properties:
                  id: {type: string}
"""
        consumer = _write_contract(tmp_path, "consumer.yaml", consumer_yaml)
        producer = _write_contract(tmp_path, "producer.yaml", producer_yaml)
        report = Comparator(producer, consumer).compare()
        assert report.is_compatible is False
        assert any(f.change_kind == ChangeKind.ENDPOINT_REMOVED for f in report.findings)
        removed = [f for f in report.findings if f.change_kind == ChangeKind.ENDPOINT_REMOVED][0]
        assert "GET /api/v1/orders/{id}" in removed.endpoint


class TestCircularReference:
    def test_circular_ref_does_not_infinite_loop(self, tmp_path):
        circular_yaml = """
openapi: "3.0.0"
info:
  title: Tree API
  version: "1.0.0"
paths:
  /trees:
    get:
      responses:
        "200":
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/Node"
components:
  schemas:
    Node:
      type: object
      properties:
        value:
          type: string
        child:
          $ref: "#/components/schemas/Node"
"""
        c1 = _write_contract(tmp_path, "c1.yaml", circular_yaml)
        c2 = _write_contract(tmp_path, "c2.yaml", circular_yaml)
        report = Comparator(c1, c2).compare()
        assert report.is_compatible is True


class TestArrayProperties:
    def test_array_item_property_type_change_detected(self, tmp_path):
        consumer_yaml = """
openapi: "3.0.0"
info:
  title: Test
  version: "1.0.0"
paths:
  /items:
    get:
      responses:
        "200":
          content:
            application/json:
              schema:
                type: array
                items:
                  type: object
                  properties:
                    id:
                      type: integer
"""
        producer_yaml = """
openapi: "3.0.0"
info:
  title: Test
  version: "1.0.0"
paths:
  /items:
    get:
      responses:
        "200":
          content:
            application/json:
              schema:
                type: array
                items:
                  type: object
                  properties:
                    id:
                      type: string
"""
        consumer = _write_contract(tmp_path, "consumer.yaml", consumer_yaml)
        producer = _write_contract(tmp_path, "producer.yaml", producer_yaml)
        report = Comparator(producer, consumer).compare()
        assert report.is_compatible is False
        type_changes = [f for f in report.findings if f.change_kind == ChangeKind.FIELD_TYPE_CHANGED]
        assert len(type_changes) == 1
        assert "id" in type_changes[0].affected_field

