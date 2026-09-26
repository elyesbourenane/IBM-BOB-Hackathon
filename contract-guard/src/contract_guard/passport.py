"""
Change Passport module for ContractGuard Phase 3C.

Provides a unified, deterministic, machine-readable representation of an API change
and everything ContractGuard knows about it:
- What changed (SemanticChange)
- Who is affected (BlastRadiusSummary & DependencyGraph)
- What actions are required (RepairMission)
- What SemVer bump applies (SemVerRecommendation)
- What the current verification & release status is (ReleaseVerification)

Adheres strictly to:
    AI reasons. Deterministic checks decide. Bob executes. Deterministic verification proves.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .discovery import discover_and_check, DiscoveryReport
from .evidence import evaluate_release_gate, ReleaseVerification, ReleaseStatus
from .graph import build_dependency_graph, DependencyGraph
from .mission import generate_repair_mission, RepairMission, SemanticChange
from .versioning import calculate_semver_recommendation, SemVerRecommendation


@dataclass
class ChangePassport:
    """Unified machine-readable change passport for an API contract modification."""

    passport_id: str
    producer: str
    contract: str
    change: dict[str, Any]
    impact: dict[str, Any]
    release: dict[str, Any]
    verification: dict[str, Any]
    dependency_graph: dict[str, Any]
    repair_mission: dict[str, Any]
    evidence_id: Optional[str] = None

    @property
    def release_status(self) -> str:
        return self.verification.get("status", "BLOCKED")

    @property
    def semver(self) -> dict[str, Any]:
        return self.release

    def to_dict(self) -> dict[str, Any]:
        return {
            "passport_id": self.passport_id,
            "producer": self.producer,
            "contract": self.contract,
            "change": self.change,
            "impact": self.impact,
            "release": self.release,
            "release_status": self.release_status,
            "verification": self.verification,
            "dependency_graph": self.dependency_graph,
            "repair_mission": self.repair_mission,
            "evidence_id": self.evidence_id,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    def to_markdown(self) -> str:
        """Render a PR-ready Markdown passport report."""
        return self.format_markdown()

    def format_markdown(self) -> str:
        """Render a PR-ready Markdown passport report."""
        ch = self.change
        imp = self.impact
        rel = self.release
        ver = self.verification
        mis = self.repair_mission

        change_line = f"`{ch.get('field', '')}` -> `{ch.get('new_field', ch.get('new_value', ''))}`" if ch.get("new_field") or ch.get("new_value") else f"`{ch.get('field', 'None')}`"

        lines = [
            f"# CONTRACTGUARD CHANGE PASSPORT: {self.passport_id}",
            "",
            f"**Producer:** `{self.producer}`  ",
            f"**Contract:** `{self.contract}`  ",
            f"**Release Status:** **{ver.get('status', 'UNKNOWN')}**  ",
            f"**SemVer Bump:** `{rel.get('from', '?')} -> {rel.get('to', '?')}` ({rel.get('semver', 'NONE')})  ",
            "",
            "## 1. Semantic Change",
            f"- **Endpoint:** `{ch.get('endpoint', 'N/A')}`",
            f"- **Method:** `{ch.get('method', 'N/A')}`",
            f"- **Change Kind:** `{ch.get('kind', 'N/A')}`",
            f"- **Change:** {change_line}",
            f"- **Compatibility:** `{ch.get('compatibility', 'N/A')}`",
            f"- **Reason:** {ch.get('reason', 'N/A')}",
            "",
            "## 2. Blast Radius & Consumer Impact",
            "| Metric | Count |",
            "|---|---|",
            f"| Direct Consumers | {imp.get('direct_consumers', 0)} |",
            f"| Affected Consumers | {imp.get('affected_consumers', 0)} |",
            f"| Contract-Only Consumers | {imp.get('contract_only_consumers', 0)} |",
            f"| Confirmed Source Files | {len(imp.get('confirmed_source_files', []))} |",
            f"| Confirmed Test Files | {len(imp.get('confirmed_test_files', []))} |",
            f"| Likely Source Files | {len(imp.get('likely_source_files', []))} |",
            f"| Transitive Consumers | {imp.get('transitive_consumers', 0)} |",
            "",
        ]

        if imp.get("confirmed_source_files"):
            lines.append("### Confirmed Source Files")
            for f in imp["confirmed_source_files"]:
                lines.append(f"- `{f}`")
            lines.append("")

        if imp.get("confirmed_test_files"):
            lines.append("### Confirmed Test Files")
            for f in imp["confirmed_test_files"]:
                lines.append(f"- `{f}`")
            lines.append("")

        lines.extend([
            "## 3. Repair Mission Overview",
            f"- **Mission ID:** `{mis.get('mission_id', 'N/A')}`",
            f"- **Title:** {mis.get('title', 'N/A')}",
            f"- **Status:** `{mis.get('status', 'N/A')}`",
            "",
            "### Required Actions",
        ])
        for act in mis.get("required_actions", []):
            lines.append(f"1. {act}")
        lines.append("")

        lines.extend([
            "## 4. Verification & Next Steps",
            f"- **Verification Status:** `{ver.get('status', 'UNKNOWN')}`",
            f"- **Compatible Consumers:** {ver.get('compatible_consumers', 0)}",
            f"- **Incompatible Consumers:** {ver.get('incompatible_consumers', 0)}",
            f"- **Breaking Findings:** {ver.get('breaking_findings', 0)}",
            f"- **Next Step:** `{ver.get('next_step', 'N/A')}`",
            "",
        ])

        if ver.get("remaining_actions"):
            lines.append("### Remaining Actions Before Release")
            for ra in ver["remaining_actions"]:
                lines.append(f"- [ ] {ra}")
            lines.append("")

        return "\n".join(lines)

    def format_text(self, no_color: bool = False) -> str:
        return self.render_text()

    def render_text(self) -> str:
        """Render human/agent readable text format."""
        ch = self.change
        imp = self.impact
        rel = self.release
        ver = self.verification
        mis = self.repair_mission

        change_line = f"{ch.get('field', '')} -> {ch.get('new_field', ch.get('new_value', ''))}" if ch.get("new_field") or ch.get("new_value") else ch.get("field", "None")

        lines = [
            "=" * 80,
            f"CONTRACTGUARD CHANGE PASSPORT: {self.passport_id}",
            "=" * 80,
            f"Producer:       {self.producer}",
            f"Contract:       {self.contract}",
            f"Release Status: {ver.get('status', 'UNKNOWN')}",
            f"SemVer:         {rel.get('from', '?')} -> {rel.get('to', '?')} ({rel.get('semver', 'NONE')})",
            "",
            "SEMANTIC CHANGE",
            f"  Endpoint:      {ch.get('endpoint', 'N/A')}",
            f"  Method:        {ch.get('method', 'N/A')}",
            f"  Change Kind:   {ch.get('kind', 'N/A')}",
            f"  Change:        {change_line}",
            f"  Compatibility: {ch.get('compatibility', 'N/A')}",
            f"  Reason:        {ch.get('reason', 'N/A')}",
            "",
            "IMPACT & BLAST RADIUS",
            f"  Direct Consumers:        {imp.get('direct_consumers', 0)}",
            f"  Affected Consumers:      {imp.get('affected_consumers', 0)}",
            f"  Contract-Only Consumers: {imp.get('contract_only_consumers', 0)}",
            f"  Confirmed Source Files:  {len(imp.get('confirmed_source_files', []))}",
            f"  Confirmed Test Files:    {len(imp.get('confirmed_test_files', []))}",
            f"  Likely Source Files:     {len(imp.get('likely_source_files', []))}",
            f"  Transitive Consumers:    {imp.get('transitive_consumers', 0)}",
            "",
            "REPAIR MISSION",
            f"  Mission ID: {mis.get('mission_id', 'N/A')}",
            f"  Title:      {mis.get('title', 'N/A')}",
            f"  Status:     {mis.get('status', 'N/A')}",
            "",
            "VERIFICATION",
            f"  Status:                 {ver.get('status', 'UNKNOWN')}",
            f"  Compatible Consumers:   {ver.get('compatible_consumers', 0)}",
            f"  Incompatible Consumers: {ver.get('incompatible_consumers', 0)}",
            f"  Breaking Findings:      {ver.get('breaking_findings', 0)}",
            f"  Next Step:              {ver.get('next_step', 'N/A')}",
            "=" * 80,
        ]
        return "\n".join(lines)


def generate_change_passport(
    workspace_root: str | Path,
    producer_filter: Optional[str] = None,
    test_status: str = "PASS",
) -> ChangePassport:
    """
    Deterministically compose a ChangePassport from workspace state.

    Reuses existing discovery, impact analysis, dependency graph,
    repair mission, SemVer, and verification logic without duplication.
    """
    ws = Path(workspace_root).resolve()
    if not ws.exists():
        raise FileNotFoundError(f"Workspace root not found: {ws}")
    if not ws.is_dir():
        raise NotADirectoryError(f"Not a directory: {ws}")

    # 1. Discover consumers and check compatibility
    report: DiscoveryReport = discover_and_check(ws, producer_filter=producer_filter)

    # 2. Repair mission (contains primary semantic change and affected consumers)
    mission: RepairMission = generate_repair_mission(ws, producer_filter=producer_filter)

    # 3. Dependency graph
    graph: DependencyGraph = build_dependency_graph(ws, producer_filter=producer_filter)

    # 4. Release verification
    verification_res: ReleaseVerification = evaluate_release_gate(
        report=report,
        producer_service=mission.producer,
        test_results={"status": test_status, "details": f"Automated tests: {test_status}"},
    )

    producer = mission.producer
    contract = mission.change.contract_path or ""
    ch = mission.change
    summary = report.blast_radius_summary

    change_dict = {
        "endpoint": ch.endpoint,
        "method": ch.method,
        "kind": ch.change_kind,
        "field": ch.field,
        "new_field": ch.new_value,
        "old_value": ch.old_value,
        "new_value": ch.new_value,
        "compatibility": ch.compatibility,
        "reason": ch.reason,
    }

    impact_dict = {
        "direct_consumers": summary.direct_consumers,
        "affected_consumers": summary.affected_consumers or len(summary.affected_services),
        "contract_only_consumers": summary.contract_only_consumers,
        "confirmed_source_files": list(summary.confirmed_source_files),
        "confirmed_test_files": list(summary.confirmed_test_files),
        "likely_source_files": list(summary.likely_source_files),
        "likely_test_files": list(summary.likely_test_files),
        "transitive_consumers": summary.transitive_consumers,
        "counts": summary.summary_metrics(),
    }

    bump = (mission.semver.get("bump") or mission.semver.get("recommendation") or "none").upper()
    release_dict = {
        "semver": bump,
        "recommendation": bump,
        "from": mission.semver.get("current_version", "1.0.0"),
        "to": mission.semver.get("recommended_version", "1.0.0"),
        "is_breaking": mission.semver.get("is_breaking", bump == "MAJOR"),
        "reason": mission.semver.get("reason", ""),
    }

    verification_dict = {
        "status": verification_res.status.value,
        "is_ready": verification_res.is_ready,
        "compatible_consumers": len(verification_res.compatible_consumers),
        "incompatible_consumers": len(verification_res.affected_consumers),
        "breaking_findings": verification_res.breaking_changes_count,
        "remaining_actions": list(verification_res.remaining_actions),
        "remaining_failures": list(verification_res.remaining_failures),
        "next_step": verification_res.next_step,
    }

    mission_dict = {
        "mission_id": mission.mission_id,
        "title": mission.title,
        "status": mission.status,
        "required_actions": list(mission.required_actions),
        "acceptance_criteria": list(mission.acceptance_criteria),
        "affected_consumers_count": len(mission.affected_consumers),
    }

    # Deterministic Passport ID
    raw_key = (
        f"{producer}:{ch.endpoint}:{ch.change_kind}:{ch.field}:{ch.new_value or ''}:"
        f"{verification_res.status.value}:{len(report.affected_consumers)}"
    )
    passport_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()[:8]
    passport_id = f"passport-{producer}-{passport_hash}"

    return ChangePassport(
        passport_id=passport_id,
        producer=producer,
        contract=contract,
        change=change_dict,
        impact=impact_dict,
        release=release_dict,
        verification=verification_dict,
        dependency_graph=graph.to_dict(),
        repair_mission=mission_dict,
        evidence_id=verification_res.mission_id or None,
    )
