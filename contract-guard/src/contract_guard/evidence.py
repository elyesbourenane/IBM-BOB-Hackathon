"""
Release safety gate and reproducible release evidence generator.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from .discovery import DiscoveryReport
from .models import Finding

CONTRACTGUARD_VERSION = "0.1.0"

DETERMINISTIC_CHECKS = [
    "check_removed_fields",
    "check_type_changes",
    "check_required_added",
    "check_optional_added",
    "detect_renames",
    "workspace_consumer_discovery",
    "deterministic_blast_radius_scan",
]


class ReleaseStatus(str, Enum):
    READY = "READY"
    BLOCKED = "BLOCKED"


@dataclass
class ReleaseVerification:
    """Outcome of evaluating the deterministic release gate."""

    status: ReleaseStatus
    producer_service: str
    workspace_root: str
    configs_found: int
    consumers_checked: list[str]
    compatible_consumers: list[str]
    affected_consumers: list[str]
    breaking_changes_count: int
    contract_checks_status: str  # "PASS" | "FAIL"
    test_results: Optional[dict[str, Any]] = None
    reasons: list[str] = field(default_factory=list)

    @property
    def is_ready(self) -> bool:
        return self.status == ReleaseStatus.READY

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "is_ready": self.is_ready,
            "producer_service": self.producer_service,
            "workspace_root": self.workspace_root,
            "configs_found": self.configs_found,
            "consumers_checked": self.consumers_checked,
            "compatible_consumers": self.compatible_consumers,
            "affected_consumers": self.affected_consumers,
            "breaking_changes_count": self.breaking_changes_count,
            "contract_checks_status": self.contract_checks_status,
            "test_results": self.test_results,
            "reasons": self.reasons,
        }


def evaluate_release_gate(
    report: DiscoveryReport,
    producer_service: str = "payment-service",
    test_results: Optional[dict[str, Any]] = None,
) -> ReleaseVerification:
    """
    Deterministically evaluate whether an API change is safe for release.
    The decision is 100% deterministic and never influenced or overridden by LLM output.
    """
    reasons: list[str] = []
    breaking_count = len(report.breaking_findings)
    contract_checks_pass = (len(report.affected_consumers) == 0 and breaking_count == 0)

    if not contract_checks_pass:
        reasons.append(
            f"Downstream API contracts are incompatible: {len(report.affected_consumers)} "
            f"affected consumer(s) with {breaking_count} breaking finding(s)."
        )

    tests_pass = True
    if test_results:
        test_status = test_results.get("status", "PASS").upper()
        if test_status != "PASS":
            tests_pass = False
            reasons.append(f"Automated test suite failed: {test_results.get('detail', 'Tests reported FAIL')}")

    is_ready = contract_checks_pass and tests_pass
    status = ReleaseStatus.READY if is_ready else ReleaseStatus.BLOCKED

    if is_ready:
        reasons.append("All consumer contracts are compatible and all verified tests passed.")

    return ReleaseVerification(
        status=status,
        producer_service=producer_service,
        workspace_root=report.workspace_root,
        configs_found=report.configs_found,
        consumers_checked=report.consumers_checked,
        compatible_consumers=report.compatible_consumers,
        affected_consumers=report.affected_consumers,
        breaking_changes_count=breaking_count,
        contract_checks_status="PASS" if contract_checks_pass else "FAIL",
        test_results=test_results,
        reasons=reasons,
    )


@dataclass
class EvidenceReport:
    """Machine-readable, reproducible audit artifact verifying release safety."""

    producer_service: str
    workspace_root: str
    changed_contracts: list[str]
    consumers_checked: list[str]
    compatible_consumers: list[str]
    affected_consumers: list[str]
    findings: list[dict[str, Any]]
    deterministic_checks_performed: list[str]
    verdict: str
    reasons: list[str]
    test_results: Optional[dict[str, Any]] = None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    version: str = CONTRACTGUARD_VERSION
    evidence_id: str = ""

    def __post_init__(self) -> None:
        if not self.evidence_id:
            self.evidence_id = self.compute_stable_hash()

    def compute_stable_hash(self) -> str:
        """
        Generate a stable, tamper-evident SHA-256 identifier based on substantive content.
        Excludes transient timestamp and self-referential ID.
        Findings are canonically sorted so the identifier is deterministic across platforms.
        """
        sorted_findings = sorted(
            self.findings,
            key=lambda f: (
                str(f.get("consumer_service", "")),
                str(f.get("endpoint", "")),
                str(f.get("affected_field", "")),
                str(f.get("change_kind", "")),
            ),
        )
        substantive = {
            "version": self.version,
            "producer_service": self.producer_service,
            "changed_contracts": sorted(self.changed_contracts),
            "consumers_checked": sorted(self.consumers_checked),
            "compatible_consumers": sorted(self.compatible_consumers),
            "affected_consumers": sorted(self.affected_consumers),
            "findings": sorted_findings,
            "deterministic_checks_performed": sorted(self.deterministic_checks_performed),
            "verdict": self.verdict,
            "reasons": sorted(self.reasons),
            "test_results": self.test_results,
        }
        canonical_bytes = json.dumps(substantive, sort_keys=True).encode("utf-8")
        digest = hashlib.sha256(canonical_bytes).hexdigest()
        return f"cg-ev-{digest[:16]}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "contractguard_version": self.version,
            "timestamp": self.timestamp,
            "verdict": self.verdict,
            "producer_service": self.producer_service,
            "workspace_root": self.workspace_root,
            "changed_contracts": self.changed_contracts,
            "consumers_checked": self.consumers_checked,
            "compatible_consumers": self.compatible_consumers,
            "affected_consumers": self.affected_consumers,
            "findings": self.findings,
            "deterministic_checks_performed": self.deterministic_checks_performed,
            "test_results": self.test_results,
            "reasons": self.reasons,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    def to_markdown(self) -> str:
        """Render a concise, human-readable Markdown audit report."""
        status_badge = "[OK] READY FOR RELEASE" if self.verdict == "READY" else "[BLOCKED] RELEASE BLOCKED"
        lines = [
            f"# ContractGuard Release Verification Report",
            f"",
            f"**Verdict:** `{status_badge}`  ",
            f"**Evidence ID:** `{self.evidence_id}`  ",
            f"**Timestamp (UTC):** `{self.timestamp}`  ",
            f"**ContractGuard Version:** `{self.version}`  ",
            f"",
            f"---",
            f"",
            f"## Scope & Context",
            f"- **Producer Service:** `{self.producer_service}`",
            f"- **Workspace Root:** `{self.workspace_root}`",
            f"- **Consumers Checked:** {len(self.consumers_checked)} ({', '.join(self.consumers_checked) if self.consumers_checked else 'None'})",
            f"- **Compatible Consumers:** {len(self.compatible_consumers)} ({', '.join(self.compatible_consumers) if self.compatible_consumers else 'None'})",
            f"- **Affected Consumers:** {len(self.affected_consumers)} ({', '.join(self.affected_consumers) if self.affected_consumers else 'None'})",
            f"",
            f"## Verdict Reasons",
        ]
        for r in self.reasons:
            lines.append(f"- {r}")

        lines.extend([
            f"",
            f"## Contract Differences ({len(self.findings)})",
        ])
        if not self.findings:
            lines.append("No contract differences detected.")
        else:
            lines.append("| Consumer | Endpoint | Field | Change | Severity | Detail |")
            lines.append("|---|---|---|---|---|---|")
            for f in self.findings:
                c_svc = f.get("consumer_service", "N/A")
                ep = f.get("endpoint", "N/A")
                field_name = f.get("affected_field", "N/A")
                ck = f.get("change_kind", "N/A")
                sev = f.get("severity", "N/A")
                detail = f.get("detail", "").replace("|", "\\|")
                lines.append(f"| `{c_svc}` | `{ep}` | `{field_name}` | `{ck}` | `{sev}` | {detail} |")

        if self.test_results:
            lines.extend([
                f"",
                f"## Automated Tests",
                f"- **Status:** `{self.test_results.get('status', 'UNKNOWN')}`",
                f"- **Details:** {self.test_results.get('details', 'N/A')}",
            ])

        lines.extend([
            f"",
            f"## Deterministic Checks Applied",
        ])
        for chk in self.deterministic_checks_performed:
            lines.append(f"- `{chk}`")

        lines.append("")
        return "\n".join(lines)

    def write(
        self,
        output_dir: Path | str,
        json_filename: str = "contractguard-evidence.json",
        md_filename: str = "contractguard-report.md",
    ) -> tuple[Path, Path]:
        """Write JSON and Markdown evidence files to the target directory."""
        out_path = Path(output_dir).resolve()
        out_path.mkdir(parents=True, exist_ok=True)

        json_file = out_path / json_filename
        md_file = out_path / md_filename

        json_file.write_text(self.to_json(), encoding="utf-8")
        md_file.write_text(self.to_markdown(), encoding="utf-8")

        return json_file, md_file


def generate_evidence(
    report: DiscoveryReport,
    verification: ReleaseVerification,
    output_dir: Optional[Path | str] = None,
) -> EvidenceReport:
    """Factory to construct and optionally write the EvidenceReport."""
    changed_contracts = list(
        {r.producer_contract for r in report.results if r.producer_contract}
    )
    evidence = EvidenceReport(
        producer_service=verification.producer_service,
        workspace_root=report.workspace_root,
        changed_contracts=changed_contracts,
        consumers_checked=report.consumers_checked,
        compatible_consumers=report.compatible_consumers,
        affected_consumers=report.affected_consumers,
        findings=report.breaking_findings,
        deterministic_checks_performed=list(DETERMINISTIC_CHECKS),
        verdict=verification.status.value,
        reasons=verification.reasons,
        test_results=verification.test_results,
    )
    if output_dir:
        evidence.write(output_dir)
    return evidence
