"""CLI entry point for ContractGuard."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .ai import ImpactAnalyzer
from .comparator import Comparator
from .config import load_config
from .discovery import discover_and_check
from .evidence import evaluate_release_gate, generate_evidence, ReleaseStatus
from .git import inspect_git_status
from .graph import build_dependency_graph
from .models import Severity
from .mission import generate_repair_mission, format_mission_text
from .passport import generate_change_passport
from .pr import analyze_pr
from .simulation import simulate_what_if

# ANSI helpers
_RED = "\033[31m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_CYAN = "\033[36m"
_BOLD = "\033[1m"
_RESET = "\033[0m"


def _colorize(text: str, *codes: str, no_color: bool = False) -> str:
    if no_color:
        return text
    return "".join(codes) + text + _RESET


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="contract-guard",
        description="ContractGuard: Deterministic OpenAPI contract compatibility and blast-radius verification.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # 1. compare
    compare = sub.add_parser(
        "compare",
        help="Compare a producer contract against a consumer contract.",
    )
    compare.add_argument("producer", help="Path to the producer OpenAPI YAML file.")
    compare.add_argument("consumer", help="Path to the consumer OpenAPI YAML file.")
    compare.add_argument(
        "--no-color",
        action="store_true",
        default=False,
        help="Disable ANSI color output.",
    )

    # 2. check
    check = sub.add_parser(
        "check",
        help=(
            "Read a contractguard.yaml config file and compare all declared "
            "consumer/producer contract pairs."
        ),
    )
    check.add_argument(
        "config",
        nargs="?",
        default="contractguard.yaml",
        help="Path to contractguard.yaml (default: ./contractguard.yaml).",
    )
    check.add_argument(
        "--no-color",
        action="store_true",
        default=False,
        help="Disable ANSI color output.",
    )

    # 3. discover
    discover = sub.add_parser(
        "discover",
        help="Discover all contractguard.yaml consumers in workspace and compute blast radius.",
    )
    discover.add_argument(
        "workspace",
        nargs="?",
        default=".",
        help="Workspace root path to scan for consumer configs (default: .).",
    )
    discover.add_argument(
        "--producer",
        default=None,
        help="Filter by producer service name.",
    )
    discover.add_argument(
        "--no-color",
        action="store_true",
        default=False,
        help="Disable ANSI color output.",
    )

    # 4. analyze
    analyze = sub.add_parser(
        "analyze",
        help="Discover consumers, detect contract drift, and run AI impact analysis & repair planning.",
    )
    analyze.add_argument(
        "workspace",
        nargs="?",
        default=".",
        help="Workspace root path (default: .).",
    )
    analyze.add_argument(
        "--producer",
        default=None,
        help="Filter by producer service name.",
    )
    analyze.add_argument(
        "--no-color",
        action="store_true",
        default=False,
        help="Disable ANSI color output.",
    )

    # 5. impact
    impact = sub.add_parser(
        "impact",
        help="Compute and display deterministic contract blast radius (services, contracts, code files, endpoints).",
    )
    impact.add_argument(
        "workspace",
        nargs="?",
        default=".",
        help="Workspace root path (default: .).",
    )
    impact.add_argument(
        "--producer",
        default=None,
        help="Filter by producer service name.",
    )
    impact.add_argument(
        "--format",
        choices=["text", "json", "markdown"],
        default="text",
        help="Output format (default: text).",
    )
    impact.add_argument(
        "--no-color",
        action="store_true",
        default=False,
        help="Disable ANSI color output.",
    )

    # 6. verify
    verify = sub.add_parser(
        "verify",
        help="Deterministically evaluate release safety gate (READY or BLOCKED).",
    )
    verify.add_argument(
        "workspace",
        nargs="?",
        default=".",
        help="Workspace root path (default: .).",
    )
    verify.add_argument(
        "--producer",
        default="payment-service",
        help="Producer service name being released (default: payment-service).",
    )
    verify.add_argument(
        "--test-status",
        choices=["PASS", "FAIL"],
        default="PASS",
        help="Automated test suite outcome (default: PASS).",
    )
    verify.add_argument(
        "--format",
        choices=["text", "json", "markdown"],
        default="text",
        help="Output format (default: text).",
    )
    verify.add_argument(
        "--no-color",
        action="store_true",
        default=False,
        help="Disable ANSI color output.",
    )

    # 6. evidence
    evidence = sub.add_parser(
        "evidence",
        help="Generate reproducible JSON and Markdown release audit evidence.",
    )
    evidence.add_argument(
        "workspace",
        nargs="?",
        default=".",
        help="Workspace root path (default: .).",
    )
    evidence.add_argument(
        "--producer",
        default="payment-service",
        help="Producer service name (default: payment-service).",
    )
    evidence.add_argument(
        "--test-status",
        choices=["PASS", "FAIL"],
        default="PASS",
        help="Automated test suite outcome (default: PASS).",
    )
    evidence.add_argument(
        "--output-dir",
        default=".",
        help="Output directory for evidence files (default: .).",
    )
    evidence.add_argument(
        "--no-color",
        action="store_true",
        default=False,
        help="Disable ANSI color output.",
    )

    # 8. git-status
    git_status = sub.add_parser(
        "git-status",
        help="Inspect Git repository status and identify changed OpenAPI contracts.",
    )
    git_status.add_argument(
        "workspace",
        nargs="?",
        default=".",
        help="Workspace root path (default: .).",
    )
    git_status.add_argument(
        "--no-color",
        action="store_true",
        default=False,
        help="Disable ANSI color output.",
    )

    # 9. git-diff
    git_diff = sub.add_parser(
        "git-diff",
        help="Inspect files and contracts changed between Git base ref and working tree.",
    )
    git_diff.add_argument(
        "workspace",
        nargs="?",
        default=".",
        help="Workspace root path (default: .).",
    )
    git_diff.add_argument(
        "--base",
        default=None,
        help="Git base ref (e.g. origin/main, HEAD~1).",
    )
    git_diff.add_argument(
        "--no-color",
        action="store_true",
        default=False,
        help="Disable ANSI color output.",
    )

    # 10. pr
    pr = sub.add_parser(
        "pr",
        help="Analyze Git changes/PR for contract drift, blast radius, and SemVer recommendation.",
    )
    pr.add_argument(
        "workspace",
        nargs="?",
        default=".",
        help="Workspace root path (default: .).",
    )
    pr.add_argument(
        "--base",
        default=None,
        help="Git base ref to compare against (e.g. origin/main, HEAD~1).",
    )
    pr.add_argument(
        "--producer",
        default=None,
        help="Filter by producer service name.",
    )
    pr.add_argument(
        "--version",
        default=None,
        help="Current/baseline version for SemVer calculation (e.g. 1.4.0).",
    )
    pr.add_argument(
        "--format",
        choices=["text", "json", "markdown"],
        default="text",
        help="Output format (default: text).",
    )
    pr.add_argument(
        "--output",
        default=None,
        help="File path to write output (e.g. contractguard-pr.md).",
    )
    pr.add_argument(
        "--no-color",
        action="store_true",
        default=False,
        help="Disable ANSI color output.",
    )

    # 11. mission
    mission = sub.add_parser(
        "mission",
        help="Generate a deterministic Repair Mission for IBM Bob when breaking contract changes are detected.",
    )
    mission.add_argument(
        "workspace",
        nargs="?",
        default=".",
        help="Workspace root path (default: .).",
    )
    mission.add_argument(
        "--producer",
        default=None,
        help="Filter by producer service name.",
    )
    mission.add_argument(
        "--format",
        choices=["text", "json", "markdown"],
        default="text",
        help="Output format (default: text).",
    )
    mission.add_argument(
        "--output",
        default=None,
        help="File path to write output (e.g. contractguard-mission.json).",
    )
    mission.add_argument(
        "--no-color",
        action="store_true",
        default=False,
        help="Disable ANSI color output.",
    )

    # 12. passport
    passport = sub.add_parser(
        "passport",
        help="Generate a deterministic Change Passport (unified impact and release report).",
    )
    passport.add_argument(
        "workspace",
        nargs="?",
        default=".",
        help="Workspace root path (default: .).",
    )
    passport.add_argument(
        "--producer",
        default=None,
        help="Filter by producer service name.",
    )
    passport.add_argument(
        "--test-status",
        choices=["PASS", "FAIL"],
        default="PASS",
        help="Automated test suite outcome (default: PASS).",
    )
    passport.add_argument(
        "--format",
        choices=["text", "json", "markdown"],
        default="text",
        help="Output format (default: text).",
    )
    passport.add_argument(
        "--output",
        default=None,
        help="File path to write output (e.g. contractguard-passport.json).",
    )
    passport.add_argument(
        "--no-color",
        action="store_true",
        default=False,
        help="Disable ANSI color output.",
    )

    # 13. what-if
    whatif = sub.add_parser(
        "what-if",
        help="Simulate a hypothetical contract change in memory without mutating files or Git.",
    )
    whatif.add_argument(
        "workspace",
        nargs="?",
        default=".",
        help="Workspace root path (default: .).",
    )
    whatif.add_argument(
        "--producer",
        required=True,
        help="Producer service name being simulated.",
    )
    whatif.add_argument(
        "--endpoint",
        required=True,
        help="API endpoint to modify (e.g. 'GET /api/payments/{id}').",
    )
    whatif.add_argument(
        "--change-kind",
        choices=[
            "field_renamed",
            "field_removed",
            "endpoint_removed",
            "field_optional_added",
            "field_required_added",
        ],
        required=True,
        help="Kind of contract change to simulate.",
    )
    whatif.add_argument(
        "--field",
        default=None,
        help="Field name being changed or removed.",
    )
    whatif.add_argument(
        "--new-field",
        default=None,
        help="New field name for field_renamed, or field for addition.",
    )
    whatif.add_argument(
        "--format",
        choices=["text", "json", "markdown"],
        default="text",
        help="Output format (default: text).",
    )
    whatif.add_argument(
        "--output",
        default=None,
        help="File path to write output.",
    )
    whatif.add_argument(
        "--no-color",
        action="store_true",
        default=False,
        help="Disable ANSI color output.",
    )

    return parser


def cmd_compare(args: argparse.Namespace) -> int:
    nc = args.no_color
    try:
        comparator = Comparator(args.producer, args.consumer)
        report = comparator.compare()
    except (FileNotFoundError, ValueError, KeyError) as exc:
        print(
            _colorize(f"ERROR: {exc}", _RED, _BOLD, no_color=nc),
            file=sys.stderr,
        )
        return 2

    # --- Verdict banner ---
    if report.is_compatible:
        banner = _colorize("[OK]  COMPATIBLE", _GREEN, _BOLD, no_color=nc)
    else:
        banner = _colorize("[!!] BREAKING", _RED, _BOLD, no_color=nc)

    print(f"\n{banner}\n")

    if not report.findings:
        print("  No differences detected between producer and consumer contracts.")
        print()
        return 0

    breaking = [f for f in report.findings if f.is_breaking]
    compatible = [f for f in report.findings if not f.is_breaking]

    if breaking:
        print(_colorize("Breaking changes:", _RED, _BOLD, no_color=nc))
        for f in breaking:
            print(f"  Endpoint    : {f.endpoint}")
            print(f"  Field       : {f.affected_field}")
            print(f"  Change      : {f.change_kind.value}")
            print(f"  Detail      : {f.detail}")
            print(f"  Reason      : {f.reason}")
            print()

    if compatible:
        print(_colorize("Compatible changes:", _GREEN, _BOLD, no_color=nc))
        for f in compatible:
            print(f"  Endpoint    : {f.endpoint}")
            print(f"  Field       : {f.affected_field}")
            print(f"  Change      : {f.change_kind.value}")
            print(f"  Detail      : {f.detail}")
            print(f"  Reason      : {f.reason}")
            print()

    return 0 if report.is_compatible else 1


def cmd_check(args: argparse.Namespace) -> int:
    """Run contract checks for every dependency declared in contractguard.yaml."""
    nc = args.no_color
    try:
        config = load_config(args.config)
    except (FileNotFoundError, ValueError) as exc:
        print(_colorize(f"ERROR: {exc}", _RED, _BOLD, no_color=nc), file=sys.stderr)
        return 2

    if not config.dependencies:
        print("No dependencies declared in contractguard.yaml.")
        return 0

    overall_ok = True
    for dep in config.dependencies:
        print(
            _colorize(
                f"\n-- Checking {config.service} -> {dep.service} --",
                _BOLD,
                no_color=nc,
            )
        )
        print(f"  consumer: {dep.consumer_contract}")
        print(f"  producer: {dep.producer_contract}")

        inner = argparse.Namespace(
            producer=str(dep.producer_contract),
            consumer=str(dep.consumer_contract),
            no_color=nc,
        )
        rc = cmd_compare(inner)
        if rc != 0:
            overall_ok = False

    return 0 if overall_ok else 1


def cmd_discover(args: argparse.Namespace) -> int:
    nc = args.no_color
    try:
        report = discover_and_check(args.workspace, producer_filter=args.producer)
    except Exception as exc:
        print(_colorize(f"ERROR: {exc}", _RED, _BOLD, no_color=nc), file=sys.stderr)
        return 2

    total = len(report.consumers_checked)
    compat = len(report.compatible_consumers)
    affected = len(report.affected_consumers)

    if affected == 0:
        banner = _colorize(f"[OK] ALL CONSUMERS COMPATIBLE ({compat}/{total})", _GREEN, _BOLD, no_color=nc)
    else:
        banner = _colorize(f"[!!] {affected}/{total} CONSUMERS AFFECTED BY CONTRACT DRIFT", _RED, _BOLD, no_color=nc)

    print(f"\n{banner}\n")
    print(f"  Workspace Root    : {report.workspace_root}")
    print(f"  Configs Discovered: {report.configs_found}")
    print(f"  Consumers Checked : {', '.join(report.consumers_checked) or 'None'}")
    print(f"  Compatible        : {', '.join(report.compatible_consumers) or 'None'}")
    print(f"  Affected          : {', '.join(report.affected_consumers) or 'None'}")
    print()

    if report.impacts:
        print(_colorize("Deterministic Blast Radius & Impact Analysis:", _CYAN, _BOLD, no_color=nc))
        for imp in report.impacts:
            print(f"\n  Consumer  : {imp.consumer_service}")
            print(f"  Contract  : {imp.contract_path}")
            print(f"  Endpoint  : {imp.endpoint}")
            print(f"  Field     : {imp.affected_field} ({imp.change_kind})")
            print(f"  Detail    : {imp.detail}")

            if imp.confirmed_source_files:
                print(_colorize("    Confirmed Affected Source Files:", _BOLD, no_color=nc))
                for f in imp.confirmed_source_files:
                    print(f"      - {f}")
            if imp.confirmed_test_files:
                print(_colorize("    Confirmed Affected Test Files:", _BOLD, no_color=nc))
                for f in imp.confirmed_test_files:
                    print(f"      - {f}")
            if imp.likely_source_files:
                print(_colorize("    Likely Affected Source Files:", _BOLD, no_color=nc))
                for f in imp.likely_source_files:
                    print(f"      - {f}")

    return 0 if affected == 0 else 1


def cmd_analyze(args: argparse.Namespace) -> int:
    nc = args.no_color
    try:
        report = discover_and_check(args.workspace, producer_filter=args.producer)
    except Exception as exc:
        print(_colorize(f"ERROR: {exc}", _RED, _BOLD, no_color=nc), file=sys.stderr)
        return 2

    # Deterministic findings first
    cmd_discover(args)

    print(_colorize("\n--- AI Impact Explanation & Advisory Repair Plan ---", _CYAN, _BOLD, no_color=nc))
    analyzer = ImpactAnalyzer()
    ai_report = analyzer.analyze(report)

    if ai_report.status == "unavailable":
        print(_colorize(f"\n[AI UNAVAILABLE] {ai_report.error_message}", _YELLOW, _BOLD, no_color=nc))
        print("  Deterministic analysis above remains 100% active and accurate.")
        return 0 if len(report.affected_consumers) == 0 else 1

    if ai_report.status == "error":
        print(_colorize(f"\n[AI ERROR] {ai_report.error_message}", _RED, _BOLD, no_color=nc))
        print("  Deterministic findings preserved.")
        return 0 if len(report.affected_consumers) == 0 else 1

    if ai_report.analysis:
        analysis = ai_report.analysis
        print(f"\nSummary:\n  {analysis.summary}\n")
        if analysis.breaking_change_explanation:
            print(f"Technical Explanation:\n  {analysis.breaking_change_explanation}\n")

        if analysis.impact:
            print(_colorize("Impact by Consumer:", _BOLD, no_color=nc))
            for item in analysis.impact:
                print(f"  [{item.consumer}]")
                print(f"    Reason        : {item.reason}")
                if item.confirmed_impact:
                    print("    Confirmed Fact: " + "; ".join(item.confirmed_impact))
                if item.likely_impact:
                    print("    Likely Impact : " + "; ".join(item.likely_impact))
                if item.files:
                    print("    Affected Files: " + ", ".join(item.files))
                if item.tests_to_update:
                    print("    Tests to Update: " + ", ".join(item.tests_to_update))
                print()

        if analysis.repair_plan:
            print(_colorize("Recommended Advisory Repair Plan (for IBM Bob / Developers):", _GREEN, _BOLD, no_color=nc))
            for step in analysis.repair_plan:
                print(f"  {step}")
            print()

        if analysis.migration_options:
            print(_colorize("Backward-Compatible Migration Options:", _CYAN, _BOLD, no_color=nc))
            for opt in analysis.migration_options:
                print(f"  - {opt}")
            print()

    return 0 if len(report.affected_consumers) == 0 else 1


def cmd_impact(args: argparse.Namespace) -> int:
    nc = args.no_color
    try:
        report = discover_and_check(args.workspace, producer_filter=args.producer)
    except Exception as exc:
        print(_colorize(f"ERROR: {exc}", _RED, _BOLD, no_color=nc), file=sys.stderr)
        return 2

    graph = build_dependency_graph(args.workspace, producer_filter=args.producer)
    summary = report.blast_radius_summary

    # Determine API change string
    api_change = "None"
    for imp in report.impacts:
        if imp.change_kind == "field_renamed":
            import re
            m = re.search(r"Consumer expects '([^']+)' but producer now uses '([^']+)'", imp.detail)
            if m:
                api_change = f"{m.group(1)} -> {m.group(2)}"
                break
            elif imp.affected_field:
                api_change = imp.affected_field
                break
        elif imp.affected_field:
            api_change = imp.affected_field
            break
    if api_change == "None" and summary.affected_fields:
        api_change = ", ".join(summary.affected_fields)

    # JSON format
    if args.format == "json":
        import json
        payload = {
            "workspace": report.workspace_root,
            "producer_filter": report.producer_filter,
            "summary": report.summary,
            "api_change": api_change,
            "blast_radius_summary": summary.to_dict(),
            "direct_consumers": summary.direct_consumers,
            "affected_consumers": summary.affected_consumers or len(summary.affected_services),
            "contract_only_consumers": summary.contract_only_consumers,
            "confirmed_source_files": len(summary.confirmed_source_files),
            "confirmed_test_files": len(summary.confirmed_test_files),
            "likely_source_files": len(summary.likely_source_files),
            "likely_test_files": len(summary.likely_test_files),
            "transitive_consumers": summary.transitive_consumers,
            "dependency_graph": graph.to_dict(),
            "impacts": [imp.to_dict() for imp in report.impacts],
        }
        print(json.dumps(payload, indent=2))
        return 0 if len(report.affected_consumers) == 0 else 1

    # Markdown format
    if args.format == "markdown":
        lines = [
            "# CONTRACTGUARD — BLAST RADIUS",
            "",
            "## API CHANGE",
            api_change,
            "",
            "| Metric | Count |",
            "|---|---|",
            f"| Direct Consumers | {summary.direct_consumers} |",
            f"| Affected Consumers | {summary.affected_consumers or len(summary.affected_services)} |",
            f"| Contract-Only Consumers | {summary.contract_only_consumers} |",
            f"| Confirmed Source Files | {len(summary.confirmed_source_files)} |",
            f"| Confirmed Test Files | {len(summary.confirmed_test_files)} |",
            f"| Likely Source Files | {len(summary.likely_source_files)} |",
            f"| Transitive Consumers | {summary.transitive_consumers} |",
        ]
        if summary.confirmed_source_files:
            lines.extend(["", "### Confirmed Source Files"])
            for f in summary.confirmed_source_files:
                lines.append(f"- {f}")
        if summary.confirmed_test_files:
            lines.extend(["", "### Confirmed Test Files"])
            for f in summary.confirmed_test_files:
                lines.append(f"- {f}")
        if summary.likely_source_files:
            lines.extend(["", "### Likely Source Files"])
            for f in summary.likely_source_files:
                lines.append(f"- {f}")
        lines.append("")
        print("\n".join(lines))
        return 0 if len(report.affected_consumers) == 0 else 1

    # Text format
    if not report.affected_consumers:
        banner = _colorize("[OK] NO BLAST RADIUS - ALL CONSUMERS COMPATIBLE", _GREEN, _BOLD, no_color=nc)
        print(f"\n{banner}\n")
        print(f"  {report.summary}\n")
        return 0

    print(_colorize("\nCONTRACTGUARD — BLAST RADIUS", _BOLD, _CYAN, no_color=nc))
    print(_colorize("\nAPI CHANGE", _BOLD, no_color=nc))
    print(f"{api_change}")
    print(_colorize("\nDIRECT CONSUMERS", _BOLD, no_color=nc))
    print(f"{summary.direct_consumers}")
    print(_colorize("\nAFFECTED CONSUMERS", _BOLD, no_color=nc))
    print(f"{summary.affected_consumers or len(summary.affected_services)}")
    print(_colorize("\nCONTRACT-ONLY CONSUMERS", _BOLD, no_color=nc))
    print(f"{summary.contract_only_consumers}")
    print(_colorize("\nCONFIRMED SOURCE FILES", _BOLD, no_color=nc))
    print(f"{len(summary.confirmed_source_files)}")
    for f in summary.confirmed_source_files:
        print(f"  - {f}")
    print(_colorize("\nCONFIRMED TEST FILES", _BOLD, no_color=nc))
    print(f"{len(summary.confirmed_test_files)}")
    for f in summary.confirmed_test_files:
        print(f"  - {f}")
    if summary.likely_source_files:
        print(_colorize("\nLIKELY SOURCE FILES", _BOLD, no_color=nc))
        print(f"{len(summary.likely_source_files)}")
        for f in summary.likely_source_files:
            print(f"  - {f}")
    if summary.likely_test_files:
        print(_colorize("\nLIKELY TEST FILES", _BOLD, no_color=nc))
        print(f"{len(summary.likely_test_files)}")
        for f in summary.likely_test_files:
            print(f"  - {f}")
    print(_colorize("\nTRANSITIVE CONSUMERS", _BOLD, no_color=nc))
    print(f"{summary.transitive_consumers}\n")

    return 1


def cmd_verify(args: argparse.Namespace) -> int:
    nc = args.no_color
    try:
        report = discover_and_check(args.workspace, producer_filter=args.producer)
        try:
            mission = generate_repair_mission(args.workspace, producer_filter=args.producer)
            eff_mission_id = mission.mission_id
        except Exception:
            eff_mission_id = None

        verification = evaluate_release_gate(
            report,
            producer_service=args.producer,
            test_results={"status": args.test_status, "details": f"Automated tests: {args.test_status}"},
            mission_id=eff_mission_id,
        )
    except Exception as exc:
        print(_colorize(f"ERROR: {exc}", _RED, _BOLD, no_color=nc), file=sys.stderr)
        return 2

    fmt = getattr(args, "format", "text")
    if fmt == "json":
        import json
        payload = {
            "mission_id": verification.mission_id,
            "status": verification.status.value,
            "is_ready": verification.is_ready,
            "producer_service": verification.producer_service,
            "contract_checks_status": verification.contract_checks_status,
            "breaking_changes_count": verification.breaking_changes_count,
            "consumers_checked": verification.consumers_checked,
            "compatible_consumers": verification.compatible_consumers,
            "affected_consumers": verification.affected_consumers,
            "verification": {
                "compatible_consumers": len(verification.compatible_consumers),
                "incompatible_consumers": len(verification.affected_consumers),
                "breaking_findings": verification.breaking_changes_count,
            },
            "remaining_actions": verification.remaining_actions,
            "remaining_failures": verification.remaining_failures,
            "next_step": verification.next_step,
            "reasons": verification.reasons,
        }
        print(json.dumps(payload, indent=2))
        return 0 if verification.is_ready else 1

    if fmt == "markdown":
        lines = [
            f"# CONTRACTGUARD VERIFICATION: {verification.status.value}",
            "",
            f"**Producer Service:** `{verification.producer_service}`  ",
            f"**Mission ID:** `{verification.mission_id or 'N/A'}`  ",
            f"**Status:** **{verification.status.value}**  ",
            f"**Next Step:** `{verification.next_step}`  ",
            "",
            "## Summary",
            f"- **Consumers Checked:** {len(verification.consumers_checked)}",
            f"- **Compatible Consumers:** {len(verification.compatible_consumers)}",
            f"- **Incompatible Consumers:** {len(verification.affected_consumers)}",
            f"- **Breaking Findings:** {verification.breaking_changes_count}",
            "",
        ]
        if verification.remaining_actions:
            lines.append("## Remaining Required Actions")
            for act in verification.remaining_actions:
                lines.append(f"- [ ] {act}")
            lines.append("")
        if verification.remaining_failures:
            lines.append("## Remaining Breaking Failures")
            for fail in verification.remaining_failures:
                lines.append(f"- **{fail.get('consumer_service')}:** {fail.get('detail')} ({fail.get('endpoint')})")
            lines.append("")
        print("\n".join(lines))
        return 0 if verification.is_ready else 1

    if verification.status == ReleaseStatus.READY:
        banner = _colorize("[OK] READY FOR RELEASE", _GREEN, _BOLD, no_color=nc)
    else:
        banner = _colorize("[BLOCKED] RELEASE BLOCKED", _RED, _BOLD, no_color=nc)

    print(f"\n{banner}\n")
    if verification.mission_id:
        print(f"  Mission ID       : {verification.mission_id}")
    print(f"  Producer Service : {verification.producer_service}")
    print(f"  Contract Status  : {verification.contract_checks_status}")
    print(f"  Breaking Changes : {verification.breaking_changes_count}")
    print(f"  Consumers Checked: {len(verification.consumers_checked)}")
    print(f"  Affected         : {len(verification.affected_consumers)}")
    print(f"  Next Step        : {verification.next_step}")
    print(f"\nReasons:")
    for r in verification.reasons:
        print(f"  - {r}")
    if verification.remaining_actions:
        print(f"\nRemaining Actions:")
        for a in verification.remaining_actions:
            print(f"  - [ ] {a}")
    print()

    return 0 if verification.is_ready else 1


def cmd_evidence(args: argparse.Namespace) -> int:
    nc = args.no_color
    try:
        report = discover_and_check(args.workspace, producer_filter=args.producer)
        verification = evaluate_release_gate(
            report,
            producer_service=args.producer,
            test_results={"status": args.test_status, "details": f"Automated tests: {args.test_status}"},
        )
        evidence = generate_evidence(report, verification, output_dir=args.output_dir)
    except Exception as exc:
        print(_colorize(f"ERROR: {exc}", _RED, _BOLD, no_color=nc), file=sys.stderr)
        return 2

    if verification.is_ready:
        banner = _colorize("[OK] EVIDENCE GENERATED - RELEASE APPROVED", _GREEN, _BOLD, no_color=nc)
    else:
        banner = _colorize("[!!] EVIDENCE GENERATED - RELEASE BLOCKED", _RED, _BOLD, no_color=nc)

    print(f"\n{banner}\n")
    print(f"  Evidence ID   : {evidence.evidence_id}")
    print(f"  Verdict       : {evidence.verdict}")
    print(f"  Output Files  :")
    print(f"    - {Path(args.output_dir) / 'contractguard-evidence.json'}")
    print(f"    - {Path(args.output_dir) / 'contractguard-report.md'}")
    print()

    return 0 if verification.is_ready else 1


def cmd_git_status(args: argparse.Namespace) -> int:
    nc = args.no_color
    status = inspect_git_status(args.workspace)
    if not status.is_repo:
        print(_colorize(f"ERROR: {status.error}", _RED, _BOLD, no_color=nc), file=sys.stderr)
        return 2

    print(_colorize("\nGit Repository Status", _BOLD, no_color=nc))
    print(f"  Repository Root : {status.repo_root}")
    print(f"  Current SHA     : {status.current_sha or 'N/A'}")
    print(f"  Changed Files   : {len(status.changed_files)}")

    print(_colorize(f"\nChanged Contracts ({len(status.changed_contracts)}):", _CYAN, _BOLD, no_color=nc))
    if not status.changed_contracts:
        print("  None")
    else:
        for c in status.changed_contracts:
            print(f"  - {c}")

    print(_colorize(f"\nOther Changed Files ({len(status.other_changed_files)}):", _BOLD, no_color=nc))
    if not status.other_changed_files:
        print("  None")
    else:
        for f in status.other_changed_files[:10]:
            print(f"  - {f}")
        if len(status.other_changed_files) > 10:
            print(f"  ... and {len(status.other_changed_files) - 10} more")
    print()
    return 0


def cmd_git_diff(args: argparse.Namespace) -> int:
    nc = args.no_color
    status = inspect_git_status(args.workspace, base_ref=args.base)
    if not status.is_repo or status.error:
        print(_colorize(f"ERROR: {status.error}", _RED, _BOLD, no_color=nc), file=sys.stderr)
        return 2

    base_label = args.base if args.base else "working tree / HEAD"
    print(_colorize(f"\nGit Diff against {base_label}", _BOLD, no_color=nc))
    print(f"  Repository Root : {status.repo_root}")
    print(f"  Current SHA     : {status.current_sha or 'N/A'}")
    print(f"  Total Changed   : {len(status.changed_files)}")

    print(_colorize(f"\nChanged Contracts ({len(status.changed_contracts)}):", _CYAN, _BOLD, no_color=nc))
    if not status.changed_contracts:
        print("  None")
    else:
        for c in status.changed_contracts:
            print(f"  - {c}")
    print()
    return 0


def cmd_pr(args: argparse.Namespace) -> int:
    nc = args.no_color
    try:
        pr_report = analyze_pr(
            args.workspace,
            base_ref=args.base,
            producer_filter=args.producer,
            current_version=args.version,
        )
    except Exception as exc:
        print(_colorize(f"ERROR: {exc}", _RED, _BOLD, no_color=nc), file=sys.stderr)
        return 2

    if pr_report.git_error and not pr_report.commit:
        print(_colorize(f"ERROR: {pr_report.git_error}", _RED, _BOLD, no_color=nc), file=sys.stderr)
        return 2

    # Write output to file if requested
    if args.output:
        out_p = Path(args.output).resolve()
        out_p.parent.mkdir(parents=True, exist_ok=True)
        if args.format == "json":
            out_p.write_text(pr_report.to_json(), encoding="utf-8")
        elif args.format == "markdown":
            out_p.write_text(pr_report.to_markdown(), encoding="utf-8")
        else:
            out_p.write_text(pr_report.to_markdown(), encoding="utf-8")

    if args.format == "json":
        print(pr_report.to_json())
        return 0 if pr_report.is_ready else 1

    if args.format == "markdown":
        print(pr_report.to_markdown())
        return 0 if pr_report.is_ready else 1

    # Text format
    if pr_report.is_ready:
        banner = _colorize("[OK] PR SAFE TO MERGE - READY", _GREEN, _BOLD, no_color=nc)
    else:
        banner = _colorize("[BLOCKED] PR CONTAINS BREAKING API CHANGES", _RED, _BOLD, no_color=nc)

    print(f"\n{banner}\n")
    print(_colorize("CONTRACTGUARD -- PR ANALYSIS", _BOLD, no_color=nc))
    print(f"  Repository        : {pr_report.repository or 'N/A'}")
    print(f"  Commit            : {pr_report.commit[:7] if pr_report.commit else 'working tree'}")
    if pr_report.base:
        print(f"  Base Ref          : {pr_report.base}")

    print(_colorize("\nChanged Contracts:", _CYAN, _BOLD, no_color=nc))
    if not pr_report.changed_contracts:
        print("  (None detected by git)")
    else:
        for c in pr_report.changed_contracts:
            print(f"  - {c}")

    print(_colorize(f"\nConsumers Checked: {len(pr_report.consumers_checked)}", _BOLD, no_color=nc))
    print(f"  Compatible        : {len(pr_report.compatible_consumers)}")
    print(f"  Affected          : {len(pr_report.affected_consumers)}")
    print(f"  Breaking Changes  : {len(pr_report.breaking_findings)}")

    if pr_report.breaking_findings:
        print(_colorize("\nBreaking Changes:", _RED, _BOLD, no_color=nc))
        for f in pr_report.breaking_findings:
            ep = f.get("endpoint", "N/A")
            field_name = f.get("affected_field", "N/A")
            ck = f.get("change_kind", "N/A")
            det = f.get("detail", "")
            c_svc = f.get("consumer_service", "N/A")
            print(f"  Endpoint : {ep}")
            print(f"  Field    : {field_name}")
            print(f"  Change   : {ck}")
            print(f"  Consumer : {c_svc}")
            if det:
                print(f"  Detail   : {det}")
            print()

    if pr_report.affected_consumers:
        print(_colorize("Affected Consumers:", _RED, _BOLD, no_color=nc))
        for c in pr_report.affected_consumers:
            print(f"  [X] {c}")
        print()

    sem = pr_report.semver
    print(_colorize("Recommended SemVer:", _BOLD, no_color=nc))
    if sem.current_version and sem.recommended_version:
        print(f"  {sem.current_version} -> {_colorize(sem.recommended_version, _BOLD, no_color=nc)} ({sem.bump.upper()})")
    else:
        print(f"  Bump  : {_colorize(sem.bump.upper(), _BOLD, no_color=nc)}")
    print(f"  Reason: {sem.reason}")

    print(f"\nVerdict:\n  {_colorize(pr_report.verdict, _GREEN if pr_report.is_ready else _RED, _BOLD, no_color=nc)}")
    print(f"\nEvidence ID:\n  {pr_report.evidence_id}\n")

    return 0 if pr_report.is_ready else 1


def cmd_mission(args: argparse.Namespace) -> int:
    nc = args.no_color
    try:
        mission = generate_repair_mission(args.workspace, producer_filter=args.producer)
    except (FileNotFoundError, NotADirectoryError, ValueError) as exc:
        print(
            _colorize(f"ERROR: {exc}", _RED, _BOLD, no_color=nc),
            file=sys.stderr,
        )
        return 2

    if args.format == "json":
        output = mission.to_json()
    elif args.format == "markdown":
        output = mission.to_markdown()
    else:
        output = format_mission_text(mission, no_color=nc)

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output, encoding="utf-8")
        if args.format == "text":
            print(output)
        print(_colorize(f"\nRepair mission written to: {out_path}", _CYAN, no_color=nc))
    else:
        print(output)

    return 0 if mission.status == "READY" else 1


def cmd_passport(args: argparse.Namespace) -> int:
    nc = args.no_color
    try:
        passport = generate_change_passport(
            args.workspace,
            producer_filter=args.producer,
            test_status=args.test_status,
        )
    except (FileNotFoundError, NotADirectoryError, ValueError) as exc:
        print(_colorize(f"ERROR: {exc}", _RED, _BOLD, no_color=nc), file=sys.stderr)
        return 2

    if args.format == "json":
        output = passport.to_json()
    elif args.format == "markdown":
        output = passport.to_markdown()
    else:
        output = passport.render_text()

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output, encoding="utf-8")
        if args.format == "text":
            print(output)
        print(_colorize(f"\nChange Passport written to: {out_path}", _CYAN, no_color=nc))
    else:
        print(output)

    return 0 if passport.verification.get("is_ready") else 1


def cmd_whatif(args: argparse.Namespace) -> int:
    nc = args.no_color
    try:
        result = simulate_what_if(
            workspace_root=args.workspace,
            producer_service=args.producer,
            endpoint=args.endpoint,
            change_kind=args.change_kind,
            field=args.field,
            new_field=args.new_field,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(_colorize(f"ERROR: {exc}", _RED, _BOLD, no_color=nc), file=sys.stderr)
        return 2

    if args.format == "json":
        output = result.to_json()
    elif args.format == "markdown":
        output = result.to_markdown()
    else:
        output = result.render_text()

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output, encoding="utf-8")
        if args.format == "text":
            print(output)
        print(_colorize(f"\nWhat-if simulation written to: {out_path}", _CYAN, no_color=nc))
    else:
        print(output)

    return 0 if result.status == "READY" else 1


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    if args.command == "compare":
        sys.exit(cmd_compare(args))
    elif args.command == "check":
        sys.exit(cmd_check(args))
    elif args.command == "discover":
        sys.exit(cmd_discover(args))
    elif args.command == "analyze":
        sys.exit(cmd_analyze(args))
    elif args.command == "impact":
        sys.exit(cmd_impact(args))
    elif args.command == "verify":
        sys.exit(cmd_verify(args))
    elif args.command == "evidence":
        sys.exit(cmd_evidence(args))
    elif args.command == "git-status":
        sys.exit(cmd_git_status(args))
    elif args.command == "git-diff":
        sys.exit(cmd_git_diff(args))
    elif args.command == "pr":
        sys.exit(cmd_pr(args))
    elif args.command == "mission":
        sys.exit(cmd_mission(args))
    elif args.command == "passport":
        sys.exit(cmd_passport(args))
    elif args.command == "what-if":
        sys.exit(cmd_whatif(args))


if __name__ == "__main__":
    main()
