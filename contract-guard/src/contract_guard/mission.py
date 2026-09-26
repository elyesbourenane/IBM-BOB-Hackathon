"""
Repair Mission module for ContractGuard Phase 3A.

Transforms deterministic contract compatibility and blast-radius results into
a structured, machine-readable REPAIR MISSION for IBM Bob:

    AI reasons. Deterministic checks decide. Bob executes. Deterministic verification proves.

Contains:
- SemanticChange: Focused representation of what changed in the producer API.
- AffectedConsumerMission: Consumer-specific blast radius and confirmed impact.
- RepairMission: Complete deterministic repair mission specification for Bob.
- generate_repair_mission: Generator integrating consumer discovery, comparator,
  blast radius, and SemVer recommendation.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .discovery import discover_and_check, DiscoveryReport
from .git import inspect_git_status
from .models import ChangeKind, Finding, Severity, _EXPLANATIONS
from .pr import _detect_producer_contract_changes, _extract_contract_version
from .versioning import calculate_semver_recommendation, SemVerRecommendation


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class SemanticChange:
    """Focused representation of a producer API contract change."""

    producer_service: str
    contract_path: str
    endpoint: str
    method: str
    change_kind: str
    field: str
    old_value: Optional[str]
    new_value: Optional[str]
    compatibility: str  # "breaking" | "compatible"
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "producer_service": self.producer_service,
            "contract_path": self.contract_path,
            "endpoint": self.endpoint,
            "method": self.method,
            "change_kind": self.change_kind,
            "field": self.field,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "compatibility": self.compatibility,
            "reason": self.reason,
        }


@dataclass
class AffectedConsumerMission:
    """Consumer impact summary within a repair mission."""

    service: str
    contract: str
    affected_endpoints: list[str] = field(default_factory=list)
    affected_fields: list[str] = field(default_factory=list)
    confirmed_source_files: list[str] = field(default_factory=list)
    confirmed_test_files: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "service": self.service,
            "contract": self.contract,
            "affected_endpoints": list(self.affected_endpoints),
            "affected_fields": list(self.affected_fields),
            "confirmed_source_files": list(self.confirmed_source_files),
            "confirmed_test_files": list(self.confirmed_test_files),
        }


@dataclass
class RepairMission:
    """
    Structured, machine-readable repair mission for IBM Bob.

    Describes what changed, which consumers are affected, which code/test files
    are confirmed impacted, what actions Bob must take, and the acceptance criteria.
    """

    mission_id: str
    title: str
    producer: str
    change: SemanticChange
    severity: str  # "breaking" | "compatible"
    semver: dict[str, Any]
    status: str    # "BLOCKED" | "READY"
    affected_consumers: list[AffectedConsumerMission]
    required_actions: list[str]
    acceptance_criteria: list[str]
    all_changes: list[SemanticChange] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "title": self.title,
            "producer": self.producer,
            "change": self.change.to_dict() if hasattr(self.change, "to_dict") else self.change,
            "severity": self.severity,
            "semver": dict(self.semver),
            "status": self.status,
            "affected_consumers": [
                c.to_dict() if hasattr(c, "to_dict") else c for c in self.affected_consumers
            ],
            "required_actions": list(self.required_actions),
            "acceptance_criteria": list(self.acceptance_criteria),
            "all_changes": [
                c.to_dict() if hasattr(c, "to_dict") else c for c in self.all_changes
            ],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    def to_markdown(self) -> str:
        semver_info = self.semver.get("recommended_version") or self.semver.get("bump", "").upper()
        semver_bump = self.semver.get("bump", "").upper()
        curr_ver = self.semver.get("current_version")
        rec_ver = self.semver.get("recommended_version")
        ver_str = f"`{curr_ver} -> {rec_ver}` ({semver_bump})" if curr_ver and rec_ver else f"**{semver_bump}**"

        lines = [
            f"# ContractGuard Repair Mission: `{self.mission_id}`",
            "",
            f"**Title:** {self.title}  ",
            f"**Status:** `{self.status}`  ",
            f"**Severity:** `{self.severity}`  ",
            f"**Producer Service:** `{self.producer}`  ",
            f"**SemVer Recommendation:** {ver_str}  ",
            "",
            "## Semantic Change",
            "",
            f"- **Endpoint:** `{self.change.endpoint}`",
            f"- **Method:** `{self.change.method}`",
            f"- **Change Kind:** `{self.change.change_kind}`",
            f"- **Field:** `{self.change.field}`",
            f"- **Old Value:** `{self.change.old_value}`",
            f"- **New Value:** `{self.change.new_value}`",
            f"- **Compatibility:** `{self.change.compatibility}`",
            f"- **Reason:** {self.change.reason}",
            "",
            f"## Affected Consumers ({len(self.affected_consumers)})",
            "",
        ]

        if not self.affected_consumers:
            lines.append("No consumers are affected. All discovered consumer contracts are compatible.")
            lines.append("")
        else:
            for c in self.affected_consumers:
                lines.append(f"### {c.service}")
                lines.append(f"- **Contract:** `{c.contract}`")
                lines.append(f"- **Affected Endpoints:** {', '.join(f'`{ep}`' for ep in c.affected_endpoints) or 'None'}")
                lines.append(f"- **Affected Fields:** {', '.join(f'`{fd}`' for fd in c.affected_fields) or 'None'}")
                if c.confirmed_source_files:
                    lines.append("- **Confirmed Source Files:**")
                    for sf in c.confirmed_source_files:
                        lines.append(f"  - `{sf}`")
                else:
                    lines.append("- **Confirmed Source Files:** None")

                if c.confirmed_test_files:
                    lines.append("- **Confirmed Test Files:**")
                    for tf in c.confirmed_test_files:
                        lines.append(f"  - `{tf}`")
                else:
                    lines.append("- **Confirmed Test Files:** None")
                lines.append("")

        lines.extend([
            "## Required Actions",
            "",
        ])
        for idx, act in enumerate(self.required_actions, 1):
            lines.append(f"{idx}. {act}")
        lines.append("")

        lines.extend([
            "## Acceptance Criteria",
            "",
        ])
        for crit in self.acceptance_criteria:
            lines.append(f"- [ ] {crit}")
        lines.append("")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Semantic Change Factory
# ---------------------------------------------------------------------------

def create_semantic_change(
    finding: Optional[Finding | dict[str, Any]] = None,
    *,
    producer_service: str = "",
    contract_path: str = "",
    endpoint: Optional[str] = None,
    method: Optional[str] = None,
    change_kind: Optional[str | ChangeKind] = None,
    field: Optional[str] = None,
    old_value: Optional[str] = None,
    new_value: Optional[str] = None,
    compatibility: Optional[str] = None,
    reason: Optional[str] = None,
) -> SemanticChange:
    """
    Construct a SemanticChange object, extracting values from a Finding or dict,
    and allowing explicit keyword overrides.
    """
    f_ep = ""
    f_kind = ""
    f_field = ""
    f_detail = ""
    f_sev = ""
    f_reason = ""
    f_prod = producer_service

    if isinstance(finding, Finding):
        f_ep = finding.endpoint
        f_kind = finding.change_kind.value if isinstance(finding.change_kind, ChangeKind) else str(finding.change_kind)
        f_field = finding.affected_field
        f_detail = finding.detail
        f_sev = finding.severity.value if isinstance(finding.severity, Severity) else str(finding.severity)
        f_reason = finding.reason
    elif isinstance(finding, dict):
        f_ep = finding.get("endpoint", "")
        f_kind = finding.get("change_kind", "")
        f_field = finding.get("affected_field", "")
        f_detail = finding.get("detail", "")
        f_sev = finding.get("severity", "")
        f_reason = finding.get("reason", "")
        if finding.get("producer_service"):
            f_prod = finding["producer_service"]

    # Resolution with overrides
    eff_ep = endpoint if endpoint is not None else f_ep
    eff_kind = (
        (change_kind.value if isinstance(change_kind, ChangeKind) else str(change_kind))
        if change_kind is not None
        else f_kind
    )
    eff_field = field if field is not None else f_field
    eff_prod = producer_service or f_prod

    eff_method = method
    if eff_method is None:
        eff_method = eff_ep.split()[0] if " " in eff_ep else ""

    eff_old = old_value
    eff_new = new_value

    if eff_old is None and eff_new is None:
        if eff_kind == "field_renamed":
            m = re.search(r"Consumer expects '([^']+)' but producer now uses '([^']+)'", f_detail)
            if m:
                eff_old = m.group(1)
                eff_new = m.group(2)
            else:
                eff_old = eff_field or None
        elif eff_kind == "field_type_changed":
            m = re.search(r"Producer type is '([^']+)', consumer expects '([^']+)'", f_detail)
            if m:
                eff_new = m.group(1)
                eff_old = m.group(2)
        elif eff_kind == "field_removed":
            eff_old = eff_field or None
        elif eff_kind == "endpoint_removed":
            eff_old = eff_ep or None
        elif eff_kind == "field_optional_added":
            eff_new = eff_field or None
        elif eff_kind == "field_required_added":
            eff_new = eff_field or None

    eff_compat = compatibility
    if eff_compat is None:
        if f_sev == "breaking" or eff_kind in (
            "field_renamed",
            "field_removed",
            "endpoint_removed",
            "field_type_changed",
            "field_required_added",
            "contract_error",
        ):
            eff_compat = "breaking"
        else:
            eff_compat = "compatible"

    eff_reason = reason if reason is not None else (f_reason or f_detail)

    return SemanticChange(
        producer_service=eff_prod,
        contract_path=contract_path,
        endpoint=eff_ep,
        method=eff_method,
        change_kind=eff_kind,
        field=eff_field,
        old_value=eff_old,
        new_value=eff_new,
        compatibility=eff_compat,
        reason=eff_reason,
    )


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------

def generate_repair_mission(
    workspace_root: str | Path,
    producer_filter: Optional[str] = None,
) -> RepairMission:
    """
    Generate a deterministic Repair Mission for the workspace.

    Discovers all consumers, runs deterministic contract compatibility checks,
    computes blast radius with confirmed source/test files, derives SemVer,
    and returns a structured RepairMission.
    """
    ws = Path(workspace_root).resolve()
    if not ws.exists():
        raise FileNotFoundError(f"Workspace root not found: {ws}")
    if not ws.is_dir():
        raise NotADirectoryError(f"Not a directory: {ws}")

    # 1. Discover consumers and run compatibility checks
    report: DiscoveryReport = discover_and_check(ws, producer_filter=producer_filter)

    # 2. Determine primary producer and contract
    producer = producer_filter or ""
    contract_path = ""
    current_version: Optional[str] = None

    if report.results:
        for r in report.results:
            if producer_filter and r.producer_service != producer_filter:
                continue
            if not producer:
                producer = r.producer_service
            if r.producer_contract and Path(r.producer_contract).exists():
                contract_path = r.producer_contract
                ver = _extract_contract_version(r.producer_contract)
                if ver:
                    current_version = ver
                    break

    if not producer:
        producer = "producer"

    # 3. Collect semantic changes
    git_status = inspect_git_status(ws)
    prod_findings, has_prod_changes = _detect_producer_contract_changes(
        ws=ws,
        git_status=git_status,
        base_ref=None,
        report=report,
        producer_filter=producer_filter,
    )

    semantic_changes: list[SemanticChange] = []
    seen_changes: set[tuple[str, str, str, Optional[str]]] = set()

    for f in prod_findings:
        sc = create_semantic_change(
            f,
            producer_service=producer,
            contract_path=contract_path,
        )
        key = (sc.endpoint, sc.change_kind, sc.field, sc.new_value)
        if key not in seen_changes:
            seen_changes.add(key)
            semantic_changes.append(sc)

    for f_dict in report.breaking_findings:
        sc = create_semantic_change(
            f_dict,
            producer_service=producer,
            contract_path=contract_path,
        )
        key = (sc.endpoint, sc.change_kind, sc.field, sc.new_value)
        if key not in seen_changes:
            seen_changes.add(key)
            semantic_changes.append(sc)

    if not semantic_changes and has_prod_changes:
        semantic_changes.append(
            SemanticChange(
                producer_service=producer,
                contract_path=contract_path,
                endpoint="",
                method="",
                change_kind="contract_modified",
                field="",
                old_value=None,
                new_value=None,
                compatibility="compatible",
                reason="API contract modified with no breaking or additive schema differences.",
            )
        )

    # Fallback if still empty: check compatible findings or default to none
    if not semantic_changes:
        all_findings: list[Finding] = []
        for r in report.results:
            all_findings.extend(r.findings)
        compat_findings = [f for f in all_findings if not f.is_breaking]
        if compat_findings:
            sc = create_semantic_change(
                compat_findings[0],
                producer_service=producer,
                contract_path=contract_path,
            )
            semantic_changes.append(sc)
        else:
            semantic_changes.append(
                SemanticChange(
                    producer_service=producer,
                    contract_path=contract_path,
                    endpoint="",
                    method="",
                    change_kind="none",
                    field="",
                    old_value=None,
                    new_value=None,
                    compatibility="compatible",
                    reason="No contract differences detected.",
                )
            )

    primary_change = semantic_changes[0]

    # 4. Build affected consumer mission entries (strictly using confirmed impact, never inventing files)
    affected_consumer_missions: list[AffectedConsumerMission] = []
    for c_name in report.affected_consumers:
        c_impacts = [imp for imp in report.impacts if imp.consumer_service == c_name]
        c_contract = ""
        endpoints: set[str] = set()
        fields: set[str] = set()
        conf_src: set[str] = set()
        conf_test: set[str] = set()

        for imp in c_impacts:
            if not c_contract and imp.contract_path:
                c_contract = imp.contract_path
            if imp.endpoint:
                endpoints.add(imp.endpoint)
            if imp.affected_field:
                fields.add(imp.affected_field)
            for sf in imp.confirmed_source_files:
                conf_src.add(sf)
            for tf in imp.confirmed_test_files:
                conf_test.add(tf)

        if not c_contract:
            for r in report.results:
                if r.consumer_service == c_name and r.consumer_contract:
                    try:
                        c_contract = str(Path(r.consumer_contract).relative_to(ws)).replace("\\", "/")
                    except ValueError:
                        c_contract = r.consumer_contract
                    break

        affected_consumer_missions.append(
            AffectedConsumerMission(
                service=c_name,
                contract=c_contract,
                affected_endpoints=sorted(endpoints),
                affected_fields=sorted(fields),
                confirmed_source_files=sorted(conf_src),
                confirmed_test_files=sorted(conf_test),
            )
        )

    # 5. SemVer calculation
    all_compat = len(report.consumers_checked) > 0 and len(report.affected_consumers) == 0
    if prod_findings or has_prod_changes:
        findings_for_semver = prod_findings
        has_changes = has_prod_changes
    else:
        findings_for_semver = report.breaking_findings if report.breaking_findings else [primary_change.to_dict()]
        has_changes = bool(git_status.changed_contracts or report.breaking_findings)

    semver_rec: SemVerRecommendation = calculate_semver_recommendation(
        findings=findings_for_semver,
        has_contract_changes=has_changes,
        current_version=current_version,
        all_consumers_compatible=all_compat,
    )

    # 6. Severity & Status
    is_breaking = any(c.compatibility == "breaking" for c in semantic_changes)
    has_incompatible = len(report.affected_consumers) > 0

    severity = "breaking" if is_breaking else "compatible"
    status = "BLOCKED" if has_incompatible else "READY"

    # 7. Required Actions
    if primary_change.change_kind == "field_renamed":
        required_actions = [
            "Update consumer contract",
            "Update affected DTO/model mapping if present",
            "Update source references if present",
            "Update affected tests if present",
            "Run consumer tests",
            "Re-run ContractGuard verification",
        ]
    elif primary_change.change_kind == "endpoint_removed":
        required_actions = [
            "Update consumer contract: remove decommissioned endpoint",
            "Update or reroute consumer client calls to endpoint",
            "Update affected tests if present",
            "Run consumer tests",
            "Re-run ContractGuard verification",
        ]
    elif primary_change.change_kind == "field_removed":
        required_actions = [
            "Update consumer contract: remove deprecated field reference",
            "Update consumer models and remove field usage",
            "Update affected tests if present",
            "Run consumer tests",
            "Re-run ContractGuard verification",
        ]
    elif primary_change.change_kind == "field_type_changed":
        required_actions = [
            "Update consumer contract: update field type definition",
            "Update affected DTO/model mapping if present",
            "Update source references to handle new type",
            "Update affected tests if present",
            "Run consumer tests",
            "Re-run ContractGuard verification",
        ]
    elif is_breaking:
        required_actions = [
            "Update consumer contract",
            "Update affected DTO/model mapping if present",
            "Update source references if present",
            "Update affected tests if present",
            "Run consumer tests",
            "Re-run ContractGuard verification",
        ]
    else:
        required_actions = [
            "Verify consumer contract compatibility",
            "Run consumer tests",
            "Re-run ContractGuard verification",
        ]

    # 8. Deterministic Acceptance Criteria
    acceptance_criteria = [
        "All discovered consumer contracts compatible",
        "No breaking findings remain",
        "Affected tests pass when available",
        "ContractGuard verification returns READY",
    ]

    # 9. Deterministic Mission ID (canonical hash, never random UUID)
    raw_key = f"{producer}:{primary_change.endpoint}:{primary_change.change_kind}:{primary_change.field}:{primary_change.new_value or ''}"
    mission_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()[:8]
    mission_id = f"mission-{producer}-{mission_hash}"

    # 10. Title
    if primary_change.change_kind == "field_renamed":
        title = f"Repair breaking field rename in {producer}: {primary_change.old_value} -> {primary_change.new_value}"
    elif primary_change.change_kind == "field_removed":
        title = f"Repair breaking field removal in {producer}: {primary_change.field}"
    elif primary_change.change_kind == "endpoint_removed":
        title = f"Repair breaking endpoint removal in {producer}: {primary_change.endpoint}"
    elif is_breaking:
        title = f"Repair breaking contract change in {producer}: {primary_change.endpoint} ({primary_change.change_kind})"
    else:
        title = f"Contract change review for {producer}: {primary_change.change_kind}"

    return RepairMission(
        mission_id=mission_id,
        title=title,
        producer=producer,
        change=primary_change,
        severity=severity,
        semver=semver_rec.to_dict(),
        status=status,
        affected_consumers=affected_consumer_missions,
        required_actions=required_actions,
        acceptance_criteria=acceptance_criteria,
        all_changes=semantic_changes,
    )


# ---------------------------------------------------------------------------
# CLI Text Formatter
# ---------------------------------------------------------------------------

def format_mission_text(mission: RepairMission, no_color: bool = False) -> str:
    """Format a repair mission for terminal display."""
    red = "" if no_color else "\033[31m"
    green = "" if no_color else "\033[32m"
    bold = "" if no_color else "\033[1m"
    cyan = "" if no_color else "\033[36m"
    reset = "" if no_color else "\033[0m"

    status_color = green if mission.status == "READY" else red

    sem = mission.semver
    if sem.get("current_version") and sem.get("recommended_version"):
        semver_line = f"{sem['current_version']} -> {bold}{sem['recommended_version']}{reset} ({sem.get('bump', '').upper()})"
    else:
        semver_line = f"{bold}{sem.get('bump', '').upper()}{reset}"

    lines = [
        f"{bold}{'=' * 80}{reset}",
        f"{bold}CONTRACTGUARD REPAIR MISSION: {cyan}{mission.mission_id}{reset}",
        f"{bold}{'=' * 80}{reset}",
        f"Title:       {bold}{mission.title}{reset}",
        f"Producer:    {mission.producer}",
        f"Severity:    {red if mission.severity == 'breaking' else green}{mission.severity}{reset}",
        f"Status:      {status_color}{bold}{mission.status}{reset}",
        f"SemVer:      {semver_line}",
        "",
        f"{bold}Semantic Change:{reset}",
        f"  Endpoint:      {mission.change.endpoint}",
        f"  Method:        {mission.change.method}",
        f"  Change Kind:   {mission.change.change_kind}",
        f"  Field:         {mission.change.field}",
        f"  Old Value:     {mission.change.old_value}",
        f"  New Value:     {mission.change.new_value}",
        f"  Compatibility: {mission.change.compatibility}",
        f"  Reason:        {mission.change.reason}",
        "",
        f"{bold}Affected Consumers ({len(mission.affected_consumers)}):{reset}",
    ]

    if not mission.affected_consumers:
        lines.append("  [OK] None (All discovered consumers compatible)")
    else:
        for c in mission.affected_consumers:
            lines.append(f"  {red}[X]{reset} {bold}{c.service}{reset}")
            lines.append(f"      Contract:   {c.contract}")
            lines.append(f"      Endpoints:  {', '.join(c.affected_endpoints) or 'None'}")
            lines.append(f"      Fields:     {', '.join(c.affected_fields) or 'None'}")
            src_str = ", ".join(c.confirmed_source_files) if c.confirmed_source_files else "None"
            test_str = ", ".join(c.confirmed_test_files) if c.confirmed_test_files else "None"
            lines.append(f"      Source:     {src_str}")
            lines.append(f"      Tests:      {test_str}")

    lines.extend([
        "",
        f"{bold}Required Actions:{reset}",
    ])
    for idx, act in enumerate(mission.required_actions, 1):
        lines.append(f"  {idx}. {act}")

    lines.extend([
        "",
        f"{bold}Acceptance Criteria:{reset}",
    ])
    for crit in mission.acceptance_criteria:
        lines.append(f"  [ ] {crit}")
    lines.append("")

    return "\n".join(lines)
