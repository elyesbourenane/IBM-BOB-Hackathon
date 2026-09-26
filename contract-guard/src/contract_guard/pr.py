"""
Pull Request (PR) and Git-aware contract safety analysis.

Coordinates:
Git change detection -> Consumer discovery -> Deterministic compatibility analysis
-> Blast radius -> SemVer recommendation -> Verdict -> PR-ready Markdown / JSON / Evidence.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .discovery import discover_and_check, DiscoveryReport
from .evidence import evaluate_release_gate, generate_evidence, EvidenceReport, ReleaseStatus
from .git import inspect_git_status, GitStatus
from .loader import load_contract
from .versioning import calculate_semver_recommendation, SemVerRecommendation


@dataclass
class PRReport:
    """Consolidated PR analysis report."""

    workspace_root: str
    repository: Optional[str]
    commit: Optional[str]
    base: Optional[str]
    changed_contracts: list[str]
    other_changed_files: list[str]
    consumers_checked: list[str]
    compatible_consumers: list[str]
    affected_consumers: list[str]
    breaking_findings: list[dict[str, Any]]
    blast_radius_summary: dict[str, Any]
    semver: SemVerRecommendation
    verdict: str  # "READY" | "BLOCKED"
    is_ready: bool
    evidence_id: str
    reasons: list[str] = field(default_factory=list)
    git_error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "repository": self.repository,
            "commit": self.commit,
            "base": self.base,
            "changed_contracts": list(self.changed_contracts),
            "other_changed_files": list(self.other_changed_files),
            "consumers_checked": len(self.consumers_checked),
            "consumers_checked_list": list(self.consumers_checked),
            "compatible_consumers": len(self.compatible_consumers),
            "compatible_consumers_list": list(self.compatible_consumers),
            "affected_consumers": len(self.affected_consumers),
            "affected_consumers_list": list(self.affected_consumers),
            "breaking_findings": list(self.breaking_findings),
            "blast_radius_summary": self.blast_radius_summary,
            "semver": self.semver.to_dict(),
            "verdict": self.verdict,
            "is_ready": self.is_ready,
            "evidence_id": self.evidence_id,
            "reasons": list(self.reasons),
            "git_error": self.git_error,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    def to_markdown(self) -> str:
        """Render a PR-ready Markdown report suitable for GitHub/GitLab comments."""
        status_badge = "READY" if self.is_ready else "BLOCKED"
        lines = [
            "# ContractGuard PR Analysis",
            "",
            f"**Verdict:** `{status_badge}`",
            "",
            "## Summary",
            "",
            "| Metric | Result |",
            "|---|---:|",
            f"| Consumers checked | {len(self.consumers_checked)} |",
            f"| Affected consumers | {len(self.affected_consumers)} |",
            f"| Breaking changes | {len(self.breaking_findings)} |",
            "",
        ]

        if self.changed_contracts:
            lines.extend([
                "## Changed Contracts",
                "",
            ])
            for c in self.changed_contracts:
                lines.append(f"- `{c}`")
            lines.append("")

        if self.breaking_findings:
            lines.extend([
                "## Breaking Changes",
                "",
            ])
            for f in self.breaking_findings:
                ep = f.get("endpoint", "N/A")
                field_name = f.get("affected_field", "N/A")
                ck = f.get("change_kind", "N/A")
                detail = f.get("detail", "")
                c_svc = f.get("consumer_service", "N/A")
                lines.append(f"### {ep}")
                lines.append("")
                lines.append(f"- **Field:** `{field_name}`")
                lines.append(f"- **Type:** `{ck}`")
                lines.append(f"- **Consumer Affected:** `{c_svc}`")
                if detail:
                    lines.append(f"- **Detail:** {detail}")
                lines.append("")

        if self.affected_consumers:
            lines.extend([
                "## Affected Consumers",
                "",
            ])
            for cons in self.affected_consumers:
                lines.append(f"- {cons}")
            lines.append("")

        lines.extend([
            "## SemVer Recommendation",
            "",
            f"**{self.semver.bump.upper()}**",
            "",
        ])
        if self.semver.current_version and self.semver.recommended_version:
            lines.append(f"`{self.semver.current_version} -> {self.semver.recommended_version}`")
            lines.append("")
        if self.semver.reason:
            lines.append(f"Reason: {self.semver.reason}")
            lines.append("")

        lines.extend([
            "## Evidence",
            "",
            f"Evidence ID: `{self.evidence_id}`",
            "",
        ])

        return "\n".join(lines)


def _extract_contract_version(contract_path: Path | str) -> Optional[str]:
    """Attempt to read info.version from an OpenAPI contract file."""
    try:
        doc = load_contract(contract_path)
        info = doc.get("info")
        if isinstance(info, dict):
            ver = info.get("version")
            if ver is not None:
                return str(ver).strip()
    except Exception:
        pass
    return None


def analyze_pr(
    workspace_root: str | Path,
    base_ref: Optional[str] = None,
    producer_filter: Optional[str] = None,
    current_version: Optional[str] = None,
) -> PRReport:
    """
    Perform a complete Git-aware PR and contract change analysis.

    Parameters
    ----------
    workspace_root:
        Path to workspace directory.
    base_ref:
        Optional git ref to compare against (e.g. 'origin/main', 'HEAD~1').
    producer_filter:
        Optional producer service name filter.
    current_version:
        Optional baseline version. If None, tries to read from changed contract or repo.

    Returns
    -------
    PRReport
        Comprehensive structured report.
    """
    ws = Path(workspace_root).resolve()
    git_status = inspect_git_status(ws, base_ref=base_ref)

    # 1. Consumer discovery and contract compatibility check
    report: DiscoveryReport = discover_and_check(ws, producer_filter=producer_filter)

    # 2. Release gate evaluation
    verification = evaluate_release_gate(
        report,
        producer_service=producer_filter or "producer",
        test_results={"status": "PASS", "details": "PR pre-merge contract evaluation"},
    )

    # 3. Detect version if not explicitly supplied
    detected_version = current_version
    if not detected_version and git_status.changed_contracts:
        for c_file in git_status.changed_contracts:
            full_c_path = ws / c_file
            if full_c_path.exists():
                ver = _extract_contract_version(full_c_path)
                if ver:
                    detected_version = ver
                    break

    # If still not found, check discovered producer contracts
    if not detected_version and report.results:
        for r in report.results:
            if r.producer_contract and Path(r.producer_contract).exists():
                ver = _extract_contract_version(r.producer_contract)
                if ver:
                    detected_version = ver
                    break
    # Collect all findings across all consumer-producer comparisons
    all_findings = []
    for r in report.results:
        all_findings.extend(r.findings)

    # 4. SemVer recommendation
    semver_rec = calculate_semver_recommendation(
        findings=all_findings if all_findings else report.breaking_findings,
        has_contract_changes=bool(git_status.changed_contracts or report.breaking_findings or all_findings),
        current_version=detected_version,
    )

    # 5. Deterministic evidence generation
    evidence: EvidenceReport = generate_evidence(
        report=report,
        verification=verification,
        repository_path=git_status.repo_root or str(ws),
        commit_sha=git_status.current_sha,
        base_ref=base_ref,
        semver=semver_rec.to_dict(),
        blast_radius_summary=report.blast_radius_summary.to_dict(),
    )

    return PRReport(
        workspace_root=str(ws),
        repository=Path(git_status.repo_root).name if git_status.repo_root else ws.name,
        commit=git_status.current_sha,
        base=base_ref,
        changed_contracts=git_status.changed_contracts,
        other_changed_files=git_status.other_changed_files,
        consumers_checked=report.consumers_checked,
        compatible_consumers=report.compatible_consumers,
        affected_consumers=report.affected_consumers,
        breaking_findings=report.breaking_findings,
        blast_radius_summary=report.blast_radius_summary.to_dict(),
        semver=semver_rec,
        verdict=verification.status.value,
        is_ready=verification.is_ready,
        evidence_id=evidence.evidence_id,
        reasons=verification.reasons,
        git_error=git_status.error,
    )
