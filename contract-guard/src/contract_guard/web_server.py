"""
ContractGuard Command Center — Web Server (Phase 3G).

Thin Flask API layer over the existing ContractGuard deterministic engine.
All compatibility logic stays in the Python backend; the UI is a visualization
and interaction layer only.

Launch:
    python -m contract_guard.web_server [--port 5100] [--workspace .]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, request, send_from_directory

# ContractGuard imports — reuse, never duplicate
from .discovery import discover_and_check, DiscoveryReport
from .evidence import evaluate_release_gate, ReleaseVerification, ReleaseStatus
from .graph import build_dependency_graph, DependencyGraph
from .impact import BlastRadiusSummary
from .mission import generate_repair_mission, RepairMission
from .models import Finding
from .passport import generate_change_passport, ChangePassport
from .simulation import simulate_what_if, WhatIfResult

# ---------------------------------------------------------------------------
# Flask App
# ---------------------------------------------------------------------------

app = Flask(
    __name__,
    static_folder=os.path.join(os.path.dirname(__file__), "static"),
    static_url_path="/static",
)

# Workspace root — set at startup, used by all endpoints
_WORKSPACE_ROOT: Path = Path(".").resolve()


def _ws() -> Path:
    return _WORKSPACE_ROOT


# ---------------------------------------------------------------------------
# Static UI
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


# ---------------------------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------------------------

@app.route("/api/what-if", methods=["POST"])
def api_what_if():
    """Run a What-If simulation using the real ContractGuard engine."""
    try:
        data = request.get_json(force=True) or {}
        result: WhatIfResult = simulate_what_if(
            workspace_root=str(_ws()),
            producer_service=data.get("producer", "payment-service"),
            endpoint=data.get("endpoint", ""),
            change_kind=data.get("change_kind", "field_renamed"),
            field=data.get("field"),
            new_field=data.get("new_field"),
        )
        return jsonify(result.to_dict())
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        return jsonify({"error": str(exc)}), 400


@app.route("/api/blast-radius", methods=["GET"])
def api_blast_radius():
    """Return the dependency graph and blast-radius summary."""
    try:
        producer = request.args.get("producer")
        report: DiscoveryReport = discover_and_check(
            _ws(), producer_filter=producer
        )
        graph: DependencyGraph = build_dependency_graph(
            _ws(), producer_filter=producer
        )
        summary = report.blast_radius_summary

        return jsonify({
            "graph": graph.to_dict(),
            "tree": graph.render_tree(root_service=producer),
            "summary": summary.to_dict() if summary else {},
            "consumers_checked": report.consumers_checked,
            "affected_consumers": report.affected_consumers,
            "compatible_consumers": report.compatible_consumers,
            "breaking_findings": report.breaking_findings,
        })
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        return jsonify({"error": str(exc)}), 400


@app.route("/api/repair-mission", methods=["GET"])
def api_repair_mission():
    """Generate the deterministic Repair Mission."""
    try:
        producer = request.args.get("producer")
        mission: RepairMission = generate_repair_mission(
            _ws(), producer_filter=producer
        )
        return jsonify(mission.to_dict())
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        return jsonify({"error": str(exc)}), 400


@app.route("/api/verify", methods=["GET"])
def api_verify():
    """Evaluate the deterministic release gate."""
    try:
        producer = request.args.get("producer", "payment-service")
        test_status = request.args.get("test_status", "PASS")
        report: DiscoveryReport = discover_and_check(
            _ws(), producer_filter=producer
        )
        verification: ReleaseVerification = evaluate_release_gate(
            report=report,
            producer_service=producer,
            test_results={"status": test_status, "details": f"Automated tests: {test_status}"},
        )
        return jsonify(verification.to_dict())
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        return jsonify({"error": str(exc)}), 400


@app.route("/api/passport", methods=["GET"])
def api_passport():
    """Generate the full Change Passport."""
    try:
        producer = request.args.get("producer")
        test_status = request.args.get("test_status", "PASS")
        passport: ChangePassport = generate_change_passport(
            workspace_root=str(_ws()),
            producer_filter=producer,
            test_status=test_status,
        )
        return jsonify(passport.to_dict())
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        return jsonify({"error": str(exc)}), 400


@app.route("/api/discovery", methods=["GET"])
def api_discovery():
    """Run workspace discovery."""
    try:
        producer = request.args.get("producer")
        report: DiscoveryReport = discover_and_check(
            _ws(), producer_filter=producer
        )
        results_list = []
        for r in report.results:
            results_list.append({
                "consumer_service": r.consumer_service,
                "producer_service": r.producer_service,
                "consumer_contract": r.consumer_contract,
                "producer_contract": r.producer_contract,
                "is_compatible": r.is_compatible,
                "findings": [
                    {
                        "endpoint": f.endpoint,
                        "affected_field": f.affected_field,
                        "change_kind": f.change_kind.value if hasattr(f.change_kind, "value") else str(f.change_kind),
                        "detail": f.detail,
                        "severity": f.severity.value if hasattr(f.severity, "value") else str(f.severity),
                        "reason": f.reason,
                    }
                    for f in r.findings
                ],
            })
        return jsonify({
            "workspace_root": report.workspace_root,
            "configs_found": report.configs_found,
            "consumers_checked": report.consumers_checked,
            "affected_consumers": report.affected_consumers,
            "compatible_consumers": report.compatible_consumers,
            "results": results_list,
        })
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        return jsonify({"error": str(exc)}), 400


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------

def main():
    global _WORKSPACE_ROOT
    parser = argparse.ArgumentParser(description="ContractGuard Command Center")
    parser.add_argument("--port", type=int, default=5100, help="Port (default: 5100)")
    parser.add_argument("--workspace", default=".", help="Workspace root path")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host")
    args = parser.parse_args()

    _WORKSPACE_ROOT = Path(args.workspace).resolve()
    print(f"\n  ContractGuard Command Center")
    print(f"  Workspace: {_WORKSPACE_ROOT}")
    print(f"  URL:       http://{args.host}:{args.port}\n")
    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
