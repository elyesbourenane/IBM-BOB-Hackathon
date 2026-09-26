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

import yaml

from .comparator import Comparator
from .discovery import discover_and_check, DiscoveryReport
from .evidence import evaluate_release_gate, generate_evidence, EvidenceReport, ReleaseStatus
from .git import get_file_content_at_ref, inspect_git_status, GitStatus
from .loader import load_contract
from .models import Finding
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


def _detect_producer_contract_changes(
    ws: Path,
    git_status: GitStatus,
    base_ref: Optional[str],
    report: DiscoveryReport,
    producer_filter: Optional[str] = None,
) -> tuple[list[Finding], bool]:
    """
    Compare changed producer contracts at HEAD/working tree against their baseline at base_ref.
    Returns (producer_findings, has_producer_contract_changes).
    """
    known_producer_paths = {
        str(Path(r.producer_contract).resolve())
        for r in report.results
        if r.producer_contract and (not producer_filter or r.producer_service == producer_filter)
    }
    known_consumer_paths = {
        str(Path(r.consumer_contract).resolve())
        for r in report.results
        if r.consumer_contract
    }

    # Identify changed producer contracts
    changed_producer_contracts: list[str] = []
    for c_file in git_status.changed_contracts:
        abs_p = str((ws / c_file).resolve())
        if abs_p in known_consumer_paths:
            # Skip consumer contracts - they do not dictate producer SemVer
            continue
        if known_producer_paths and abs_p not in known_producer_paths:
            continue
        changed_producer_contracts.append(c_file)

    # If no specific producer found via discovery configs, but contracts were changed
    if not changed_producer_contracts and git_status.changed_contracts and not known_producer_paths:
        changed_producer_contracts = [
            c for c in git_status.changed_contracts
            if not ("/contracts/" in c.replace("\\", "/").lower())
        ] or git_status.changed_contracts

    producer_findings: list[Finding] = []
    has_producer_changes = bool(changed_producer_contracts)

    # For each changed producer contract, diff HEAD against base_ref
    for c_file in changed_producer_contracts:
        abs_c_path = ws / c_file
        if not abs_c_path.exists():
            continue

        effective_base = base_ref or "HEAD"
        base_content = get_file_content_at_ref(ws, c_file, effective_base)

        try:
            head_text = abs_c_path.read_text(encoding="utf-8")
        except Exception:
            head_text = ""

        if not base_ref and (base_content is None or base_content.strip() == head_text.strip()):
            alt_content = get_file_content_at_ref(ws, c_file, "HEAD~1")
            if alt_content is not None:
                base_content = alt_content

        if base_content is not None:
            try:
                base_doc = yaml.safe_load(base_content)
                head_doc = load_contract(abs_c_path)
                if isinstance(base_doc, dict) and isinstance(head_doc, dict):
                    cmp = Comparator(abs_c_path, abs_c_path)
                    diff_report = cmp._compare_docs(producer_doc=head_doc, consumer_doc=base_doc)
                    producer_findings.extend(diff_report.findings)
            except Exception:
                pass

    return producer_findings, has_producer_changes


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

    # 3. Detect API version from producer contract if not explicitly supplied
    detected_version = current_version
    if not detected_version and report.results:
        for r in report.results:
            if producer_filter and r.producer_service != producer_filter:
                continue
            if r.producer_contract and Path(r.producer_contract).exists():
                ver = _extract_contract_version(r.producer_contract)
                if ver:
                    detected_version = ver
                    break

    if not detected_version and git_status.changed_contracts:
        for c_file in git_status.changed_contracts:
            # Avoid extracting version from consumer contract copies
            if "/contracts/" in c_file.replace("\\", "/").lower():
                continue
            full_c_path = ws / c_file
            if full_c_path.exists():
                ver = _extract_contract_version(full_c_path)
                if ver:
                    detected_version = ver
                    break

    if not detected_version and git_status.changed_contracts:
        for c_file in git_status.changed_contracts:
            full_c_path = ws / c_file
            if full_c_path.exists():
                ver = _extract_contract_version(full_c_path)
                if ver:
                    detected_version = ver
                    break

    # 4. SemVer recommendation
    # Evaluate the producer contract change directly against Git baseline
    producer_findings, has_producer_changes = _detect_producer_contract_changes(
        ws=ws,
        git_status=git_status,
        base_ref=base_ref,
        report=report,
        producer_filter=producer_filter,
    )

    all_consumers_compatible = (
        len(report.consumers_checked) > 0 and len(report.affected_consumers) == 0
    )

    if producer_findings or has_producer_changes:
        effective_findings = producer_findings
        has_changes = has_producer_changes
    else:
        # Fallback when git diff is not available (e.g. non-git directory or mock tests)
        all_comparison_findings = []
        for r in report.results:
            all_comparison_findings.extend(r.findings)
        effective_findings = all_comparison_findings if all_comparison_findings else report.breaking_findings
        has_changes = bool(git_status.changed_contracts or report.breaking_findings or all_comparison_findings)

    semver_rec = calculate_semver_recommendation(
        findings=effective_findings,
        has_contract_changes=has_changes,
        current_version=detected_version,
        all_consumers_compatible=all_consumers_compatible,
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
