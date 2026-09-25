"""
End-to-End Integration Test:
Verifies the full ContractGuard verification loop:
    API Change
        ↓
    Consumer Discovery
        ↓
    Deterministic Breaking Analysis
        ↓
    AI Impact Explanation & Advisory Repair Plan
        ↓
    Bob Repair Execution
        ↓
    Tests
        ↓
    Deterministic Re-verification
        ↓
    Release Evidence
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from contract_guard.ai.analyzer import ImpactAnalyzer
from contract_guard.ai.provider import LLMProvider, LLMResponse
from contract_guard.discovery import discover_and_check
from contract_guard.evidence import evaluate_release_gate, generate_evidence, ReleaseStatus


class MockMistralForE2E(LLMProvider):
    """Mock LLM Provider that mimics Mistral returning structured analysis."""

    def __init__(self) -> None:
        self.call_count = 0

    @property
    def name(self) -> str:
        return "mistral"

    @property
    def model_name(self) -> str:
        return "mistral-small-latest"

    def is_configured(self) -> bool:
        return True

    def complete(self, messages: list[dict[str, str]], json_mode: bool = True, temperature: float = 0.1) -> LLMResponse:
        self.call_count += 1
        content = {
            "summary": "payment-service renamed paymentAmount to totalAmount breaking 3 consumers",
            "breaking_change_explanation": (
                "Field 'paymentAmount' in GET /api/payments/{id} was renamed to 'totalAmount'. "
                "Downstream consumers expecting 'paymentAmount' will fail deserialization."
            ),
            "impact": [
                {
                    "consumer": "payment-client",
                    "files": ["src/main/java/com/example/paymentclient/model/PaymentResponse.java"],
                    "tests_to_update": ["src/test/java/com/example/paymentclient/client/PaymentClientTest.java"],
                    "reason": "Relies on paymentAmount property",
                    "confirmed_impact": ["paymentAmount removed from API response"],
                    "likely_impact": ["PaymentDisplayService formatting"],
                }
            ],
            "repair_plan": [
                "1. Update contracts/payment-service.yaml in payment-client, order-service, and reporting-service to totalAmount",
                "2. Update PaymentResponse.java to map @JsonProperty('totalAmount')",
                "3. Update PaymentClientTest.java fixtures to use totalAmount",
                "4. Re-run ContractGuard to deterministically verify compatibility",
            ],
            "migration_options": [
                "Dual-write both paymentAmount and totalAmount during deprecation window"
            ],
        }
        return LLMResponse(content=json.dumps(content), model="mistral-small-latest")


def test_full_e2e_verification_loop(tmp_path: Path):
    # =========================================================================
    # Step 1: Set up Baseline (3 consumers, all expecting paymentAmount)
    # =========================================================================
    prod_dir = tmp_path / "payment-service" / "docs"
    prod_dir.mkdir(parents=True)
    prod_contract = prod_dir / "openapi.yaml"
    prod_contract.write_text(
        textwrap.dedent("""
        openapi: "3.1.0"
        info: {title: Payment Service, version: "1.0.0"}
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

    consumers = ["payment-client", "order-service", "reporting-service"]
    consumer_contracts: dict[str, Path] = {}

    for c in consumers:
        c_dir = tmp_path / c
        c_contracts = c_dir / "contracts"
        c_contracts.mkdir(parents=True)
        c_contract = c_contracts / "payment-service.yaml"
        c_contract.write_text(
            textwrap.dedent("""
            openapi: "3.1.0"
            info: {title: Consumer Contract, version: "1.0.0"}
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
        consumer_contracts[c] = c_contract
        (c_dir / "contractguard.yaml").write_text(
            f"service: {c}\ndependencies:\n  - service: payment-service\n    consumer_contract: contracts/payment-service.yaml\n    producer_contract: ../payment-service/docs/openapi.yaml\n",
            encoding="utf-8",
        )

    # In payment-client, create Java code files
    pclient_src = tmp_path / "payment-client" / "src" / "main" / "java" / "com" / "example" / "paymentclient" / "model"
    pclient_src.mkdir(parents=True)
    (pclient_src / "PaymentResponse.java").write_text(
        "public class PaymentResponse { private BigDecimal paymentAmount; public BigDecimal getPaymentAmount() { return paymentAmount; } }",
        encoding="utf-8",
    )

    # Check baseline compatibility
    baseline_report = discover_and_check(tmp_path)
    assert len(baseline_report.consumers_checked) == 3
    assert len(baseline_report.compatible_consumers) == 3
    assert len(baseline_report.affected_consumers) == 0

    # Baseline release gate is READY
    gate_baseline = evaluate_release_gate(baseline_report, producer_service="payment-service")
    assert gate_baseline.status == ReleaseStatus.READY

    # =========================================================================
    # Step 2: Breaking API Change (paymentAmount -> totalAmount in producer ONLY)
    # =========================================================================
    prod_contract.write_text(
        textwrap.dedent("""
        openapi: "3.1.0"
        info: {title: Payment Service, version: "1.1.0"}
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

    # =========================================================================
    # Step 3: Discovery detects contract drift deterministically
    # =========================================================================
    drift_report = discover_and_check(tmp_path)
    assert len(drift_report.consumers_checked) == 3
    assert len(drift_report.compatible_consumers) == 0
    assert len(drift_report.affected_consumers) == 3

    # Blast radius exposes confirmed affected source file in payment-client
    assert len(drift_report.impacts) >= 1
    pclient_impact = next(i for i in drift_report.impacts if i.consumer_service == "payment-client")
    assert any("PaymentResponse.java" in f for f in pclient_impact.confirmed_source_files)

    # =========================================================================
    # Step 4: Release Safety Gate BLOCKED (even if mock tests pass!)
    # =========================================================================
    gate_blocked = evaluate_release_gate(
        drift_report,
        producer_service="payment-service",
        test_results={"status": "PASS", "details": "Consumer mock HTTP tests still pass green"},
    )
    assert gate_blocked.status == ReleaseStatus.BLOCKED
    assert not gate_blocked.is_ready
    assert gate_blocked.contract_checks_status == "FAIL"

    # =========================================================================
    # Step 5: AI Impact Analysis produces explanation and repair plan
    # =========================================================================
    mock_provider = MockMistralForE2E()
    analyzer = ImpactAnalyzer(provider=mock_provider)
    ai_report = analyzer.analyze(drift_report)

    assert ai_report.status == "available"
    assert ai_report.analysis is not None
    assert len(ai_report.analysis.repair_plan) > 0
    assert len(ai_report.analysis.impact) > 0
    assert mock_provider.call_count == 1

    # =========================================================================
    # Step 6: IBM Bob executes repair on consumers
    # =========================================================================
    for c, c_contract in consumer_contracts.items():
        # Update consumer contracts to expect totalAmount
        c_contract.write_text(
            textwrap.dedent("""
            openapi: "3.1.0"
            info: {title: Consumer Contract, version: "1.1.0"}
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

    # Update Java source
    (pclient_src / "PaymentResponse.java").write_text(
        "public class PaymentResponse { private BigDecimal totalAmount; public BigDecimal getTotalAmount() { return totalAmount; } }",
        encoding="utf-8",
    )

    # =========================================================================
    # Step 7: Deterministic Re-verification
    # =========================================================================
    recheck_report = discover_and_check(tmp_path)
    assert len(recheck_report.consumers_checked) == 3
    assert len(recheck_report.compatible_consumers) == 3
    assert len(recheck_report.affected_consumers) == 0

    # =========================================================================
    # Step 8: Release Safety Gate APPROVED
    # =========================================================================
    gate_ready = evaluate_release_gate(
        recheck_report,
        producer_service="payment-service",
        test_results={"status": "PASS", "details": "All unit & integration tests passed"},
    )
    assert gate_ready.status == ReleaseStatus.READY
    assert gate_ready.is_ready
    assert gate_ready.contract_checks_status == "PASS"

    # =========================================================================
    # Step 9: Release Evidence Generation
    # =========================================================================
    evidence_dir = tmp_path / "release-evidence"
    evidence = generate_evidence(recheck_report, gate_ready, output_dir=evidence_dir)

    assert evidence.verdict == "READY"
    assert evidence.evidence_id.startswith("cg-ev-")
    assert (evidence_dir / "contractguard-evidence.json").exists()
    assert (evidence_dir / "contractguard-report.md").exists()

    json_doc = json.loads((evidence_dir / "contractguard-evidence.json").read_text(encoding="utf-8"))
    assert json_doc["verdict"] == "READY"
    assert json_doc["evidence_id"] == evidence.evidence_id
    assert len(json_doc["compatible_consumers"]) == 3
    assert len(json_doc["affected_consumers"]) == 0
