"""
What-if / Pre-change Simulation module for ContractGuard Phase 3D.

Allows simulating hypothetical API contract changes in memory WITHOUT mutating:
- producer contracts
- consumer contracts
- source files
- test files
- Git repository state

Reuses the existing deterministic comparison engine (Comparator._compare_docs),
blast-radius scanner, SemVer calculator, and dependency graph.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .comparator import Comparator
from .config import load_config, ContractGuardConfig
from .discovery import _find_config_files, ConsumerResult, DiscoveryReport
from .extractor import iter_endpoints
from .graph import build_dependency_graph, DependencyGraph
from .impact import (
    BlastRadiusSummary,
    ConsumerImpact,
    scan_consumer_impact,
    summarize_blast_radius,
)
from .loader import load_contract
from .models import ChangeKind, ComparisonReport, Finding, Severity
from .versioning import calculate_semver_recommendation, SemVerRecommendation


VALID_CHANGE_KINDS = {
    "field_renamed",
    "field_removed",
    "endpoint_removed",
    "field_optional_added",
    "field_required_added",
}


@dataclass
class WhatIfResult:
    """Outcome of an in-memory pre-change contract simulation."""

    is_simulated: bool
    producer: str
    proposed_change: dict[str, Any]
    classification: str  # "BREAKING" | "COMPATIBLE"
    status: str          # "BLOCKED" | "READY"
    direct_consumers: int
    affected_consumers: list[str]
    compatible_consumers: list[str]
    contract_only_consumers: int
    confirmed_source_files: list[str]
    confirmed_test_files: list[str]
    likely_source_files: list[str]
    likely_test_files: list[str]
    transitive_consumers: int
    semver_bump: str
    current_version: str
    recommended_version: str
    required_actions: list[str]
    acceptance_criteria: list[str]
    breaking_findings: list[dict[str, Any]] = field(default_factory=list)

    @property
    def simulated(self) -> bool:
        return self.is_simulated

    @property
    def compatibility(self) -> str:
        return self.classification.lower()

    @property
    def release_status(self) -> str:
        return self.status

    @property
    def semver(self) -> dict[str, Any]:
        return {
            "recommendation": self.semver_bump,
            "current_version": self.current_version,
            "recommended_version": self.recommended_version,
        }

    @property
    def findings(self) -> list[dict[str, Any]]:
        return self.breaking_findings

    def format_markdown(self) -> str:
        return self.to_markdown()

    def format_text(self, no_color: bool = False) -> str:
        return self.render_text()

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_simulated": True,
            "simulated": True,
            "simulation_note": "SIMULATED / NOT APPLIED - No files or git state modified",
            "producer": self.producer,
            "proposed_change": self.proposed_change,
            "classification": self.classification,
            "compatibility": self.compatibility,
            "status": self.status,
            "release_status": self.release_status,
            "direct_consumers": self.direct_consumers,
            "affected_consumers": len(self.affected_consumers),
            "semver": self.semver,
            "blast_radius": {
                "direct_consumers": self.direct_consumers,
                "affected_consumers": len(self.affected_consumers),
                "contract_only_consumers": self.contract_only_consumers,
                "confirmed_source_files": len(self.confirmed_source_files),
                "confirmed_test_files": len(self.confirmed_test_files),
                "likely_source_files": len(self.likely_source_files),
                "likely_test_files": len(self.likely_test_files),
                "transitive_consumers": self.transitive_consumers,
                "confirmed_source_list": list(self.confirmed_source_files),
                "confirmed_test_list": list(self.confirmed_test_files),
                "likely_source_list": list(self.likely_source_files),
                "affected_consumers_list": list(self.affected_consumers),
                "compatible_consumers_list": list(self.compatible_consumers),
            },
            "release": {
                "semver": self.semver_bump,
                "from": self.current_version,
                "to": self.recommended_version,
            },
            "required_actions": list(self.required_actions),
            "acceptance_criteria": list(self.acceptance_criteria),
            "breaking_findings": list(self.breaking_findings),
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    def to_markdown(self) -> str:
        ch = self.proposed_change
        change_desc = (
            f"`{ch.get('field', '')}` -> `{ch.get('new_field', '')}`"
            if ch.get("new_field")
            else f"`{ch.get('field', ch.get('endpoint', 'N/A'))}`"
        )

        lines = [
            "# CONTRACTGUARD WHAT-IF SIMULATION",
            "",
            "> **NOTICE:** SIMULATED / NOT APPLIED — Workspace and contracts were not modified.",
            "",
            f"**Producer:** `{self.producer}`  ",
            f"**Proposed Change:** {change_desc} (`{ch.get('change_kind', 'N/A')}`)  ",
            f"**Endpoint:** `{ch.get('endpoint', 'N/A')}`  ",
            f"**Classification:** **{self.classification}**  ",
            f"**Predicted Release Status:** **{self.status}**  ",
            f"**SemVer Impact:** `{self.current_version} -> {self.recommended_version}` ({self.semver_bump})  ",
            "",
            "## Blast Radius Breakdown",
            "| Metric | Simulated Count |",
            "|---|---|",
            f"| Direct Consumers | {self.direct_consumers} |",
            f"| Affected Consumers | {len(self.affected_consumers)} |",
            f"| Contract-Only Consumers | {self.contract_only_consumers} |",
            f"| Confirmed Source Files | {len(self.confirmed_source_files)} |",
            f"| Confirmed Test Files | {len(self.confirmed_test_files)} |",
            f"| Likely Source Files | {len(self.likely_source_files)} |",
            f"| Transitive Consumers | {self.transitive_consumers} |",
            "",
        ]

        if self.confirmed_source_files:
            lines.append("### Confirmed Source Files")
            for f in self.confirmed_source_files:
                lines.append(f"- `{f}`")
            lines.append("")

        if self.confirmed_test_files:
            lines.append("### Confirmed Test Files")
            for f in self.confirmed_test_files:
                lines.append(f"- `{f}`")
            lines.append("")

        lines.append("## Required Actions if Applied")
        for act in self.required_actions:
            lines.append(f"1. {act}")
        lines.append("")

        return "\n".join(lines)

    def render_text(self) -> str:
        ch = self.proposed_change
        change_desc = (
            f"{ch.get('field', '')} -> {ch.get('new_field', '')}"
            if ch.get("new_field")
            else f"{ch.get('field', ch.get('endpoint', 'N/A'))}"
        )

        lines = [
            "=" * 70,
            "CONTRACTGUARD WHAT-IF SIMULATION [SIMULATED / NOT APPLIED]",
            "=" * 70,
            f"Producer:       {self.producer}",
            f"Proposed:       {change_desc}",
            f"Endpoint:       {ch.get('endpoint', 'N/A')}",
            f"Change Kind:    {ch.get('change_kind', 'N/A')}",
            f"Classification: {self.classification}",
            f"Release Status: {self.status}",
            f"SemVer Impact:  {self.current_version} -> {self.recommended_version} ({self.semver_bump})",
            "",
            "BLAST RADIUS (PREDICTED)",
            f"  Direct Consumers:        {self.direct_consumers}",
            f"  Affected Consumers:      {len(self.affected_consumers)}",
            f"  Contract-Only Consumers: {self.contract_only_consumers}",
            f"  Confirmed Source Files:  {len(self.confirmed_source_files)}",
            f"  Confirmed Test Files:    {len(self.confirmed_test_files)}",
            f"  Likely Source Files:     {len(self.likely_source_files)}",
            f"  Transitive Consumers:    {self.transitive_consumers}",
            "",
            "REQUIRED REPAIRS IF APPLIED",
        ]
        for act in self.required_actions:
            lines.append(f"  - {act}")
        lines.append("=" * 70)
        return "\n".join(lines)


def _apply_in_memory_change(
    doc: dict[str, Any],
    endpoint: str,
    change_kind: str,
    field: Optional[str] = None,
    new_field: Optional[str] = None,
) -> None:
    """Mutate an in-memory OpenAPI dictionary without writing to disk."""
    method_part = ""
    path_part = endpoint.strip()
    if " " in endpoint:
        method_part, path_part = endpoint.split(None, 1)
        method_part = method_part.lower()

    paths = doc.get("paths", {})
    if not isinstance(paths, dict):
        return

    # Handle endpoint removal
    if change_kind == "endpoint_removed":
        if path_part in paths:
            if method_part and method_part in paths[path_part]:
                del paths[path_part][method_part]
                if not paths[path_part]:
                    del paths[path_part]
            elif not method_part:
                del paths[path_part]
        return

    # Match path
    target_path = None
    for p in paths:
        if p == path_part or p.rstrip("/") == path_part.rstrip("/"):
            target_path = p
            break

    if not target_path:
        return

    path_item = paths[target_path]
    if not isinstance(path_item, dict):
        return

    # Match operations
    methods_to_modify = [method_part] if method_part and method_part in path_item else [
        m for m in ("get", "post", "put", "delete", "patch") if m in path_item
    ]

    for m in methods_to_modify:
        op = path_item[m]
        if not isinstance(op, dict):
            continue

        # Look in responses
        responses = op.get("responses", {})
        schemas_to_visit = []
        for r_code, resp in responses.items():
            if isinstance(resp, dict):
                content = resp.get("content", {})
                for media, media_obj in content.items():
                    if isinstance(media_obj, dict) and "schema" in media_obj:
                        schemas_to_visit.append(media_obj["schema"])

        # Look in requestBody
        req_body = op.get("requestBody", {})
        if isinstance(req_body, dict):
            content = req_body.get("content", {})
            for media, media_obj in content.items():
                if isinstance(media_obj, dict) and "schema" in media_obj:
                    schemas_to_visit.append(media_obj["schema"])

        # Apply field changes to discovered schemas
        for s in schemas_to_visit:
            _modify_schema(doc, s, change_kind, field, new_field)


def _resolve_schema_ref(
    doc: dict[str, Any],
    schema: dict[str, Any],
) -> dict[str, Any]:
    """Resolve a local OpenAPI $ref to the actual schema in memory."""
    if not isinstance(schema, dict):
        return schema

    ref = schema.get("$ref")
    if not isinstance(ref, str):
        return schema

    prefix = "#/components/schemas/"
    if not ref.startswith(prefix):
        return schema

    schema_name = ref[len(prefix):]
    components = doc.get("components", {})
    schemas = components.get("schemas", {}) if isinstance(components, dict) else {}

    resolved = schemas.get(schema_name)
    return resolved if isinstance(resolved, dict) else schema


def _modify_schema(
    doc: dict[str, Any],
    schema: dict[str, Any],
    change_kind: str,
    field: Optional[str],
    new_field: Optional[str],
) -> None:
    """Apply an in-memory change to a resolved OpenAPI schema."""
    if not isinstance(schema, dict):
        return

    schema = _resolve_schema_ref(doc, schema)

    props = schema.get("properties", {})
    if not isinstance(props, dict):
        props = {}
        schema["properties"] = props

    reqs = schema.get("required", [])
    req_set = list(reqs) if isinstance(reqs, list) else []

    if change_kind == "field_renamed" and field and new_field:
        if field in props:
            props[new_field] = props.pop(field)

        if field in req_set:
            schema["required"] = [
                new_field if r == field else r
                for r in req_set
            ]

    elif change_kind == "field_removed" and field:
        if field in props:
            del props[field]

        if field in req_set:
            schema["required"] = [
                r for r in req_set if r != field
            ]

    elif change_kind == "field_optional_added":
        fname = new_field or field
        if fname:
            props[fname] = {"type": "string"}

    elif change_kind == "field_required_added":
        fname = new_field or field
        if fname:
            props[fname] = {"type": "string"}

            if fname not in req_set:
                req_set.append(fname)
                schema["required"] = req_set


def simulate_what_if(
    workspace_root: str | Path,
    producer_service: Optional[str] = None,
    endpoint: str = "",
    change_kind: str = "field_renamed",
    field: Optional[str] = None,
    new_field: Optional[str] = None,
    old_value: Optional[str] = None,
    new_value: Optional[str] = None,
    producer: Optional[str] = None,
    method: Optional[str] = None,
    current_version: Optional[str] = None,
    **kwargs: Any,
) -> WhatIfResult:
    """
    Simulate a proposed contract change in memory WITHOUT mutating files or Git.

    Returns deterministic WhatIfResult containing predicted classification,
    affected consumers, blast radius, SemVer, and required actions.
    """
    ws = Path(workspace_root).resolve()
    if not ws.exists():
        raise FileNotFoundError(f"Workspace root not found: {ws}")

    producer_service = producer_service or producer or "payment-service"
    new_field = new_field or new_value
    if change_kind == "field_added":
        change_kind = "field_optional_added"

    if change_kind not in VALID_CHANGE_KINDS:
        raise ValueError(
            f"Unsupported change_kind '{change_kind}'. Supported: {', '.join(sorted(VALID_CHANGE_KINDS))}"
        )

    if change_kind == "field_renamed" and (not field or not new_field):
        raise ValueError("field_renamed requires both --field and --new-field")

    if change_kind in ("field_removed", "field_optional_added", "field_required_added") and not field and not new_field:
        raise ValueError(f"{change_kind} requires --field or --new-field")

    # 1. Discover all configs in workspace
    config_paths = _find_config_files(ws)
    producer_contract_path: Optional[Path] = None
    current_version = "1.0.0"

    # Find consumer dependencies matching producer_service
    matching_deps: list[tuple[ContractGuardConfig, Any]] = []
    for cp in config_paths:
        try:
            cfg = load_config(cp)
        except Exception:
            continue
        for dep in cfg.dependencies:
            if dep.service == producer_service:
                matching_deps.append((cfg, dep))
                if not producer_contract_path and dep.producer_contract.exists():
                    producer_contract_path = dep.producer_contract

    # Fallback to search inside producer directory if not found in consumer configs
    if not producer_contract_path:
        prod_candidates = [
            ws / producer_service / "docs" / "openapi.yaml",
            ws / producer_service / "docs" / "openapi.yml",
            ws / producer_service / "openapi.yaml",
            ws / producer_service / "openapi.yml",
        ]
        for c in prod_candidates:
            if c.exists():
                producer_contract_path = c
                break

    if not producer_contract_path or not producer_contract_path.exists():
        raise FileNotFoundError(
            f"Producer contract for service '{producer_service}' not found under {ws}"
        )

    # 2. Load original producer contract document into memory
    orig_producer_doc = load_contract(producer_contract_path)
    if isinstance(orig_producer_doc.get("info"), dict) and "version" in orig_producer_doc["info"]:
        current_version = str(orig_producer_doc["info"]["version"])

    # 3. Deep-copy and apply hypothetical change IN MEMORY
    sim_producer_doc = copy.deepcopy(orig_producer_doc)
    _apply_in_memory_change(
        sim_producer_doc,
        endpoint=endpoint,
        change_kind=change_kind,
        field=field,
        new_field=new_field,
    )

    # 4. Compare simulated producer doc against each consumer contract in memory
    comparator_engine = Comparator(producer_contract_path, producer_contract_path)
    all_findings: list[Finding] = []
    affected_consumers: list[str] = []
    compatible_consumers: list[str] = []
    consumer_impacts: list[ConsumerImpact] = []

    scan_token = field or new_field or ""

    for cfg, dep in matching_deps:
        if not dep.consumer_contract.exists():
            continue
        consumer_doc = load_contract(dep.consumer_contract)
        # In-memory comparison
        report: ComparisonReport = comparator_engine._compare_docs(sim_producer_doc, consumer_doc)
        breaking = [f for f in report.findings if f.is_breaking]

        if breaking:
            affected_consumers.append(cfg.service)
            for bf in breaking:
                all_findings.append(bf)
                # In-memory blast-radius file inspection
                fake_finding = Finding(
                    endpoint=bf.endpoint or endpoint,
                    affected_field=scan_token,
                    change_kind=bf.change_kind,
                    detail=bf.detail,
                )
                imp = scan_consumer_impact(
                    consumer_dir=cfg.base_dir,
                    consumer_service=cfg.service,
                    producer_service=producer_service,
                    consumer_contract=dep.consumer_contract,
                    producer_contract=producer_contract_path,
                    finding=fake_finding,
                )
                consumer_impacts.append(imp)
        else:
            compatible_consumers.append(cfg.service)

    # 5. Summarize blast radius
    direct_count = len(matching_deps)
    blast_summary = summarize_blast_radius(
        consumer_impacts,
        direct_consumers=direct_count,
        transitive_consumers=0,
    )

    # 6. SemVer calculation
    is_breaking = len(affected_consumers) > 0 or any(f.is_breaking for f in all_findings)
    # Deduplicate findings across consumers to produce canonical breaking findings
    unique_findings_dicts: list[dict[str, Any]] = []
    seen_finding_keys: set[tuple[str, str, str]] = set()
    renamed_keys: set[tuple[str, str]] = set()

    for f in all_findings:
        ck = f.change_kind.value if hasattr(f.change_kind, "value") else str(f.change_kind)
        if ck == "field_renamed":
            renamed_keys.add((f.endpoint, f.affected_field or scan_token))

    for f in all_findings:
        ck = f.change_kind.value if hasattr(f.change_kind, "value") else str(f.change_kind)
        af = f.affected_field or scan_token
        ep = f.endpoint
        # Suppress redundant field_removed if already identified as field_renamed
        if ck == "field_removed" and (ep, af) in renamed_keys:
            continue
        key = (ep, af, ck)
        if key not in seen_finding_keys:
            seen_finding_keys.add(key)
            unique_findings_dicts.append({
                "endpoint": ep,
                "affected_field": af,
                "change_kind": ck,
                "severity": f.severity.value if hasattr(f.severity, "value") else str(f.severity),
                "detail": f.detail,
                "reason": f.reason,
            })
    findings_dicts = unique_findings_dicts

    # If no consumer contract was broken (e.g. producer-only change), determine intrinsic change severity
    if not findings_dicts and change_kind in ("field_renamed", "field_removed", "endpoint_removed", "field_required_added"):
        findings_dicts = [{
            "endpoint": endpoint,
            "affected_field": scan_token,
            "change_kind": change_kind,
            "severity": "breaking",
            "detail": f"Simulated {change_kind}",
            "reason": "Breaking contract modification",
        }]
        is_breaking = True
    elif not findings_dicts and change_kind == "field_optional_added":
        findings_dicts = [{
            "endpoint": endpoint,
            "affected_field": scan_token,
            "change_kind": "field_optional_added",
            "severity": "compatible",
            "detail": "Simulated field_optional_added",
            "reason": "Backward-compatible additive change",
        }]

    semver_rec: SemVerRecommendation = calculate_semver_recommendation(
        findings=findings_dicts,
        has_contract_changes=True,
        current_version=current_version,
        all_consumers_compatible=(len(affected_consumers) == 0),
    )

    # 7. Required Actions
    if change_kind == "field_renamed":
        required_actions = [
            f"Update consumer contract: rename '{field}' to '{new_field}'",
            "Update affected consumer DTO/model mapping if present",
            "Update source references if present",
            "Update affected tests if present",
            "Run consumer tests",
            "Verify with ContractGuard before releasing",
        ]
    elif change_kind == "field_removed":
        required_actions = [
            f"Update consumer contract: remove reference to '{field}'",
            "Update consumer models and remove field usage",
            "Update affected tests if present",
            "Run consumer tests",
            "Verify with ContractGuard before releasing",
        ]
    elif change_kind == "endpoint_removed":
        required_actions = [
            f"Update consumer contract: remove endpoint '{endpoint}'",
            "Reroute consumer client calls to new endpoint",
            "Update affected tests",
            "Verify with ContractGuard before releasing",
        ]
    elif is_breaking:
        required_actions = [
            "Update consumer contracts to match new producer schema",
            "Update affected consumer source code and tests",
            "Verify with ContractGuard before releasing",
        ]
    else:
        required_actions = [
            "Verify consumer contracts continue to parse successfully",
            "Run consumer regression tests",
        ]

    acceptance_criteria = [
        "All discovered consumer contracts compatible",
        "No breaking findings remain",
        "Affected tests pass when available",
        "ContractGuard verification returns READY",
    ]

    classification = "BREAKING" if is_breaking else "COMPATIBLE"
    status = "BLOCKED" if is_breaking else "READY"

    proposed_dict = {
        "producer": producer_service,
        "endpoint": endpoint,
        "change_kind": change_kind,
        "field": field or "",
        "new_field": new_field or "",
        "old_value": old_value or field,
        "new_value": new_value or new_field,
    }

    return WhatIfResult(
        is_simulated=True,
        producer=producer_service,
        proposed_change=proposed_dict,
        classification=classification,
        status=status,
        direct_consumers=direct_count,
        affected_consumers=sorted(affected_consumers),
        compatible_consumers=sorted(compatible_consumers),
        contract_only_consumers=blast_summary.contract_only_consumers,
        confirmed_source_files=blast_summary.confirmed_source_files,
        confirmed_test_files=blast_summary.confirmed_test_files,
        likely_source_files=blast_summary.likely_source_files,
        likely_test_files=blast_summary.likely_test_files,
        transitive_consumers=0,
        semver_bump=semver_rec.bump.upper(),
        current_version=current_version,
        recommended_version=semver_rec.recommended_version,
        required_actions=required_actions,
        acceptance_criteria=acceptance_criteria,
        breaking_findings=findings_dicts,
    )
