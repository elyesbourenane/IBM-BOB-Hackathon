"""Tests for ContractGuard CLI commands."""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from contract_guard.__main__ import (
    _build_parser,
    cmd_analyze,
    cmd_check,
    cmd_compare,
    cmd_discover,
    cmd_evidence,
    cmd_git_diff,
    cmd_git_status,
    cmd_impact,
    cmd_pr,
    cmd_verify,
)


def test_cli_parser_commands():
    parser = _build_parser()
    args = parser.parse_args(["discover", "/workspace"])
    assert args.command == "discover"
    assert args.workspace == "/workspace"

    args = parser.parse_args(["impact", "/workspace", "--format", "json"])
    assert args.command == "impact"
    assert args.format == "json"

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

    # 2. Impact (text)
    args_impact = parser.parse_args(["impact", str(tmp_path), "--no-color"])
    rc = cmd_impact(args_impact)
    assert rc == 0
    out = capsys.readouterr().out
    assert "NO BLAST RADIUS - ALL CONSUMERS COMPATIBLE" in out

    # 3. Impact (json)
    args_impact_json = parser.parse_args(["impact", str(tmp_path), "--format", "json"])
    rc = cmd_impact(args_impact_json)
    assert rc == 0
    out = capsys.readouterr().out
    assert '"blast_radius_summary"' in out

    # 4. Verify
    args_verify = parser.parse_args(["verify", str(tmp_path), "--no-color"])
    rc = cmd_verify(args_verify)
    assert rc == 0
    out = capsys.readouterr().out
    assert "READY FOR RELEASE" in out

    # 5. Evidence
    args_evidence = parser.parse_args(["evidence", str(tmp_path), "--output-dir", str(tmp_path), "--no-color"])
    rc = cmd_evidence(args_evidence)
    assert rc == 0
    assert (tmp_path / "contractguard-evidence.json").exists()
    assert (tmp_path / "contractguard-report.md").exists()


def test_cli_compare_and_check(tmp_path: Path, capsys):
    prod = tmp_path / "prod.yaml"
    cons = tmp_path / "cons.yaml"
    prod.write_text("openapi: 3.0.0\npaths:\n  /p:\n    get:\n      responses:\n        '200':\n          content:\n            application/json:\n              schema:\n                type: object\n                properties:\n                  amt: {type: number}\n", encoding="utf-8")
    cons.write_text("openapi: 3.0.0\npaths:\n  /p:\n    get:\n      responses:\n        '200':\n          content:\n            application/json:\n              schema:\n                type: object\n                properties:\n                  amt: {type: number}\n", encoding="utf-8")

    parser = _build_parser()
    args_compare = parser.parse_args(["compare", str(prod), str(cons), "--no-color"])
    rc = cmd_compare(args_compare)
    assert rc == 0
    out = capsys.readouterr().out
    assert "COMPATIBLE" in out

    cfg = tmp_path / "contractguard.yaml"
    cfg.write_text(f"service: c\ndependencies:\n  - service: p\n    consumer_contract: {cons.name}\n    producer_contract: {prod.name}\n", encoding="utf-8")
    args_check = parser.parse_args(["check", str(cfg), "--no-color"])
    rc = cmd_check(args_check)
    assert rc == 0
    out = capsys.readouterr().out
    assert "COMPATIBLE" in out


def test_cli_git_status_and_diff(tmp_path: Path, capsys):
    parser = _build_parser()
    # 1. Non-git directory returns exit 2
    non_git = tmp_path / "non_git"
    non_git.mkdir()
    args_status = parser.parse_args(["git-status", str(non_git), "--no-color"])
    rc = cmd_git_status(args_status)
    assert rc == 2

    # 2. Git repo
    repo = tmp_path / "repo"
    repo.mkdir()
    import subprocess
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, check=True, capture_output=True)
    (repo / "openapi.yaml").write_text("openapi: 3.0.0", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)

    args_status_ok = parser.parse_args(["git-status", str(repo), "--no-color"])
    rc = cmd_git_status(args_status_ok)
    assert rc == 0
    out = capsys.readouterr().out
    assert "Git Repository Status" in out

    args_diff = parser.parse_args(["git-diff", str(repo), "--no-color"])
    rc = cmd_git_diff(args_diff)
    assert rc == 0


def test_cli_pr_command(tmp_path: Path, capsys):
    parser = _build_parser()
    import subprocess
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, check=True, capture_output=True)

    prod_dir = tmp_path / "payment-service" / "docs"
    prod_dir.mkdir(parents=True)
    (prod_dir / "openapi.yaml").write_text(
        "openapi: 3.1.0\ninfo:\n  title: P\n  version: '1.4.0'\npaths:\n  /api/payments/{id}:\n    get:\n      responses:\n        '200':\n          content:\n            application/json:\n              schema:\n                type: object\n                properties:\n                  id: {type: string}\n",
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
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, check=True, capture_output=True)

    # Text format
    args_pr = parser.parse_args(["pr", str(tmp_path), "--no-color"])
    rc = cmd_pr(args_pr)
    assert rc == 0
    out = capsys.readouterr().out
    assert "PR SAFE TO MERGE - READY" in out

    # Markdown format with output file
    out_md = tmp_path / "pr_report.md"
    args_pr_md = parser.parse_args(["pr", str(tmp_path), "--format", "markdown", "--output", str(out_md)])
    rc = cmd_pr(args_pr_md)
    assert rc == 0
    assert out_md.exists()
    assert "# ContractGuard PR Analysis" in out_md.read_text(encoding="utf-8")

    # JSON format
    args_pr_json = parser.parse_args(["pr", str(tmp_path), "--format", "json"])
    rc = cmd_pr(args_pr_json)
    assert rc == 0
    out_json = capsys.readouterr().out
    assert '"verdict": "READY"' in out_json


