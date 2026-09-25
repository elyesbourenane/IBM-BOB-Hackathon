"""Tests for ContractGuard CLI commands."""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from contract_guard.__main__ import _build_parser, cmd_discover, cmd_verify, cmd_evidence, cmd_analyze


def test_cli_parser_commands():
    parser = _build_parser()
    args = parser.parse_args(["discover", "/workspace"])
    assert args.command == "discover"
    assert args.workspace == "/workspace"

    args = parser.parse_args(["analyze", "/workspace"])
    assert args.command == "analyze"

    args = parser.parse_args(["verify", "/workspace", "--test-status", "PASS"])
    assert args.command == "verify"
    assert args.test_status == "PASS"

    args = parser.parse_args(["evidence", "/workspace", "--output-dir", "/out"])
    assert args.command == "evidence"
    assert args.output_dir == "/out"


def test_cli_discover_and_verify_e2e(tmp_path: Path, capsys):
    # Setup compatible producer and consumer
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

    # 1. Discover
    parser = _build_parser()
    args_discover = parser.parse_args(["discover", str(tmp_path), "--no-color"])
    rc = cmd_discover(args_discover)
    assert rc == 0
    out = capsys.readouterr().out
    assert "ALL CONSUMERS COMPATIBLE" in out

    # 2. Verify
    args_verify = parser.parse_args(["verify", str(tmp_path), "--no-color"])
    rc = cmd_verify(args_verify)
    assert rc == 0
    out = capsys.readouterr().out
    assert "READY FOR RELEASE" in out

    # 3. Evidence
    args_evidence = parser.parse_args(["evidence", str(tmp_path), "--output-dir", str(tmp_path), "--no-color"])
    rc = cmd_evidence(args_evidence)
    assert rc == 0
    assert (tmp_path / "contractguard-evidence.json").exists()
    assert (tmp_path / "contractguard-report.md").exists()
