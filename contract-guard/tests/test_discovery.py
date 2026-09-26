"""Tests for the workspace-wide consumer discovery and check functionality."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from contract_guard.discovery import discover_and_check, DiscoveryReport


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_producer(tmp_path: Path, field_name: str = "paymentAmount") -> Path:
    """Write a minimal producer OpenAPI YAML and return its path."""
    producer_dir = tmp_path / "payment-service" / "docs"
    producer_dir.mkdir(parents=True, exist_ok=True)
    p = producer_dir / "openapi.yaml"
    p.write_text(
        textwrap.dedent(f"""
        openapi: "3.1.0"
        info:
          title: Payment Service
          version: "1.0.0"
        paths:
          /api/payments/{{id}}:
            get:
              responses:
                "200":
                  content:
                    application/json:
                      schema:
                        type: object
                        required:
                          - id
                          - {field_name}
                          - status
                        properties:
                          id:
                            type: string
                          {field_name}:
                            type: number
                          status:
                            type: string
        """).lstrip("\n"),
        encoding="utf-8",
    )
    return p


def _make_consumer_dir(
    tmp_path: Path,
    service_name: str,
    field_name: str = "paymentAmount",
    producer_relative: str = "../payment-service/docs/openapi.yaml",
) -> Path:
    """
    Create a consumer directory with a contractguard.yaml and a consumer contract.
    Returns the consumer directory.
    """
    consumer_dir = tmp_path / service_name
    consumer_dir.mkdir(parents=True, exist_ok=True)
    contracts_dir = consumer_dir / "contracts"
    contracts_dir.mkdir(exist_ok=True)

    # Consumer contract
    contract = contracts_dir / "payment-service.yaml"
    contract.write_text(
        textwrap.dedent(f"""
        openapi: "3.1.0"
        info:
          title: Consumer Contract
          version: "1.0.0"
        paths:
          /api/payments/{{id}}:
            get:
              responses:
                "200":
                  content:
                    application/json:
                      schema:
                        type: object
                        required:
                          - id
                          - {field_name}
                          - status
                        properties:
                          id:
                            type: string
                          {field_name}:
                            type: number
                          status:
                            type: string
        """).lstrip("\n"),
        encoding="utf-8",
    )

    # contractguard.yaml
    config = consumer_dir / "contractguard.yaml"
    config.write_text(
        textwrap.dedent(f"""
        service: {service_name}
        dependencies:
          - service: payment-service
            consumer_contract: contracts/payment-service.yaml
            producer_contract: {producer_relative}
        """).lstrip("\n"),
        encoding="utf-8",
    )
    return consumer_dir


# ---------------------------------------------------------------------------
# Basic discovery
# ---------------------------------------------------------------------------

class TestDiscoverAndCheck:
    def test_finds_all_configs_in_workspace(self, tmp_path):
        _make_producer(tmp_path)
        _make_consumer_dir(tmp_path, "order-service")
        _make_consumer_dir(tmp_path, "reporting-service")

        report = discover_and_check(tmp_path)

        assert report.configs_found == 2
        assert set(report.consumers_checked) == {"order-service", "reporting-service"}

    def test_compatible_consumers_all_pass(self, tmp_path):
        _make_producer(tmp_path)
        _make_consumer_dir(tmp_path, "order-service")
        _make_consumer_dir(tmp_path, "reporting-service")

        report = discover_and_check(tmp_path)

        assert set(report.compatible_consumers) == {"order-service", "reporting-service"}
        assert report.affected_consumers == []
        assert report.breaking_findings == []

    def test_affected_consumer_detected(self, tmp_path):
        """Consumer expecting 'amount' against a producer using 'paymentAmount' is breaking."""
        _make_producer(tmp_path, field_name="paymentAmount")
        _make_consumer_dir(tmp_path, "order-service", field_name="paymentAmount")   # compatible
        _make_consumer_dir(tmp_path, "bad-client", field_name="amount")             # breaking

        report = discover_and_check(tmp_path)

        assert "order-service" in report.compatible_consumers
        assert "bad-client" in report.affected_consumers
        assert "bad-client" not in report.compatible_consumers
        assert len(report.breaking_findings) >= 1

    def test_breaking_findings_include_consumer_and_producer(self, tmp_path):
        _make_producer(tmp_path, field_name="paymentAmount")
        _make_consumer_dir(tmp_path, "bad-client", field_name="amount")

        report = discover_and_check(tmp_path)

        assert all("consumer_service" in f for f in report.breaking_findings)
        assert all("producer_service" in f for f in report.breaking_findings)
        assert all(f["consumer_service"] == "bad-client" for f in report.breaking_findings)
        assert all(f["producer_service"] == "payment-service" for f in report.breaking_findings)


# ---------------------------------------------------------------------------
# Producer filter
# ---------------------------------------------------------------------------

class TestProducerFilter:
    def test_filter_limits_checked_dependencies(self, tmp_path):
        _make_producer(tmp_path)
        consumer_dir = _make_consumer_dir(tmp_path, "order-service")

        # Add a second dependency in the same consumer pointing to a non-existent service
        config = consumer_dir / "contractguard.yaml"
        config.write_text(
            textwrap.dedent("""
            service: order-service
            dependencies:
              - service: payment-service
                consumer_contract: contracts/payment-service.yaml
                producer_contract: ../payment-service/docs/openapi.yaml
              - service: other-service
                consumer_contract: contracts/payment-service.yaml
                producer_contract: ../payment-service/docs/openapi.yaml
            """).lstrip("\n"),
            encoding="utf-8",
        )

        # Filter to only payment-service — the second dep is skipped entirely
        report = discover_and_check(tmp_path, producer_filter="payment-service")

        assert report.producer_filter == "payment-service"
        # Only one result (the payment-service dep); other-service is not checked
        assert all(r.producer_service == "payment-service" for r in report.results)

    def test_filter_none_checks_all(self, tmp_path):
        _make_producer(tmp_path)
        _make_consumer_dir(tmp_path, "order-service")

        report = discover_and_check(tmp_path, producer_filter=None)

        assert report.producer_filter is None
        assert len(report.results) == 1


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestDiscoveryErrors:
    def test_workspace_root_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            discover_and_check(tmp_path / "nonexistent")

    def test_workspace_root_not_a_directory(self, tmp_path):
        f = tmp_path / "file.txt"
        f.write_text("hello", encoding="utf-8")
        with pytest.raises(NotADirectoryError):
            discover_and_check(f)

    def test_empty_workspace_returns_empty_report(self, tmp_path):
        report = discover_and_check(tmp_path)

        assert report.configs_found == 0
        assert report.consumers_checked == []
        assert report.compatible_consumers == []
        assert report.affected_consumers == []
        assert report.breaking_findings == []

    def test_malformed_config_recorded_as_error(self, tmp_path):
        bad = tmp_path / "broken-service"
        bad.mkdir()
        cfg = bad / "contractguard.yaml"
        cfg.write_text("- not_a_mapping\n", encoding="utf-8")

        report = discover_and_check(tmp_path)

        # One config found, but it errors; consumer is not "compatible"
        assert report.configs_found == 1
        assert len(report.results) == 1
        assert report.results[0].error is not None
        assert report.compatible_consumers == []

    def test_missing_contract_file_recorded_as_error(self, tmp_path):
        consumer_dir = tmp_path / "order-service"
        consumer_dir.mkdir()
        cfg = consumer_dir / "contractguard.yaml"
        cfg.write_text(
            textwrap.dedent("""
            service: order-service
            dependencies:
              - service: payment-service
                consumer_contract: contracts/missing.yaml
                producer_contract: ../payment-service/docs/openapi.yaml
            """).lstrip("\n"),
            encoding="utf-8",
        )

        report = discover_and_check(tmp_path)

        assert len(report.results) == 1
        assert report.results[0].error is not None
        assert "order-service" in report.affected_consumers
        assert len(report.breaking_findings) == 1
        assert report.breaking_findings[0]["change_kind"] == "contract_error"

    def test_discover_contractguard_yml(self, tmp_path):
        """Verify discovery finds both .yaml and .yml files."""
        _make_producer(tmp_path)
        cdir = _make_consumer_dir(tmp_path, "yml-service")
        # Rename contractguard.yaml to contractguard.yml
        yaml_cfg = cdir / "contractguard.yaml"
        yml_cfg = cdir / "contractguard.yml"
        yaml_cfg.rename(yml_cfg)

        report = discover_and_check(tmp_path)
        assert "yml-service" in report.consumers_checked
        assert "yml-service" in report.compatible_consumers


# ---------------------------------------------------------------------------
# Report summary
# ---------------------------------------------------------------------------

class TestDiscoveryReportSummary:
    def test_summary_mentions_checked_count(self, tmp_path):
        _make_producer(tmp_path)
        _make_consumer_dir(tmp_path, "order-service")
        _make_consumer_dir(tmp_path, "reporting-service")

        report = discover_and_check(tmp_path)

        assert "2" in report.summary  # 2 consumers checked

    def test_summary_with_producer_filter(self, tmp_path):
        _make_producer(tmp_path)
        _make_consumer_dir(tmp_path, "order-service")

        report = discover_and_check(tmp_path, producer_filter="payment-service")

        assert "payment-service" in report.summary


# ---------------------------------------------------------------------------
# MCP tool: _run_discover
# ---------------------------------------------------------------------------

class TestRunDiscoverMcpTool:
    """Test the MCP-layer wrapper _run_discover via the full dispatch path."""

    def _dispatch(self, method: str, params: dict) -> dict:
        """Import and call _dispatch directly (avoids spinning up stdio)."""
        from contract_guard.mcp_server import _dispatch  # type: ignore[attr-defined]

        req = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        return _dispatch(req)

    def test_discover_tool_appears_in_tools_list(self):
        resp = self._dispatch("tools/list", {})
        tool_names = [t["name"] for t in resp["result"]["tools"]]
        assert "discover_and_check_consumers" in tool_names

    def test_discover_missing_workspace_root_is_error(self, tmp_path):
        resp = self._dispatch(
            "tools/call",
            {"name": "discover_and_check_consumers", "arguments": {}},
        )
        content = resp["result"]["content"][0]["text"]
        assert resp["result"]["isError"] is True
        assert "workspace_root" in content

    def test_discover_nonexistent_workspace_is_error(self, tmp_path):
        resp = self._dispatch(
            "tools/call",
            {
                "name": "discover_and_check_consumers",
                "arguments": {"workspace_root": str(tmp_path / "does_not_exist")},
            },
        )
        assert resp["result"]["isError"] is True

    def test_discover_empty_workspace_returns_report(self, tmp_path):
        resp = self._dispatch(
            "tools/call",
            {
                "name": "discover_and_check_consumers",
                "arguments": {"workspace_root": str(tmp_path)},
            },
        )
        assert "isError" not in resp["result"]
        payload = json.loads(resp["result"]["content"][0]["text"])
        assert payload["configs_found"] == 0
        assert payload["consumers_checked"] == []

    def test_discover_with_compatible_consumers(self, tmp_path):
        _make_producer(tmp_path)
        _make_consumer_dir(tmp_path, "order-service")
        _make_consumer_dir(tmp_path, "reporting-service")

        resp = self._dispatch(
            "tools/call",
            {
                "name": "discover_and_check_consumers",
                "arguments": {"workspace_root": str(tmp_path)},
            },
        )
        assert "isError" not in resp["result"]
        payload = json.loads(resp["result"]["content"][0]["text"])
        assert payload["configs_found"] == 2
        assert set(payload["compatible_consumers"]) == {"order-service", "reporting-service"}
        assert payload["affected_consumers"] == []
        assert payload["breaking_findings"] == []

    def test_discover_with_producer_filter_argument(self, tmp_path):
        _make_producer(tmp_path)
        _make_consumer_dir(tmp_path, "order-service")

        resp = self._dispatch(
            "tools/call",
            {
                "name": "discover_and_check_consumers",
                "arguments": {
                    "workspace_root": str(tmp_path),
                    "producer_filter": "payment-service",
                },
            },
        )
        payload = json.loads(resp["result"]["content"][0]["text"])
        assert payload["producer_filter"] == "payment-service"
        assert "order-service" in payload["compatible_consumers"]

    def test_discover_detects_breaking_consumer(self, tmp_path):
        _make_producer(tmp_path, field_name="paymentAmount")
        _make_consumer_dir(tmp_path, "order-service", field_name="paymentAmount")
        _make_consumer_dir(tmp_path, "bad-client", field_name="amount")

        resp = self._dispatch(
            "tools/call",
            {
                "name": "discover_and_check_consumers",
                "arguments": {"workspace_root": str(tmp_path)},
            },
        )
        payload = json.loads(resp["result"]["content"][0]["text"])
        assert "order-service" in payload["compatible_consumers"]
        assert "bad-client" in payload["affected_consumers"]
        assert len(payload["breaking_findings"]) >= 1
        finding = payload["breaking_findings"][0]
        assert finding["consumer_service"] == "bad-client"
        assert finding["severity"] == "breaking"
