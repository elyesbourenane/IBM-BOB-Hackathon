"""
MCP stdio server for contract-guard.

Implements the Model Context Protocol (JSON-RPC 2.0 over stdin/stdout) with
a single tool: ``compare_contracts``.

No external MCP SDK required — the protocol is a thin JSON-RPC 2.0 framing
layer, which we implement directly so the server runs on any Python >= 3.9.

Wire format
-----------
Each message is a JSON object followed by a newline (\\n).  The server reads
from stdin and writes to stdout.  ALL diagnostic/logging output must go to
stderr so it never corrupts the protocol channel.

Usage (stdio transport, spawned by Bob)
---------------------------------------
    python -m contract_guard.mcp_server

Or via the installed console script:
    contract-guard-mcp
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path
from typing import Any

from .ai import ImpactAnalyzer
from .comparator import Comparator
from .config import load_config
from .discovery import discover_and_check, DiscoveryReport, ConsumerResult
from .evidence import evaluate_release_gate, generate_evidence
from .models import ComparisonReport, Finding


# ---------------------------------------------------------------------------
# Protocol helpers
# ---------------------------------------------------------------------------

SERVER_INFO = {"name": "contract-guard", "version": "0.1.0"}

PROTOCOL_VERSION = "2024-11-05"

TOOL_COMPARE = "compare_contracts"
TOOL_READ_CONFIG = "read_contractguard_config"
TOOL_DISCOVER = "discover_and_check_consumers"
TOOL_BLAST_RADIUS = "get_blast_radius"
TOOL_ANALYZE = "analyze_contract_impact"
TOOL_VERIFY_RELEASE = "verify_release_safety"

TOOL_DEFINITION_COMPARE = {
    "name": TOOL_COMPARE,
    "description": (
        "Deterministically check whether a producer OpenAPI contract is "
        "backwards-compatible with a consumer OpenAPI contract. "
        "Returns a structured JSON report with a verdict (compatible / breaking) "
        "and a list of findings, each with an endpoint, field name, change kind, "
        "detail message, and severity."
    ),
    "inputSchema": {
        "type": "object",
        "required": ["producer_path", "consumer_path"],
        "properties": {
            "producer_path": {
                "type": "string",
                "description": (
                    "Absolute or workspace-relative path to the producer OpenAPI YAML file."
                ),
            },
            "consumer_path": {
                "type": "string",
                "description": (
                    "Absolute or workspace-relative path to the consumer OpenAPI YAML file."
                ),
            },
        },
    },
}

TOOL_DEFINITION_READ_CONFIG = {
    "name": TOOL_READ_CONFIG,
    "description": (
        "Read a contractguard.yaml consumer configuration file and return the "
        "declared service name and dependency relationships. "
        "Each dependency entry includes the producer service name and the "
        "resolved absolute paths to both the consumer contract and the producer "
        "contract, ready to pass directly to compare_contracts."
    ),
    "inputSchema": {
        "type": "object",
        "required": ["config_path"],
        "properties": {
            "config_path": {
                "type": "string",
                "description": (
                    "Absolute or workspace-relative path to a contractguard.yaml file."
                ),
            },
        },
    },
}


TOOL_DEFINITION_DISCOVER = {
    "name": TOOL_DISCOVER,
    "description": (
        "Discover all contractguard.yaml files under a workspace root directory "
        "and check every declared consumer dependency against its producer "
        "OpenAPI contract. "
        "Returns a structured report with: producer filter used, number of config "
        "files found, consumers checked, compatible consumers, affected consumers, "
        "and a flat list of all breaking findings across every consumer."
    ),
    "inputSchema": {
        "type": "object",
        "required": ["workspace_root"],
        "properties": {
            "workspace_root": {
                "type": "string",
                "description": (
                    "Absolute or workspace-relative path to the directory to search "
                    "recursively for contractguard.yaml files."
                ),
            },
            "producer_filter": {
                "type": "string",
                "description": (
                    "Optional. When provided, only dependencies whose service name "
                    "matches this value are checked. Omit to check all dependencies."
                ),
            },
        },
    },
}

TOOL_DEFINITION_BLAST_RADIUS = {
    "name": TOOL_BLAST_RADIUS,
    "description": (
        "Discover consumers and compute deterministic contract blast radius without "
        "invoking external AI services. Returns aggregate summary of affected services, "
        "contracts, endpoints, fields, and confirmed/likely source and test files."
    ),
    "inputSchema": {
        "type": "object",
        "required": ["workspace_root"],
        "properties": {
            "workspace_root": {
                "type": "string",
                "description": (
                    "Absolute or workspace-relative path to the directory to search "
                    "recursively for contractguard.yaml files."
                ),
            },
            "producer_filter": {
                "type": "string",
                "description": (
                    "Optional. When provided, only dependencies whose service name "
                    "matches this value are checked. Omit to check all dependencies."
                ),
            },
        },
    },
}

TOOL_DEFINITION_ANALYZE = {
    "name": TOOL_ANALYZE,
    "description": (
        "Discover consumers, compute deterministic contract blast radius, and generate "
        "an AI-assisted impact analysis and actionable repair plan for IBM Bob. "
        "Distinguishes confirmed affected files from inferred/likely impact."
    ),
    "inputSchema": {
        "type": "object",
        "required": ["workspace_root"],
        "properties": {
            "workspace_root": {
                "type": "string",
                "description": (
                    "Absolute or workspace-relative path to the directory to search "
                    "recursively for contractguard.yaml files."
                ),
            },
            "producer_filter": {
                "type": "string",
                "description": (
                    "Optional. When provided, only dependencies whose service name "
                    "matches this value are checked. Omit to check all dependencies."
                ),
            },
        },
    },
}

TOOL_DEFINITION_VERIFY_RELEASE = {
    "name": TOOL_VERIFY_RELEASE,
    "description": (
        "Deterministically verify whether an API release is safe (READY or BLOCKED), "
        "and generate reproducible JSON and Markdown release evidence reports."
    ),
    "inputSchema": {
        "type": "object",
        "required": ["workspace_root"],
        "properties": {
            "workspace_root": {
                "type": "string",
                "description": (
                    "Absolute or workspace-relative path to the directory to search "
                    "recursively for contractguard.yaml files."
                ),
            },
            "producer_service": {
                "type": "string",
                "description": (
                    "Optional producer service name being released (default: 'payment-service')."
                ),
            },
            "test_status": {
                "type": "string",
                "description": (
                    "Optional status of automated tests ('PASS' or 'FAIL', default: 'PASS')."
                ),
            },
            "output_dir": {
                "type": "string",
                "description": (
                    "Optional directory path to write contractguard-evidence.json and contractguard-report.md."
                ),
            },
        },
    },
}


def _send(obj: dict[str, Any]) -> None:
    """Write a single JSON-RPC message to stdout."""
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def _error_response(req_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _ok_response(req_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


# ---------------------------------------------------------------------------
# Tool logic
# ---------------------------------------------------------------------------

def _finding_to_dict(f: Finding) -> dict[str, Any]:
    return {
        "endpoint": f.endpoint,
        "affected_field": f.affected_field,
        "change_kind": f.change_kind.value,
        "severity": f.severity.value,
        "detail": f.detail,
        "reason": f.reason,
    }


def _report_to_dict(report: ComparisonReport) -> dict[str, Any]:
    return {
        "verdict": report.verdict,
        "is_compatible": report.is_compatible,
        "findings": [_finding_to_dict(f) for f in report.findings],
        "breaking_count": sum(1 for f in report.findings if f.is_breaking),
        "compatible_count": sum(1 for f in report.findings if not f.is_breaking),
    }


def _run_compare(arguments: dict[str, Any]) -> dict[str, Any]:
    """
    Execute the compare_contracts tool and return the MCP tool-call result dict.
    Returns ``isError: true`` for any recoverable failure so the agent can self-correct.
    """
    producer_path = arguments.get("producer_path", "")
    consumer_path = arguments.get("consumer_path", "")

    if not producer_path:
        return {
            "content": [{"type": "text", "text": "Missing required argument: producer_path"}],
            "isError": True,
        }
    if not consumer_path:
        return {
            "content": [{"type": "text", "text": "Missing required argument: consumer_path"}],
            "isError": True,
        }

    try:
        report = Comparator(producer_path, consumer_path).compare()
    except FileNotFoundError as exc:
        return {
            "content": [{"type": "text", "text": f"File not found: {exc}"}],
            "isError": True,
        }
    except (ValueError, KeyError) as exc:
        return {
            "content": [{"type": "text", "text": f"Invalid contract: {exc}"}],
            "isError": True,
        }
    except Exception as exc:  # pragma: no cover
        return {
            "content": [{"type": "text", "text": f"Unexpected error: {exc}"}],
            "isError": True,
        }

    payload = _report_to_dict(report)
    return {
        "content": [{"type": "text", "text": json.dumps(payload, indent=2)}],
    }


def _run_read_config(arguments: dict[str, Any]) -> dict[str, Any]:
    """
    Execute the read_contractguard_config tool.
    Returns the parsed config as JSON, with all contract paths already resolved
    to absolute paths so they can be passed directly to compare_contracts.
    """
    config_path = arguments.get("config_path", "")
    if not config_path:
        return {
            "content": [{"type": "text", "text": "Missing required argument: config_path"}],
            "isError": True,
        }

    try:
        config = load_config(config_path)
    except FileNotFoundError as exc:
        return {
            "content": [{"type": "text", "text": f"File not found: {exc}"}],
            "isError": True,
        }
    except ValueError as exc:
        return {
            "content": [{"type": "text", "text": f"Invalid config: {exc}"}],
            "isError": True,
        }

    payload = {
        "service": config.service,
        "dependencies": [
            {
                "service": dep.service,
                "consumer_contract": str(dep.consumer_contract),
                "producer_contract": str(dep.producer_contract),
            }
            for dep in config.dependencies
        ],
    }
    return {
        "content": [{"type": "text", "text": json.dumps(payload, indent=2)}],
    }


def _run_discover(arguments: dict[str, Any]) -> dict[str, Any]:
    """
    Execute the discover_and_check_consumers tool.
    Walks *workspace_root* for contractguard.yaml files, runs compare_contracts
    for every dependency, and returns a structured summary report.
    """
    workspace_root = arguments.get("workspace_root", "")
    if not workspace_root:
        return {
            "content": [{"type": "text", "text": "Missing required argument: workspace_root"}],
            "isError": True,
        }
    producer_filter: str | None = arguments.get("producer_filter") or None

    try:
        report = discover_and_check(workspace_root, producer_filter=producer_filter)
    except FileNotFoundError as exc:
        return {
            "content": [{"type": "text", "text": f"Workspace root not found: {exc}"}],
            "isError": True,
        }
    except NotADirectoryError as exc:
        return {
            "content": [{"type": "text", "text": f"Not a directory: {exc}"}],
            "isError": True,
        }
    except Exception as exc:  # pragma: no cover
        return {
            "content": [{"type": "text", "text": f"Unexpected error: {exc}"}],
            "isError": True,
        }

    payload = {
        "workspace_root": report.workspace_root,
        "producer_filter": report.producer_filter,
        "configs_found": report.configs_found,
        "consumers_checked": report.consumers_checked,
        "compatible_consumers": report.compatible_consumers,
        "affected_consumers": report.affected_consumers,
        "breaking_findings": report.breaking_findings,
        "blast_radius_summary": report.blast_radius_summary.to_dict(),
        "blast_radius": [imp.to_dict() for imp in report.impacts],
        "summary": report.summary,
        "results": [
            {
                "consumer_service": r.consumer_service,
                "producer_service": r.producer_service,
                "consumer_contract": r.consumer_contract,
                "producer_contract": r.producer_contract,
                "verdict": r.verdict,
                "is_compatible": r.is_compatible,
                "error": r.error,
                "findings": [_finding_to_dict(f) for f in r.findings],
            }
            for r in report.results
        ],
    }
    return {
        "content": [{"type": "text", "text": json.dumps(payload, indent=2)}],
    }


def _run_blast_radius(arguments: dict[str, Any]) -> dict[str, Any]:
    """
    Execute the get_blast_radius tool.
    Computes deterministic blast-radius across all discovered consumers.
    """
    workspace_root = arguments.get("workspace_root", "")
    if not workspace_root:
        return {
            "content": [{"type": "text", "text": "Missing required argument: workspace_root"}],
            "isError": True,
        }
    producer_filter: str | None = arguments.get("producer_filter") or None

    try:
        report = discover_and_check(workspace_root, producer_filter=producer_filter)
    except FileNotFoundError as exc:
        return {
            "content": [{"type": "text", "text": f"Workspace root not found: {exc}"}],
            "isError": True,
        }
    except NotADirectoryError as exc:
        return {
            "content": [{"type": "text", "text": f"Not a directory: {exc}"}],
            "isError": True,
        }
    except Exception as exc:  # pragma: no cover
        return {
            "content": [{"type": "text", "text": f"Unexpected error during blast-radius analysis: {exc}"}],
            "isError": True,
        }

    payload = {
        "workspace_root": report.workspace_root,
        "producer_filter": report.producer_filter,
        "summary": report.summary,
        "blast_radius_summary": report.blast_radius_summary.to_dict(),
        "impacts": [imp.to_dict() for imp in report.impacts],
    }
    return {
        "content": [{"type": "text", "text": json.dumps(payload, indent=2)}],
    }


def _run_analyze(
    arguments: dict[str, Any],
    analyzer: ImpactAnalyzer | None = None,
) -> dict[str, Any]:
    """
    Execute the analyze_contract_impact tool.
    Discovers consumers, computes deterministic blast radius, and runs AI-assisted
    impact analysis and repair plan generation.
    """
    workspace_root = arguments.get("workspace_root", "")
    if not workspace_root:
        return {
            "content": [{"type": "text", "text": "Missing required argument: workspace_root"}],
            "isError": True,
        }
    producer_filter: str | None = arguments.get("producer_filter") or None

    try:
        report = discover_and_check(workspace_root, producer_filter=producer_filter)
    except FileNotFoundError as exc:
        return {
            "content": [{"type": "text", "text": f"Workspace root not found: {exc}"}],
            "isError": True,
        }
    except NotADirectoryError as exc:
        return {
            "content": [{"type": "text", "text": f"Not a directory: {exc}"}],
            "isError": True,
        }
    except Exception as exc:  # pragma: no cover
        return {
            "content": [{"type": "text", "text": f"Unexpected error during discovery: {exc}"}],
            "isError": True,
        }

    if analyzer is None:
        analyzer = ImpactAnalyzer()
    ai_report = analyzer.analyze(report)

    analysis_dict: dict[str, Any] | None = None
    if ai_report.analysis:
        analysis_dict = {
            "summary": ai_report.analysis.summary,
            "breaking_change_explanation": ai_report.analysis.breaking_change_explanation,
            "impact": [imp.model_dump() for imp in ai_report.analysis.impact],
            "repair_plan": ai_report.analysis.repair_plan,
            "migration_options": ai_report.analysis.migration_options,
        }

    payload = {
        "verdict": "compatible" if not report.affected_consumers else "breaking",
        "workspace_root": report.workspace_root,
        "producer_filter": report.producer_filter,
        "configs_found": report.configs_found,
        "consumers_checked": report.consumers_checked,
        "compatible_consumers": report.compatible_consumers,
        "affected_consumers": report.affected_consumers,
        "breaking_findings": report.breaking_findings,
        "blast_radius_summary": report.blast_radius_summary.to_dict(),
        "blast_radius": [imp.to_dict() for imp in report.impacts],
        "ai_analysis": {
            "status": ai_report.status,
            "provider": ai_report.provider,
            "model": ai_report.model,
            "analysis": analysis_dict,
            "error_message": ai_report.error_message,
        },
    }
    return {
        "content": [{"type": "text", "text": json.dumps(payload, indent=2)}],
    }


def _run_verify_release(arguments: dict[str, Any]) -> dict[str, Any]:
    """
    Execute the verify_release_safety tool.
    Deterministically evaluates release safety gate (READY or BLOCKED) and generates
    reproducible release evidence audit artifacts.
    """
    workspace_root = arguments.get("workspace_root", "")
    if not workspace_root:
        return {
            "content": [{"type": "text", "text": "Missing required argument: workspace_root"}],
            "isError": True,
        }
    producer_service = arguments.get("producer_service", "payment-service")
    test_status = arguments.get("test_status", "PASS")
    output_dir = arguments.get("output_dir")

    try:
        report = discover_and_check(workspace_root, producer_filter=producer_service)
    except FileNotFoundError as exc:
        return {
            "content": [{"type": "text", "text": f"Workspace root not found: {exc}"}],
            "isError": True,
        }
    except NotADirectoryError as exc:
        return {
            "content": [{"type": "text", "text": f"Not a directory: {exc}"}],
            "isError": True,
        }
    except Exception as exc:  # pragma: no cover
        return {
            "content": [{"type": "text", "text": f"Unexpected error: {exc}"}],
            "isError": True,
        }

    verification = evaluate_release_gate(
        report=report,
        producer_service=producer_service,
        test_results={"status": test_status, "details": f"Automated tests: {test_status}"},
    )
    evidence = generate_evidence(report, verification, output_dir=output_dir)

    payload = {
        "status": verification.status.value,
        "is_ready": verification.is_ready,
        "producer_service": verification.producer_service,
        "evidence_id": evidence.evidence_id,
        "contract_checks_status": verification.contract_checks_status,
        "breaking_changes_count": verification.breaking_changes_count,
        "consumers_checked": verification.consumers_checked,
        "compatible_consumers": verification.compatible_consumers,
        "affected_consumers": verification.affected_consumers,
        "reasons": verification.reasons,
        "evidence_files": {
            "json": str(Path(output_dir) / "contractguard-evidence.json") if output_dir else None,
            "markdown": str(Path(output_dir) / "contractguard-report.md") if output_dir else None,
        } if output_dir else None,
    }
    return {
        "content": [{"type": "text", "text": json.dumps(payload, indent=2)}],
    }


# ---------------------------------------------------------------------------
# Request dispatcher
# ---------------------------------------------------------------------------

def _dispatch(
    message: dict[str, Any],
    analyzer: ImpactAnalyzer | None = None,
) -> dict[str, Any] | None:
    """
    Handle one JSON-RPC request and return the response dict, or None for
    notifications (no ``id`` field) that need no response.
    """
    method = message.get("method", "")
    req_id = message.get("id")  # None for notifications

    # --- initialize ---
    if method == "initialize":
        return _ok_response(req_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "serverInfo": SERVER_INFO,
            "capabilities": {"tools": {}},
        })

    # --- initialized (notification, no response) ---
    if method == "notifications/initialized" or method == "initialized":
        return None

    # --- tools/list ---
    if method == "tools/list":
        return _ok_response(req_id, {
            "tools": [
                TOOL_DEFINITION_COMPARE,
                TOOL_DEFINITION_READ_CONFIG,
                TOOL_DEFINITION_DISCOVER,
                TOOL_DEFINITION_BLAST_RADIUS,
                TOOL_DEFINITION_ANALYZE,
                TOOL_DEFINITION_VERIFY_RELEASE,
            ]
        })

    # --- tools/call ---
    if method == "tools/call":
        params = message.get("params") or {}
        name = params.get("name", "")
        arguments = params.get("arguments") or {}
        if name == TOOL_COMPARE:
            result = _run_compare(arguments)
        elif name == TOOL_READ_CONFIG:
            result = _run_read_config(arguments)
        elif name == TOOL_DISCOVER:
            result = _run_discover(arguments)
        elif name == TOOL_BLAST_RADIUS:
            result = _run_blast_radius(arguments)
        elif name == TOOL_ANALYZE:
            result = _run_analyze(arguments, analyzer=analyzer)
        elif name == TOOL_VERIFY_RELEASE:
            result = _run_verify_release(arguments)
        else:
            return _error_response(req_id, -32602, f"Unknown tool: {name!r}")
        return _ok_response(req_id, result)

    # --- ping ---
    if method == "ping":
        return _ok_response(req_id, {})

    # Unknown method
    if req_id is not None:
        return _error_response(req_id, -32601, f"Method not found: {method!r}")
    return None  # unknown notification — silently ignore


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def _serve() -> None:
    print("contract-guard MCP server ready (stdio)", file=sys.stderr)
    for raw_line in sys.stdin:
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            message = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            _send(_error_response(None, -32700, f"Parse error: {exc}"))
            continue

        try:
            response = _dispatch(message)
        except Exception as exc:  # pragma: no cover
            traceback.print_exc(file=sys.stderr)
            req_id = message.get("id")
            if req_id is not None:
                _send(_error_response(req_id, -32603, f"Internal error: {exc}"))
            continue

        if response is not None:
            _send(response)


def main() -> None:
    _serve()


if __name__ == "__main__":
    main()
