"""CLI entry point: python -m contract_guard compare producer.yaml consumer.yaml"""

from __future__ import annotations

import argparse
import sys

from .comparator import Comparator
from .config import load_config
from .models import Severity


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="contract-guard",
        description="Deterministic OpenAPI contract compatibility checker.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

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
    return parser


# ANSI helpers
_RED = "\033[31m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_BOLD = "\033[1m"
_RESET = "\033[0m"


def _colorize(text: str, *codes: str, no_color: bool = False) -> str:
    if no_color:
        return text
    return "".join(codes) + text + _RESET


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

        # Reuse the compare printer by constructing a minimal namespace
        inner = argparse.Namespace(
            producer=str(dep.producer_contract),
            consumer=str(dep.consumer_contract),
            no_color=nc,
        )
        rc = cmd_compare(inner)
        if rc != 0:
            overall_ok = False

    return 0 if overall_ok else 1


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    if args.command == "compare":
        sys.exit(cmd_compare(args))
    if args.command == "check":
        sys.exit(cmd_check(args))


if __name__ == "__main__":
    main()
