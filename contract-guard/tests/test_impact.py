"""Tests for the blast-radius / impact analysis module."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from contract_guard.discovery import discover_and_check
from contract_guard.impact import (
    ConsumerImpact,
    scan_consumer_impact,
    _extract_field_tokens,
    _extract_likely_tokens,
)
from contract_guard.models import ChangeKind, Finding


def test_extract_field_tokens():
    tokens = _extract_field_tokens("paymentAmount")
    assert "paymentAmount" in tokens
    assert "PaymentAmount" in tokens
    assert "payment_amount" in tokens

    nested_tokens = _extract_field_tokens("data.paymentAmount")
    assert "paymentAmount" in nested_tokens

    snake_tokens = _extract_field_tokens("total_amount")
    assert "total_amount" in snake_tokens
    assert "totalAmount" in snake_tokens


def test_extract_likely_tokens():
    finding = Finding(
        endpoint="GET /api/payments/{id}",
        affected_field="paymentAmount",
        change_kind=ChangeKind.FIELD_RENAMED,
        detail="detail",
    )
    tokens = _extract_likely_tokens("GET /api/payments/{id}", finding)
    assert "payments" in tokens or "payment" in tokens


def test_scan_consumer_impact_with_confirmed_and_likely_files(tmp_path: Path):
    consumer_dir = tmp_path / "payment-client"
    consumer_dir.mkdir()

    # Source files
    src_main = consumer_dir / "src" / "main" / "java"
    src_main.mkdir(parents=True)
    resp_file = src_main / "PaymentResponse.java"
    resp_file.write_text(
        "public class PaymentResponse { private BigDecimal paymentAmount; public BigDecimal getPaymentAmount() { return paymentAmount; } }",
        encoding="utf-8",
    )
    client_file = src_main / "PaymentClient.java"
    client_file.write_text(
        "public class PaymentClient { public PaymentResponse getPayment() { return null; } }",
        encoding="utf-8",
    )

    # Test files
    src_test = consumer_dir / "src" / "test" / "java"
    src_test.mkdir(parents=True)
    test_file = src_test / "PaymentResponseTest.java"
    test_file.write_text(
        "public class PaymentResponseTest { void test() { assertEquals(10, resp.getPaymentAmount()); } }",
        encoding="utf-8",
    )

    # Contract
    contracts_dir = consumer_dir / "contracts"
    contracts_dir.mkdir()
    consumer_contract = contracts_dir / "payment-service.yaml"
    consumer_contract.write_text("openapi: 3.1.0", encoding="utf-8")

    # Producer contract dummy
    producer_contract = tmp_path / "payment-service" / "docs" / "openapi.yaml"
    producer_contract.parent.mkdir(parents=True)
    producer_contract.write_text("openapi: 3.1.0", encoding="utf-8")

    finding = Finding(
        endpoint="GET /api/payments/{id}",
        affected_field="paymentAmount",
        change_kind=ChangeKind.FIELD_RENAMED,
        detail="renamed to totalAmount",
    )

    impact = scan_consumer_impact(
        consumer_dir=consumer_dir,
        consumer_service="payment-client",
        producer_service="payment-service",
        consumer_contract=consumer_contract,
        producer_contract=producer_contract,
        finding=finding,
    )

    assert impact.consumer_service == "payment-client"
    assert impact.producer_service == "payment-service"
    assert impact.endpoint == "GET /api/payments/{id}"
    assert impact.affected_field == "paymentAmount"
    assert impact.change_kind == "field_renamed"
    assert impact.severity == "breaking"
    assert impact.contract_path == "contracts/payment-service.yaml"
    assert impact.source_path == "src/main"
    assert impact.test_path == "src/test"

    # Confirmed source: PaymentResponse.java mentions paymentAmount
    assert any("PaymentResponse.java" in f for f in impact.confirmed_source_files)
    # Confirmed test: PaymentResponseTest.java mentions paymentAmount
    assert any("PaymentResponseTest.java" in f for f in impact.confirmed_test_files)
    # Likely source: PaymentClient mentions PaymentResponse
    assert any("PaymentClient.java" in f for f in impact.likely_source_files)

    data = impact.to_dict()
    assert isinstance(data, dict)
    assert data["consumer_service"] == "payment-client"
    assert data["confirmed_source_files"] == impact.confirmed_source_files


def test_scan_consumer_impact_empty_for_contract_only_service(tmp_path: Path):
    consumer_dir = tmp_path / "order-service"
    consumer_dir.mkdir()
    contracts_dir = consumer_dir / "contracts"
    contracts_dir.mkdir()
    consumer_contract = contracts_dir / "payment-service.yaml"
    consumer_contract.write_text("openapi: 3.1.0", encoding="utf-8")

    producer_contract = tmp_path / "payment-service" / "openapi.yaml"
    producer_contract.parent.mkdir(parents=True, exist_ok=True)
    producer_contract.write_text("openapi: 3.1.0", encoding="utf-8")

    finding = Finding(
        endpoint="GET /api/payments/{id}",
        affected_field="paymentAmount",
        change_kind=ChangeKind.FIELD_REMOVED,
        detail="removed",
    )

    impact = scan_consumer_impact(
        consumer_dir=consumer_dir,
        consumer_service="order-service",
        producer_service="payment-service",
        consumer_contract=consumer_contract,
        producer_contract=producer_contract,
        finding=finding,
    )

    assert impact.confirmed_source_files == []
    assert impact.confirmed_test_files == []
    assert impact.likely_source_files == []
    assert impact.likely_test_files == []


def test_discovery_includes_impacts_on_breaking_change(tmp_path: Path):
    # Setup producer with totalAmount
    prod_dir = tmp_path / "payment-service" / "docs"
    prod_dir.mkdir(parents=True)
    (prod_dir / "openapi.yaml").write_text(
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
                        type: object
                        required: [id, totalAmount]
                        properties:
                          id: {type: string}
                          totalAmount: {type: number}
        """).lstrip(),
        encoding="utf-8",
    )

    # Setup consumer expecting paymentAmount
    client_dir = tmp_path / "payment-client"
    client_dir.mkdir()
    (client_dir / "contracts").mkdir()
    (client_dir / "contracts" / "payment-service.yaml").write_text(
        textwrap.dedent("""
        openapi: "3.1.0"
        info:
          title: Consumer Contract
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
                        required: [id, paymentAmount]
                        properties:
                          id: {type: string}
                          paymentAmount: {type: number}
        """).lstrip(),
        encoding="utf-8",
    )
    (client_dir / "contractguard.yaml").write_text(
        textwrap.dedent("""
        service: payment-client
        dependencies:
          - service: payment-service
            consumer_contract: contracts/payment-service.yaml
            producer_contract: ../payment-service/docs/openapi.yaml
        """).lstrip(),
        encoding="utf-8",
    )

    # Add source file
    src_dir = client_dir / "src" / "main" / "java"
    src_dir.mkdir(parents=True)
    (src_dir / "PaymentResponse.java").write_text(
        "private Double paymentAmount;", encoding="utf-8"
    )

    report = discover_and_check(tmp_path)
    assert len(report.affected_consumers) == 1
    assert "payment-client" in report.affected_consumers
    assert len(report.impacts) >= 1
    impact = report.impacts[0]
    assert impact.consumer_service == "payment-client"
    assert impact.affected_field == "paymentAmount"
    assert any("PaymentResponse.java" in f for f in impact.confirmed_source_files)
