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
from .models import Severity

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

    # 5. verify
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


def cmd_verify(args: argparse.Namespace) -> int:
    nc = args.no_color
    try:
        report = discover_and_check(args.workspace, producer_filter=args.producer)
        verification = evaluate_release_gate(
            report,
            producer_service=args.producer,
            test_results={"status": args.test_status, "details": f"Automated tests: {args.test_status}"},
        )
    except Exception as exc:
        print(_colorize(f"ERROR: {exc}", _RED, _BOLD, no_color=nc), file=sys.stderr)
        return 2

    if verification.status == ReleaseStatus.READY:
        banner = _colorize("[OK] READY FOR RELEASE", _GREEN, _BOLD, no_color=nc)
    else:
        banner = _colorize("[BLOCKED] RELEASE BLOCKED", _RED, _BOLD, no_color=nc)

    print(f"\n{banner}\n")
    print(f"  Producer Service : {verification.producer_service}")
    print(f"  Contract Status  : {verification.contract_checks_status}")
    print(f"  Breaking Changes : {verification.breaking_changes_count}")
    print(f"  Consumers Checked: {len(verification.consumers_checked)}")
    print(f"  Affected         : {len(verification.affected_consumers)}")
    print(f"\nReasons:")
    for r in verification.reasons:
        print(f"  - {r}")
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
    elif args.command == "verify":
        sys.exit(cmd_verify(args))
    elif args.command == "evidence":
        sys.exit(cmd_evidence(args))


if __name__ == "__main__":
    main()
