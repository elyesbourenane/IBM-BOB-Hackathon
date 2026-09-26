"""Tests for the MCP server tools and JSON-RPC dispatch."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from contract_guard.ai.analyzer import ImpactAnalyzer
from contract_guard.ai.provider import LLMResponse
from contract_guard.ai.schema import AIAnalysisResult, AIImpactReport, ConsumerImpactAnalysis
from contract_guard.mcp_server import (
    _dispatch,
    TOOL_COMPARE,
    TOOL_READ_CONFIG,
    TOOL_DISCOVER,
    TOOL_BLAST_RADIUS,
    TOOL_ANALYZE,
    TOOL_VERIFY_RELEASE,
)


def test_mcp_tools_list():
    req = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    resp = _dispatch(req)
    assert resp is not None
    assert resp["id"] == 1
    tool_names = [t["name"] for t in resp["result"]["tools"]]
    assert TOOL_COMPARE in tool_names
    assert TOOL_READ_CONFIG in tool_names
    assert TOOL_DISCOVER in tool_names
    assert TOOL_BLAST_RADIUS in tool_names
    assert TOOL_ANALYZE in tool_names
    assert TOOL_VERIFY_RELEASE in tool_names


def test_mcp_call_unknown_tool():
    req = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {"name": "non_existent_tool", "arguments": {}},
    }
    resp = _dispatch(req)
    assert resp is not None
    assert "error" in resp
    assert resp["error"]["code"] == -32602


def test_mcp_call_analyze_contract_impact(tmp_path: Path):
    # Setup dummy producer and consumer in tmp_path
    prod_dir = tmp_path / "payment-service" / "docs"
    prod_dir.mkdir(parents=True)
    (prod_dir / "openapi.yaml").write_text(
        "openapi: 3.1.0\npaths:\n  /api/payments/{id}:\n    get:\n      responses:\n        '200':\n          content:\n            application/json:\n              schema:\n                type: object\n                properties:\n                  id: {type: string}\n",
        encoding="utf-8",
    )
    client_dir = tmp_path / "payment-client"
    client_dir.mkdir()
    (client_dir / "contracts").mkdir()
    (client_dir / "contracts" / "payment-service.yaml").write_text(
        "openapi: 3.1.0\npaths:\n  /api/payments/{id}:\n    get:\n      responses:\n        '200':\n          content:\n            application/json:\n              schema:\n                type: object\n                properties:\n                  id: {type: string}\n",
        encoding="utf-8",
    )
    (client_dir / "contractguard.yaml").write_text(
        "service: payment-client\ndependencies:\n  - service: payment-service\n    consumer_contract: contracts/payment-service.yaml\n    producer_contract: ../payment-service/docs/openapi.yaml\n",
        encoding="utf-8",
    )

    req = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {
            "name": TOOL_ANALYZE,
            "arguments": {"workspace_root": str(tmp_path)},
        },
    }
    resp = _dispatch(req)
    assert resp is not None
    assert "result" in resp
    content_text = resp["result"]["content"][0]["text"]
    data = json.loads(content_text)
    assert data["verdict"] == "compatible"
    assert data["configs_found"] == 1
    assert data["consumers_checked"] == ["payment-client"]
    assert "blast_radius" in data
    assert "ai_analysis" in data


def test_mcp_call_verify_release_safety(tmp_path: Path):
    # Compatible service
    prod_dir = tmp_path / "payment-service" / "docs"
    prod_dir.mkdir(parents=True)
    (prod_dir / "openapi.yaml").write_text(
        "openapi: 3.1.0\npaths:\n  /api/payments/{id}:\n    get:\n      responses:\n        '200':\n          content:\n            application/json:\n              schema:\n                type: object\n                properties:\n                  id: {type: string}\n",
        encoding="utf-8",
    )
    client_dir = tmp_path / "payment-client"
    client_dir.mkdir()
    (client_dir / "contracts").mkdir()
    (client_dir / "contracts" / "payment-service.yaml").write_text(
        "openapi: 3.1.0\npaths:\n  /api/payments/{id}:\n    get:\n      responses:\n        '200':\n          content:\n            application/json:\n              schema:\n                type: object\n                properties:\n                  id: {type: string}\n",
        encoding="utf-8",
    )
    (client_dir / "contractguard.yaml").write_text(
        "service: payment-client\ndependencies:\n  - service: payment-service\n    consumer_contract: contracts/payment-service.yaml\n    producer_contract: ../payment-service/docs/openapi.yaml\n",
        encoding="utf-8",
    )

    evidence_out = tmp_path / "evidence_out"
    req = {
        "jsonrpc": "2.0",
        "id": 4,
        "method": "tools/call",
        "params": {
            "name": TOOL_VERIFY_RELEASE,
            "arguments": {
                "workspace_root": str(tmp_path),
                "producer_service": "payment-service",
                "test_status": "PASS",
                "output_dir": str(evidence_out),
            },
        },
    }
    resp = _dispatch(req)
    assert resp is not None
    assert "result" in resp
    content_text = resp["result"]["content"][0]["text"]
    data = json.loads(content_text)
    assert data["status"] == "READY"
    assert data["is_ready"] is True
    assert (evidence_out / "contractguard-evidence.json").exists()
    assert (evidence_out / "contractguard-report.md").exists()


def test_mcp_call_get_blast_radius(tmp_path: Path):
    prod_dir = tmp_path / "payment-service" / "docs"
    prod_dir.mkdir(parents=True)
    (prod_dir / "openapi.yaml").write_text(
        "openapi: 3.1.0\npaths:\n  /api/payments/{id}:\n    get:\n      responses:\n        '200':\n          content:\n            application/json:\n              schema:\n                type: object\n                properties:\n                  id: {type: string}\n",
        encoding="utf-8",
    )
    client_dir = tmp_path / "payment-client"
    client_dir.mkdir()
    (client_dir / "contracts").mkdir()
    (client_dir / "contracts" / "payment-service.yaml").write_text(
        "openapi: 3.1.0\npaths:\n  /api/payments/{id}:\n    get:\n      responses:\n        '200':\n          content:\n            application/json:\n              schema:\n                type: object\n                properties:\n                  id: {type: string}\n",
        encoding="utf-8",
    )
    (client_dir / "contractguard.yaml").write_text(
        "service: payment-client\ndependencies:\n  - service: payment-service\n    consumer_contract: contracts/payment-service.yaml\n    producer_contract: ../payment-service/docs/openapi.yaml\n",
        encoding="utf-8",
    )

    req = {
        "jsonrpc": "2.0",
        "id": 5,
        "method": "tools/call",
        "params": {
            "name": TOOL_BLAST_RADIUS,
            "arguments": {"workspace_root": str(tmp_path)},
        },
    }
    resp = _dispatch(req)
    assert resp is not None
    assert "result" in resp
    content_text = resp["result"]["content"][0]["text"]
    data = json.loads(content_text)
    assert "blast_radius_summary" in data
    assert "impacts" in data
    assert data["blast_radius_summary"]["affected_services"] == []


def test_mcp_tool_errors():
    # Missing required argument
    req = {
        "jsonrpc": "2.0",
        "id": 6,
        "method": "tools/call",
        "params": {
            "name": TOOL_COMPARE,
            "arguments": {},
        },
    }
    resp = _dispatch(req)
    assert resp is not None
    assert resp["result"]["isError"] is True
    assert "Missing required argument" in resp["result"]["content"][0]["text"]

    # Non-existent workspace
    req_disc = {
        "jsonrpc": "2.0",
        "id": 7,
        "method": "tools/call",
        "params": {
            "name": TOOL_DISCOVER,
            "arguments": {"workspace_root": "/non/existent/path/xyz_123"},
        },
    }
    resp_disc = _dispatch(req_disc)
    assert resp_disc is not None
    assert resp_disc["result"]["isError"] is True


def test_mcp_lifecycle():
    init_req = {"jsonrpc": "2.0", "id": 10, "method": "initialize"}
    init_resp = _dispatch(init_req)
    assert init_resp is not None
    assert init_resp["result"]["serverInfo"]["name"] == "contract-guard"

    ping_req = {"jsonrpc": "2.0", "id": 11, "method": "ping"}
    ping_resp = _dispatch(ping_req)
    assert ping_resp is not None
    assert ping_resp["result"] == {}

