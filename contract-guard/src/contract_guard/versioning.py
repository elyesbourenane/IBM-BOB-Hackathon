"""
Deterministic Semantic Versioning (SemVer) recommendation engine.

Translates contract compatibility verdicts and changes into standard SemVer bumps:
- BREAKING CHANGE -> MAJOR
- BACKWARD-COMPATIBLE ADDITION -> MINOR
- NON-CONTRACT / DOCUMENTATION-ONLY CHANGE -> PATCH

Never overrides the deterministic compatibility engine.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional

from .models import Finding, Severity, ChangeKind


@dataclass
class SemVerRecommendation:
    """Deterministic SemVer bump recommendation."""

    bump: str  # "major" | "minor" | "patch" | "none"
    current_version: Optional[str] = None
    recommended_version: Optional[str] = None
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "bump": self.bump,
            "current_version": self.current_version,
            "recommended_version": self.recommended_version,
            "reason": self.reason,
        }


_SEMVER_REGEX = re.compile(
    r"^v?(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
)


def parse_semver(version_str: Optional[str]) -> Optional[tuple[int, int, int]]:
    """
    Parse a semantic version string (e.g. '1.4.0' or 'v2.1.3') into (major, minor, patch).
    Returns None if the version string is empty, invalid, or does not follow SemVer.
    """
    if not version_str or not isinstance(version_str, str):
        return None
    match = _SEMVER_REGEX.match(version_str.strip())
    if not match:
        return None
    return (
        int(match.group("major")),
        int(match.group("minor")),
        int(match.group("patch")),
    )


def bump_version(current_version: str, bump: str) -> Optional[str]:
    """
    Apply a major, minor, or patch bump to a valid SemVer string.
    Returns None if current_version is not valid SemVer.
    """
    parsed = parse_semver(current_version)
    if not parsed:
        return None

    maj, minr, pat = parsed
    if bump.lower() == "major":
        return f"{maj + 1}.0.0"
    elif bump.lower() == "minor":
        return f"{maj}.{minr + 1}.0"
    elif bump.lower() == "patch":
        return f"{maj}.{minr}.{pat + 1}"
    elif bump.lower() == "none":
        return f"{maj}.{minr}.{pat}"
    return None


def calculate_semver_recommendation(
    findings: list[Finding | dict[str, Any]],
    has_contract_changes: bool = True,
    current_version: Optional[str] = None,
) -> SemVerRecommendation:
    """
    Deterministically recommend a SemVer bump based on detected contract differences.

    Parameters
    ----------
    findings:
        List of findings (Finding objects or serialized finding dictionaries).
    has_contract_changes:
        Whether any OpenAPI contract file was modified in Git.
    current_version:
        Optional baseline version (e.g. from openapi.yaml `info.version` or git tag).
        If omitted or invalid, bump category and reason are returned without inventing a version.
    """
    breaking_count = 0
    compatible_additions = 0

    for f in findings:
        if isinstance(f, Finding):
            if f.is_breaking:
                breaking_count += 1
            elif f.change_kind == ChangeKind.FIELD_OPTIONAL_ADDED:
                compatible_additions += 1
        elif isinstance(f, dict):
            sev = f.get("severity")
            ck = f.get("change_kind")
            if sev == "breaking" or ck in ("field_removed", "field_renamed", "field_type_changed", "field_required_added", "endpoint_removed", "contract_error"):
                breaking_count += 1
            elif ck == "field_optional_added" or sev == "compatible":
                compatible_additions += 1

    # 1. Breaking changes always mandate MAJOR bump
    if breaking_count > 0:
        bump = "major"
        reason = f"Detected {breaking_count} breaking API contract change(s)."
    # 2. Backward-compatible additions mandate MINOR bump
    elif compatible_additions > 0:
        bump = "minor"
        reason = f"Detected {compatible_additions} backward-compatible API addition(s)."
    # 3. Contract modified but 0 differences in schema or doc changes
    elif has_contract_changes:
        bump = "patch"
        reason = "API contract modified with no breaking or additive schema differences."
    # 4. No contract changes detected
    else:
        bump = "none"
        reason = "No API contract changes detected."

    # Validate and calculate recommended target version if current_version is provided
    recommended_version: Optional[str] = None
    validated_current: Optional[str] = None

    if current_version:
        cleaned = current_version.strip()
        parsed = parse_semver(cleaned)
        if parsed:
            validated_current = cleaned
            recommended_version = bump_version(cleaned, bump)

    return SemVerRecommendation(
        bump=bump,
        current_version=validated_current,
        recommended_version=recommended_version,
        reason=reason,
    )
