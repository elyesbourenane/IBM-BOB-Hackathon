"""
Phase 3B blast-radius, source/test impact, dependency graph, and CLI/MCP tests.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from contract_guard.__main__ import _build_parser, cmd_impact
from contract_guard.discovery import discover_and_check
from contract_guard.graph import build_dependency_graph
from contract_guard.impact import (
    BlastRadiusSummary,
    ConsumerImpact,
    scan_consumer_impact,
    summarize_blast_radius,
    _extract_field_tokens,
)
from contract_guard.mcp_server import _run_blast_radius
from contract_guard.mission import generate_repair_mission
from contract_guard.models import ChangeKind, Finding


def test_field_tokens_getters_setters_annotations_fixtures():
    tokens = _extract_field_tokens("paymentAmount")
    assert "paymentAmount" in tokens
    assert "PaymentAmount" in tokens
    assert "getPaymentAmount" in tokens
    assert "setPaymentAmount" in tokens
    assert "isPaymentAmount" in tokens
    assert '@JsonProperty("paymentAmount")' in tokens
    assert '"paymentAmount"' in tokens
    assert "payment_amount" in tokens
    assert "get_payment_amount" in tokens
    assert "set_payment_amount" in tokens

    # Deterministic sorting
    assert tokens == sorted(tokens)


def test_scan_consumer_impact_with_getter_setter_annotation_and_fixture(tmp_path: Path):
    consumer_dir = tmp_path / "payment-client"
    consumer_dir.mkdir()

    # 1. Source files with getter and @JsonProperty
    src_main = consumer_dir / "src" / "main" / "java"
    src_main.mkdir(parents=True)

    model_file = src_main / "PaymentResponse.java"
    model_file.write_text(
        textwrap.dedent("""
        public class PaymentResponse {
            @JsonProperty("paymentAmount")
            private BigDecimal paymentAmount;

            public BigDecimal getPaymentAmount() {
                return this.paymentAmount;
            }

            public void setPaymentAmount(BigDecimal paymentAmount) {
                this.paymentAmount = paymentAmount;
            }
        }
        """).strip(),
        encoding="utf-8",
    )

    display_service = src_main / "PaymentDisplayService.java"
    display_service.write_text(
        textwrap.dedent("""
        public class PaymentDisplayService {
            public String format(PaymentResponse resp) {
                return "$" + resp.getPaymentAmount();
            }
        }
        """).strip(),
        encoding="utf-8",
    )

    # Likely source (mentions payments endpoint token, but not field)
    client_file = src_main / "PaymentClient.java"
    client_file.write_text(
        textwrap.dedent("""
        public class PaymentClient {
            public PaymentResponse getPayment(String id) {
                return callApi("/api/payments/" + id);
            }
        }
        """).strip(),
        encoding="utf-8",
    )

    # 2. Test files and fixtures
    src_test = consumer_dir / "src" / "test" / "java"
    src_test.mkdir(parents=True)

    test_file = src_test / "PaymentClientTest.java"
    test_file.write_text(
        "public class PaymentClientTest { void test() { assertEquals(10, resp.getPaymentAmount()); } }",
        encoding="utf-8",
    )

    fixture_dir = consumer_dir / "src" / "test" / "resources" / "fixtures"
    fixture_dir.mkdir(parents=True)
    fixture_file = fixture_dir / "payment_sample.json"
    fixture_file.write_text(
        '{\n  "id": "pay-123",\n  "paymentAmount": 99.95\n}',
        encoding="utf-8",
    )

    # Contract
    contracts_dir = consumer_dir / "contracts"
    contracts_dir.mkdir()
    consumer_contract = contracts_dir / "payment-service.yaml"
    consumer_contract.write_text("openapi: 3.1.0", encoding="utf-8")

    producer_contract = tmp_path / "payment-service" / "docs" / "openapi.yaml"
    producer_contract.parent.mkdir(parents=True)
    producer_contract.write_text("openapi: 3.1.0", encoding="utf-8")

    finding = Finding(
        endpoint="GET /api/payments/{id}",
        affected_field="paymentAmount",
        change_kind=ChangeKind.FIELD_RENAMED,
        detail="Consumer expects 'paymentAmount' but producer now uses 'totalAmount'",
    )

    impact = scan_consumer_impact(
        consumer_dir=consumer_dir,
        consumer_service="payment-client",
        producer_service="payment-service",
        consumer_contract=consumer_contract,
        producer_contract=producer_contract,
        finding=finding,
    )

    # Confirmed source: PaymentDisplayService.java, PaymentResponse.java
    conf_src = [f.replace("\\", "/") for f in impact.confirmed_source_files]
    assert any("PaymentResponse.java" in f for f in conf_src)
    assert any("PaymentDisplayService.java" in f for f in conf_src)
    assert not any("PaymentClient.java" in f for f in conf_src)

    # Likely source: PaymentClient.java
    likely_src = [f.replace("\\", "/") for f in impact.likely_source_files]
    assert any("PaymentClient.java" in f for f in likely_src)

    # Confirmed test: PaymentClientTest.java AND payment_sample.json fixture
    conf_test = [f.replace("\\", "/") for f in impact.confirmed_test_files]
    assert any("PaymentClientTest.java" in f for f in conf_test)
    assert any("payment_sample.json" in f for f in conf_test)

    # Deterministic sorting
    assert impact.confirmed_source_files == sorted(impact.confirmed_source_files)
    assert impact.confirmed_test_files == sorted(impact.confirmed_test_files)


def test_blast_radius_summary_contract_only_consumers():
    # 3 consumers: 1 with code, 2 contract-only
    imp1 = ConsumerImpact(
        consumer_service="payment-client",
        producer_service="payment-service",
        endpoint="GET /api/payments/{id}",
        affected_field="paymentAmount",
        change_kind="field_renamed",
        severity="breaking",
        producer_contract="prod.yaml",
        consumer_contract="cons.yaml",
        contract_path="contracts/payment-service.yaml",
        detail="renamed",
        reason="breaking",
        confirmed_source_files=["src/main/PaymentResponse.java"],
        confirmed_test_files=["src/test/PaymentTest.java"],
    )
    imp2 = ConsumerImpact(
        consumer_service="order-service",
        producer_service="payment-service",
        endpoint="GET /api/payments/{id}",
        affected_field="paymentAmount",
        change_kind="field_renamed",
        severity="breaking",
        producer_contract="prod.yaml",
        consumer_contract="cons.yaml",
        contract_path="contracts/payment-service.yaml",
        detail="renamed",
        reason="breaking",
        confirmed_source_files=[],
        confirmed_test_files=[],
    )
    imp3 = ConsumerImpact(
        consumer_service="reporting-service",
        producer_service="payment-service",
        endpoint="GET /api/payments/{id}",
        affected_field="paymentAmount",
        change_kind="field_renamed",
        severity="breaking",
        producer_contract="prod.yaml",
        consumer_contract="cons.yaml",
        contract_path="contracts/payment-service.yaml",
        detail="renamed",
        reason="breaking",
        confirmed_source_files=[],
        confirmed_test_files=[],
    )

    summary = summarize_blast_radius([imp1, imp2, imp3], direct_consumers=3, transitive_consumers=0)

    assert summary.direct_consumers == 3
    assert summary.affected_consumers == 3
    assert summary.contract_only_consumers == 2
    assert len(summary.confirmed_source_files) == 1
    assert len(summary.confirmed_test_files) == 1
    assert summary.transitive_consumers == 0

    metrics = summary.summary_metrics()
    assert metrics["direct_consumers"] == 3
    assert metrics["affected_consumers"] == 3
    assert metrics["contract_only_consumers"] == 2
    assert metrics["transitive_consumers"] == 0


def test_end_to_end_workspace_blast_radius_and_cli(tmp_path: Path, capsys):
    ws = tmp_path / "workspace"
    ws.mkdir()

    # Producer: payment-service with breaking contract change
    prod_dir = ws / "payment-service" / "docs"
    prod_dir.mkdir(parents=True)
    prod_contract = prod_dir / "openapi.yaml"
    prod_contract.write_text(
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
                        required: [id, totalAmount]
                        properties:
                          id: { type: string }
                          totalAmount: { type: number }
        """).strip(),
        encoding="utf-8",
    )

    # Consumer 1: payment-client (has source and test references)
    c1_dir = ws / "payment-client"
    (c1_dir / "contracts").mkdir(parents=True)
    (c1_dir / "contracts" / "payment-service.yaml").write_text(
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
                        required: [id, paymentAmount]
                        properties:
                          id: { type: string }
                          paymentAmount: { type: number }
        """).strip(),
        encoding="utf-8",
    )
    (c1_dir / "contractguard.yaml").write_text(
        "service: payment-client\ndependencies:\n  - service: payment-service\n    consumer_contract: contracts/payment-service.yaml\n    producer_contract: ../payment-service/docs/openapi.yaml\n",
        encoding="utf-8",
    )
    c1_src = c1_dir / "src" / "main" / "java"
    c1_src.mkdir(parents=True)
    (c1_src / "PaymentResponse.java").write_text(
        "public class PaymentResponse { private BigDecimal paymentAmount; public BigDecimal getPaymentAmount() { return paymentAmount; } }",
        encoding="utf-8",
    )
    c1_test = c1_dir / "src" / "test" / "java"
    c1_test.mkdir(parents=True)
    (c1_test / "PaymentResponseTest.java").write_text(
        "public class PaymentResponseTest { void test() { assertEquals(10, resp.getPaymentAmount()); } }",
        encoding="utf-8",
    )

    # Consumer 2: order-service (contract-only)
    c2_dir = ws / "order-service"
    (c2_dir / "contracts").mkdir(parents=True)
    (c2_dir / "contracts" / "payment-service.yaml").write_text(
        (c1_dir / "contracts" / "payment-service.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (c2_dir / "contractguard.yaml").write_text(
        "service: order-service\ndependencies:\n  - service: payment-service\n    consumer_contract: contracts/payment-service.yaml\n    producer_contract: ../payment-service/docs/openapi.yaml\n",
        encoding="utf-8",
    )

    # Consumer 3: reporting-service (contract-only)
    c3_dir = ws / "reporting-service"
    (c3_dir / "contracts").mkdir(parents=True)
    (c3_dir / "contracts" / "payment-service.yaml").write_text(
        (c1_dir / "contracts" / "payment-service.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (c3_dir / "contractguard.yaml").write_text(
        "service: reporting-service\ndependencies:\n  - service: payment-service\n    consumer_contract: contracts/payment-service.yaml\n    producer_contract: ../payment-service/docs/openapi.yaml\n",
        encoding="utf-8",
    )

    # 1. Run discover_and_check
    report = discover_and_check(ws, producer_filter="payment-service")
    assert len(report.consumers_checked) == 3
    assert len(report.affected_consumers) == 3
    assert report.blast_radius_summary.direct_consumers == 3
    assert report.blast_radius_summary.contract_only_consumers == 2
    assert len(report.blast_radius_summary.confirmed_source_files) == 1
    assert len(report.blast_radius_summary.confirmed_test_files) == 1

    # 2. Repair Mission Integration
    mission = generate_repair_mission(ws, producer_filter="payment-service")
    assert len(mission.affected_consumers) == 3
    client_mission = next(c for c in mission.affected_consumers if c.service == "payment-client")
    assert len(client_mission.confirmed_source_files) == 1
    assert len(client_mission.confirmed_test_files) == 1
    order_mission = next(c for c in mission.affected_consumers if c.service == "order-service")
    assert len(order_mission.confirmed_source_files) == 0
    assert len(order_mission.confirmed_test_files) == 0

    # 3. CLI Impact - Text format
    parser = _build_parser()
    args_text = parser.parse_args(["impact", str(ws), "--producer", "payment-service", "--format", "text", "--no-color"])
    rc_text = cmd_impact(args_text)
    assert rc_text == 1
    out_text = capsys.readouterr().out
    assert "CONTRACTGUARD — BLAST RADIUS" in out_text
    assert "API CHANGE" in out_text
    assert "DIRECT CONSUMERS\n3" in out_text
    assert "AFFECTED CONSUMERS\n3" in out_text
    assert "CONTRACT-ONLY CONSUMERS\n2" in out_text
    assert "CONFIRMED SOURCE FILES\n1" in out_text
    assert "CONFIRMED TEST FILES\n1" in out_text
    assert "TRANSITIVE CONSUMERS\n0" in out_text

    # 4. CLI Impact - JSON format
    args_json = parser.parse_args(["impact", str(ws), "--producer", "payment-service", "--format", "json"])
    rc_json = cmd_impact(args_json)
    assert rc_json == 1
    out_json = capsys.readouterr().out
    data = json.loads(out_json)
    assert data["direct_consumers"] == 3
    assert data["affected_consumers"] == 3
    assert data["contract_only_consumers"] == 2
    assert data["confirmed_source_files"] == 1
    assert data["confirmed_test_files"] == 1
    assert data["transitive_consumers"] == 0
    assert "dependency_graph" in data
    assert data["dependency_graph"]["total_nodes"] == 4
    assert data["dependency_graph"]["total_edges"] == 3

    # 5. CLI Impact - Markdown format
    args_md = parser.parse_args(["impact", str(ws), "--producer", "payment-service", "--format", "markdown"])
    rc_md = cmd_impact(args_md)
    assert rc_md == 1
    out_md = capsys.readouterr().out
    assert "# CONTRACTGUARD — BLAST RADIUS" in out_md
    assert "| Direct Consumers | 3 |" in out_md
    assert "| Contract-Only Consumers | 2 |" in out_md
    assert "### Confirmed Source Files" in out_md
    assert "PaymentResponse.java" in out_md

    # 6. MCP get_blast_radius
    mcp_res = _run_blast_radius({"workspace_root": str(ws), "producer_filter": "payment-service"})
    assert "content" in mcp_res
    mcp_data = json.loads(mcp_res["content"][0]["text"])
    assert "dependency_graph" in mcp_data
    assert mcp_data["blast_radius_summary"]["direct_consumers"] == 3
    assert mcp_data["blast_radius_summary"]["contract_only_consumers"] == 2
