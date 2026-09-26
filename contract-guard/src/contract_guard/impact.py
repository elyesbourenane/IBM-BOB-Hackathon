"""
Blast-radius and impact analysis module.

Provides deterministic inspection of affected consumer repositories to identify
which source and test files are affected by breaking contract changes.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .models import Finding, Severity, ChangeKind


SKIP_DIRS = {
    ".git",
    ".idea",
    ".bob",
    "target",
    "build",
    "dist",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".venv",
    "venv",
    "contracts",
}

VALID_EXTENSIONS = {
    ".java",
    ".py",
    ".ts",
    ".js",
    ".kt",
    ".go",
    ".cs",
    ".json",
    ".xml",
    ".properties",
    ".yaml",
    ".yml",
}


@dataclass
class BlastRadiusSummary:
    """High-level aggregated blast radius across all affected consumers."""

    affected_services: list[str] = field(default_factory=list)
    affected_contracts: list[str] = field(default_factory=list)
    affected_endpoints: list[str] = field(default_factory=list)
    affected_fields: list[str] = field(default_factory=list)
    confirmed_source_files: list[str] = field(default_factory=list)
    confirmed_test_files: list[str] = field(default_factory=list)
    likely_source_files: list[str] = field(default_factory=list)
    likely_test_files: list[str] = field(default_factory=list)
    direct_consumers: int = 0
    affected_consumers: int = 0
    contract_only_consumers: int = 0
    transitive_consumers: int = 0

    def to_dict(self) -> dict[str, Any]:
        aff_count = self.affected_consumers if self.affected_consumers else len(self.affected_services)
        return {
            "affected_services": list(self.affected_services),
            "affected_contracts": list(self.affected_contracts),
            "affected_endpoints": list(self.affected_endpoints),
            "affected_fields": list(self.affected_fields),
            "confirmed_source_files": list(self.confirmed_source_files),
            "confirmed_test_files": list(self.confirmed_test_files),
            "likely_source_files": list(self.likely_source_files),
            "likely_test_files": list(self.likely_test_files),
            "direct_consumers": self.direct_consumers,
            "affected_consumers": aff_count,
            "contract_only_consumers": self.contract_only_consumers,
            "transitive_consumers": self.transitive_consumers,
            "metrics": {
                "direct_consumers": self.direct_consumers,
                "affected_consumers": aff_count,
                "contract_only_consumers": self.contract_only_consumers,
                "confirmed_source_files": len(self.confirmed_source_files),
                "confirmed_test_files": len(self.confirmed_test_files),
                "likely_source_files": len(self.likely_source_files),
                "likely_test_files": len(self.likely_test_files),
                "transitive_consumers": self.transitive_consumers,
            },
        }

    def summary_metrics(self) -> dict[str, int]:
        """Return integer counts of all blast radius dimensions."""
        aff_count = self.affected_consumers if self.affected_consumers else len(self.affected_services)
        return {
            "direct_consumers": self.direct_consumers,
            "affected_consumers": aff_count,
            "contract_only_consumers": self.contract_only_consumers,
            "confirmed_source_files": len(self.confirmed_source_files),
            "confirmed_test_files": len(self.confirmed_test_files),
            "likely_source_files": len(self.likely_source_files),
            "likely_test_files": len(self.likely_test_files),
            "transitive_consumers": self.transitive_consumers,
        }


@dataclass
class ConsumerImpact:
    """Deterministic blast-radius detail for a single breaking finding in a consumer."""

    consumer_service: str
    producer_service: str
    endpoint: str
    affected_field: str
    change_kind: str
    severity: str
    producer_contract: str
    consumer_contract: str
    contract_path: str
    detail: str
    reason: str
    consumer_root: str = ""
    source_path: str | None = None
    test_path: str | None = None
    confirmed_source_files: list[str] = field(default_factory=list)
    confirmed_test_files: list[str] = field(default_factory=list)
    likely_source_files: list[str] = field(default_factory=list)
    likely_test_files: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "consumer_service": self.consumer_service,
            "producer_service": self.producer_service,
            "consumer_root": self.consumer_root,
            "endpoint": self.endpoint,
            "affected_field": self.affected_field,
            "change_kind": self.change_kind,
            "severity": self.severity,
            "producer_contract": self.producer_contract,
            "consumer_contract": self.consumer_contract,
            "contract_path": self.contract_path,
            "source_path": self.source_path,
            "test_path": self.test_path,
            "confirmed_source_files": list(self.confirmed_source_files),
            "confirmed_test_files": list(self.confirmed_test_files),
            "likely_source_files": list(self.likely_source_files),
            "likely_test_files": list(self.likely_test_files),
            "detail": self.detail,
            "reason": self.reason,
        }


def summarize_blast_radius(
    impacts: list[ConsumerImpact],
    direct_consumers: int = 0,
    transitive_consumers: int = 0,
) -> BlastRadiusSummary:
    """Aggregate individual consumer impacts into a single deduplicated blast-radius summary."""
    services: list[str] = []
    contracts: list[str] = []
    endpoints: list[str] = []
    fields: list[str] = []
    conf_src: list[str] = []
    conf_test: list[str] = []
    likely_src: list[str] = []
    likely_test: list[str] = []

    for imp in impacts:
        if imp.consumer_service and imp.consumer_service not in services:
            services.append(imp.consumer_service)
        if imp.contract_path and imp.contract_path not in contracts:
            contracts.append(imp.contract_path)
        if imp.endpoint and imp.endpoint not in endpoints:
            endpoints.append(imp.endpoint)
        if imp.affected_field and imp.affected_field not in fields:
            fields.append(imp.affected_field)
        for f in imp.confirmed_source_files:
            if f not in conf_src:
                conf_src.append(f)
        for f in imp.confirmed_test_files:
            if f not in conf_test:
                conf_test.append(f)
        for f in imp.likely_source_files:
            if f not in likely_src and f not in conf_src:
                likely_src.append(f)
        for f in imp.likely_test_files:
            if f not in likely_test and f not in conf_test:
                likely_test.append(f)

    # Sort all lists deterministically
    services.sort()
    contracts.sort()
    endpoints.sort()
    fields.sort()
    conf_src.sort()
    conf_test.sort()
    likely_src.sort()
    likely_test.sort()

    # Calculate contract-only consumers: affected consumers with 0 confirmed files
    contract_only_count = 0
    for svc in services:
        svc_conf_src = [f for imp in impacts if imp.consumer_service == svc for f in imp.confirmed_source_files]
        svc_conf_test = [f for imp in impacts if imp.consumer_service == svc for f in imp.confirmed_test_files]
        if not svc_conf_src and not svc_conf_test:
            contract_only_count += 1

    eff_direct = direct_consumers if direct_consumers > 0 else len(services)

    return BlastRadiusSummary(
        affected_services=services,
        affected_contracts=contracts,
        affected_endpoints=endpoints,
        affected_fields=fields,
        confirmed_source_files=conf_src,
        confirmed_test_files=conf_test,
        likely_source_files=likely_src,
        likely_test_files=likely_test,
        direct_consumers=eff_direct,
        affected_consumers=len(services),
        contract_only_consumers=contract_only_count,
        transitive_consumers=transitive_consumers,
    )


def _extract_field_tokens(affected_field: str) -> list[str]:
    """
    Derive search tokens for a given affected field path.

    Includes:
    - Raw field name and capitalized variant (e.g. paymentAmount, PaymentAmount)
    - Getter / setter methods (getPaymentAmount, setPaymentAmount, isPaymentAmount)
    - Snake case equivalents (payment_amount, get_payment_amount, set_payment_amount)
    - JSON / serialization annotations (@JsonProperty("paymentAmount"), @SerializedName("paymentAmount"))
    - Quoted JSON fixture / dictionary keys ("paymentAmount", "payment_amount")
    """
    leaf = affected_field.split(".")[-1]
    if not leaf:
        return []

    tokens: set[str] = {leaf}
    if len(leaf) > 1:
        cap = leaf[0].upper() + leaf[1:]
        tokens.add(cap)

        # Explicit getters / setters
        tokens.add(f"get{cap}")
        tokens.add(f"set{cap}")
        tokens.add(f"is{cap}")

        # snake_case conversion: paymentAmount -> payment_amount
        snake = re.sub(r"(?<!^)(?=[A-Z])", "_", leaf).lower()
        tokens.add(snake)
        tokens.add(f"get_{snake}")
        tokens.add(f"set_{snake}")

        # camelCase conversion: payment_amount -> paymentAmount
        if "_" in leaf:
            parts = leaf.split("_")
            camel = parts[0] + "".join(p.capitalize() for p in parts[1:])
            tokens.add(camel)
            camel_cap = parts[0].capitalize() + "".join(p.capitalize() for p in parts[1:])
            tokens.add(f"get{camel_cap}")
            tokens.add(f"set{camel_cap}")

        # Annotations (Jackson @JsonProperty, Gson @SerializedName)
        tokens.add(f'@JsonProperty("{leaf}")')
        tokens.add(f"@JsonProperty('{leaf}')")
        tokens.add(f'@SerializedName("{leaf}")')
        tokens.add(f"@SerializedName('{leaf}')")
        if snake != leaf:
            tokens.add(f'@JsonProperty("{snake}")')
            tokens.add(f"@JsonProperty('{snake}')")
            tokens.add(f'@SerializedName("{snake}")')
            tokens.add(f"@SerializedName('{snake}')")

        # JSON fixtures / quoted strings
        tokens.add(f'"{leaf}"')
        tokens.add(f"'{leaf}'")
        if snake != leaf:
            tokens.add(f'"{snake}"')
            tokens.add(f"'{snake}'")

    return sorted(tokens)


def _extract_likely_tokens(endpoint: str, finding: Finding) -> list[str]:
    """Derive tokens that suggest a file is in the call path of the endpoint."""
    tokens: set[str] = set()
    # Path tokens: e.g. /api/payments/{id} -> payments
    parts = [p.strip("{}") for p in endpoint.split()[-1].split("/") if p and not p.startswith("{")]
    for p in parts:
        if len(p) > 2 and p.lower() not in {"api", "v1", "v2", "v3"}:
            tokens.add(p)
            tokens.add(p.capitalize())
            if p.endswith("s"):
                tokens.add(p[:-1])
                tokens.add(p[:-1].capitalize())
    return [t for t in tokens if t]


def scan_consumer_impact(
    consumer_dir: Path,
    consumer_service: str,
    producer_service: str,
    consumer_contract: Path,
    producer_contract: Path,
    finding: Finding,
) -> ConsumerImpact:
    """
    Deterministically scan the consumer workspace directory for files referencing
    the breaking change. Distinguishes confirmed affected files from likely affected files.
    """
    consumer_dir = consumer_dir.resolve()
    try:
        rel_contract = str(consumer_contract.resolve().relative_to(consumer_dir)).replace("\\", "/")
    except ValueError:
        rel_contract = str(consumer_contract).replace("\\", "/")

    # Detect common source and test root directories
    source_path: str | None = None
    test_path: str | None = None
    if (consumer_dir / "src" / "main").exists():
        source_path = "src/main"
    elif (consumer_dir / "src").exists():
        source_path = "src"

    if (consumer_dir / "src" / "test").exists():
        test_path = "src/test"
    elif (consumer_dir / "tests").exists():
        test_path = "tests"

    confirmed_src: list[str] = []
    confirmed_test: list[str] = []
    likely_src: list[str] = []
    likely_test: list[str] = []

    field_tokens = _extract_field_tokens(finding.affected_field)
    likely_tokens = _extract_likely_tokens(finding.endpoint, finding)

    if consumer_dir.is_dir():
        for root, dirs, files in os.walk(consumer_dir):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for file in sorted(files):
                if file == "contractguard.yaml" or file == "contractguard.yml":
                    continue
                path = Path(root) / file
                if path.suffix.lower() not in VALID_EXTENSIONS:
                    continue

                try:
                    rel_path = str(path.relative_to(consumer_dir)).replace("\\", "/")
                except ValueError:
                    rel_path = str(path).replace("\\", "/")

                try:
                    content = path.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    continue

                is_test_file = (
                    "test" in path.parts
                    or "Test" in path.name
                    or path.name.startswith("test_")
                    or path.name.endswith("_test.py")
                    or "fixtures" in path.parts
                    or "fixture" in path.parts
                )

                # Check confirmed matches
                has_field_match = any(token in content for token in field_tokens)
                if has_field_match:
                    if is_test_file:
                        confirmed_test.append(rel_path)
                    else:
                        confirmed_src.append(rel_path)
                elif any(token in content for token in likely_tokens):
                    # Likely match only if not already confirmed
                    if is_test_file:
                        likely_test.append(rel_path)
                    else:
                        likely_src.append(rel_path)

    confirmed_src.sort()
    confirmed_test.sort()
    likely_src.sort()
    likely_test.sort()

    return ConsumerImpact(
        consumer_service=consumer_service,
        producer_service=producer_service,
        consumer_root=str(consumer_dir).replace("\\", "/"),
        endpoint=finding.endpoint,
        affected_field=finding.affected_field,
        change_kind=finding.change_kind.value,
        severity=finding.severity.value,
        producer_contract=str(producer_contract).replace("\\", "/"),
        consumer_contract=str(consumer_contract).replace("\\", "/"),
        contract_path=rel_contract,
        source_path=source_path,
        test_path=test_path,
        confirmed_source_files=confirmed_src,
        confirmed_test_files=confirmed_test,
        likely_source_files=likely_src,
        likely_test_files=likely_test,
        detail=finding.detail,
        reason=finding.reason,
    )
