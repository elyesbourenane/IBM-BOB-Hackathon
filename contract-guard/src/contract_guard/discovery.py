"""
Workspace-wide consumer discovery and bulk compatibility check.

Given a workspace root directory, this module:

1. Recursively finds every ``contractguard.yaml`` file under that root.
2. Parses each one with :func:`~contract_guard.config.load_config`.
3. Groups consumers by the producer service they depend on.
4. Runs :class:`~contract_guard.comparator.Comparator` for each
   (consumer, producer) pair.
5. Returns a :class:`DiscoveryReport` that summarises the results.

Only the discovery/check logic lives here; the MCP wiring is in
``mcp_server.py``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .comparator import Comparator
from .config import load_config, ContractGuardConfig, DependencyConfig
from .impact import BlastRadiusSummary, ConsumerImpact, scan_consumer_impact, summarize_blast_radius
from .models import ChangeKind, ComparisonReport, Finding, Severity


# ---------------------------------------------------------------------------
# Result models
# ---------------------------------------------------------------------------

@dataclass
class ConsumerResult:
    """Outcome of checking one consumer dependency against its producer."""

    consumer_service: str
    producer_service: str
    consumer_contract: str    # resolved absolute path (str for JSON serialisation)
    producer_contract: str    # resolved absolute path (str for JSON serialisation)
    is_compatible: bool
    verdict: str
    findings: list[Finding] = field(default_factory=list)
    error: str | None = None  # set when the comparison itself failed
    impacts: list[ConsumerImpact] = field(default_factory=list)


@dataclass
class DiscoveryReport:
    """Aggregated result of a workspace-wide consumer discovery and check."""

    workspace_root: str
    producer_filter: str | None          # None means all producers
    configs_found: int                   # total contractguard.yaml files discovered
    consumers_checked: list[str]         # consumer service names that were evaluated
    compatible_consumers: list[str]      # subset that passed
    affected_consumers: list[str]        # subset that broke or errored
    results: list[ConsumerResult]        # one entry per (consumer, dependency) pair
    breaking_findings: list[dict[str, Any]]  # flat list of all breaking findings
    impacts: list[ConsumerImpact] = field(default_factory=list)

    @property
    def blast_radius_summary(self) -> BlastRadiusSummary:
        return summarize_blast_radius(
            self.impacts,
            direct_consumers=len(self.consumers_checked),
            transitive_consumers=0,
        )

    @property
    def summary(self) -> str:
        total = len(self.consumers_checked)
        compat = len(self.compatible_consumers)
        affected = len(self.affected_consumers)
        return (
            f"{total} consumer(s) checked against "
            f"{'all producers' if self.producer_filter is None else repr(self.producer_filter)}: "
            f"{compat} compatible, {affected} affected."
        )


# ---------------------------------------------------------------------------
# Discovery logic
# ---------------------------------------------------------------------------

SKIP_DISCOVERY_DIRS = {
    ".git",
    ".github",
    "node_modules",
    ".idea",
    ".vscode",
    "__pycache__",
    ".pytest_cache",
    ".venv",
    "target",
    "build",
    "dist",
    ".gradle",
    "venv",
}


def _find_config_files(workspace_root: Path) -> list[Path]:
    """Return all ``contractguard.yaml`` or ``contractguard.yml`` files under *workspace_root*."""
    found: list[Path] = []
    for root, dirs, files in os.walk(workspace_root):
        dirs[:] = [d for d in dirs if d not in SKIP_DISCOVERY_DIRS]
        for f in files:
            if f in ("contractguard.yaml", "contractguard.yml"):
                found.append(Path(root) / f)
    return sorted(found)


def _finding_to_dict(f: Finding) -> dict[str, Any]:
    return {
        "endpoint": f.endpoint,
        "affected_field": f.affected_field,
        "change_kind": f.change_kind.value,
        "severity": f.severity.value,
        "detail": f.detail,
        "reason": f.reason,
    }


def discover_and_check(
    workspace_root: str | Path,
    producer_filter: str | None = None,
) -> DiscoveryReport:
    """
    Discover all ``contractguard.yaml`` files under *workspace_root* and check
    each declared dependency.

    Parameters
    ----------
    workspace_root:
        Directory to search recursively for ``contractguard.yaml`` files.
    producer_filter:
        When set, only dependencies whose ``service`` matches this string are
        checked.  Pass ``None`` (default) to check all dependencies.

    Returns
    -------
    DiscoveryReport
        Structured report — deterministic; no randomness or side-effects.

    Raises
    ------
    FileNotFoundError
        If *workspace_root* does not exist.
    NotADirectoryError
        If *workspace_root* is not a directory.
    """
    workspace_root = Path(workspace_root).resolve()
    if not workspace_root.exists():
        raise FileNotFoundError(f"Workspace root not found: {workspace_root}")
    if not workspace_root.is_dir():
        raise NotADirectoryError(f"Not a directory: {workspace_root}")

    config_paths = _find_config_files(workspace_root)
    all_results: list[ConsumerResult] = []

    for config_path in config_paths:
        try:
            config: ContractGuardConfig = load_config(config_path)
        except (ValueError, FileNotFoundError) as exc:
            # Malformed config — record an error finding and result per file
            err_finding = Finding(
                endpoint="CONFIG",
                affected_field=config_path.name,
                change_kind=ChangeKind.CONTRACT_ERROR,
                detail=str(exc),
            )
            all_results.append(
                ConsumerResult(
                    consumer_service=str(config_path),
                    producer_service="",
                    consumer_contract="",
                    producer_contract="",
                    is_compatible=False,
                    verdict="error",
                    findings=[err_finding],
                    error=str(exc),
                )
            )
            continue

        for dep in config.dependencies:
            if producer_filter is not None and dep.service != producer_filter:
                continue

            try:
                report: ComparisonReport = Comparator(
                    dep.producer_contract, dep.consumer_contract
                ).compare()
                impacts: list[ConsumerImpact] = []
                for f in report.findings:
                    if f.is_breaking:
                        impacts.append(
                            scan_consumer_impact(
                                consumer_dir=config.base_dir,
                                consumer_service=config.service,
                                producer_service=dep.service,
                                consumer_contract=dep.consumer_contract,
                                producer_contract=dep.producer_contract,
                                finding=f,
                            )
                        )
                all_results.append(
                    ConsumerResult(
                        consumer_service=config.service,
                        producer_service=dep.service,
                        consumer_contract=str(dep.consumer_contract),
                        producer_contract=str(dep.producer_contract),
                        is_compatible=report.is_compatible,
                        verdict=report.verdict,
                        findings=report.findings,
                        impacts=impacts,
                    )
                )
            except (FileNotFoundError, ValueError, KeyError) as exc:
                err_finding = Finding(
                    endpoint="CONTRACT",
                    affected_field=Path(dep.consumer_contract).name,
                    change_kind=ChangeKind.CONTRACT_ERROR,
                    detail=str(exc),
                )
                all_results.append(
                    ConsumerResult(
                        consumer_service=config.service,
                        producer_service=dep.service,
                        consumer_contract=str(dep.consumer_contract),
                        producer_contract=str(dep.producer_contract),
                        is_compatible=False,
                        verdict="error",
                        findings=[err_finding],
                        error=str(exc),
                    )
                )

    # Build summary lists (deduplicated by consumer service name)
    consumers_checked = list(dict.fromkeys(
        r.consumer_service for r in all_results
    ))
    compatible_consumers = list(dict.fromkeys(
        r.consumer_service
        for r in all_results
        if r.is_compatible and r.error is None
        # A consumer is only "compatible" if ALL its checked deps passed
    ))
    # Remove any service that has at least one breaking/error result
    affected_set = {
        r.consumer_service for r in all_results if not r.is_compatible
    }
    compatible_consumers = [c for c in compatible_consumers if c not in affected_set]
    affected_consumers = [c for c in consumers_checked if c in affected_set]

    breaking_findings: list[dict[str, Any]] = []
    all_impacts: list[ConsumerImpact] = []
    for r in all_results:
        all_impacts.extend(r.impacts)
        for f in r.findings:
            if f.is_breaking:
                breaking_findings.append({
                    "consumer_service": r.consumer_service,
                    "producer_service": r.producer_service,
                    **_finding_to_dict(f),
                })

    return DiscoveryReport(
        workspace_root=str(workspace_root),
        producer_filter=producer_filter,
        configs_found=len(config_paths),
        consumers_checked=consumers_checked,
        compatible_consumers=compatible_consumers,
        affected_consumers=affected_consumers,
        results=all_results,
        breaking_findings=breaking_findings,
        impacts=all_impacts,
    )
