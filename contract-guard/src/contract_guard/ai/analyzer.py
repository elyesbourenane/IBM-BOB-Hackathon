"""
AI Impact Analyzer: constructs focused context snippets and coordinates
with an LLM provider to explain contract breakages and generate repair plans.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from ..discovery import DiscoveryReport
from ..impact import ConsumerImpact
from .mistral import MistralProvider
from .provider import LLMError, LLMRateLimitError, LLMProvider, LLMUnavailableError
from .schema import AIAnalysisResult, AIImpactReport, ConsumerImpactAnalysis


def _extract_file_snippet(file_path: Path, match_token: str, max_lines: int = 15) -> str:
    """Extract a small snippet of lines around a token in a file."""
    if not file_path.is_file():
        return ""
    try:
        lines = file_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return ""

    match_idx = -1
    for i, line in enumerate(lines):
        if match_token.lower() in line.lower():
            match_idx = i
            break

    if match_idx == -1:
        # Fall back to first few lines
        selected = lines[:max_lines]
        return "\n".join(selected)

    start = max(0, match_idx - 4)
    end = min(len(lines), match_idx + max_lines - 4)
    return "\n".join(lines[start:end])


def build_context_snippets(report: DiscoveryReport) -> list[dict[str, Any]]:
    """
    Extract ONLY relevant, minimal snippets of contracts, source code, and tests
    for the LLM. Does NOT send entire files or entire repositories.
    """
    snippets: list[dict[str, Any]] = []

    for impact in report.impacts:
        consumer_root = Path(report.workspace_root) / impact.consumer_service
        # If relative paths or different workspace layout, resolve appropriately
        if not consumer_root.exists():
            # Try finding the consumer contract parent
            c_contract_path = Path(impact.consumer_contract)
            if c_contract_path.exists():
                consumer_root = c_contract_path.parent.parent
            else:
                consumer_root = Path(report.workspace_root)

        entry: dict[str, Any] = {
            "consumer_service": impact.consumer_service,
            "producer_service": impact.producer_service,
            "endpoint": impact.endpoint,
            "affected_field": impact.affected_field,
            "change_kind": impact.change_kind,
            "detail": impact.detail,
            "contract_snippets": {},
            "source_snippets": {},
            "test_snippets": {},
        }

        # Contract snippets
        prod_path = Path(impact.producer_contract)
        if prod_path.exists():
            entry["contract_snippets"]["producer"] = _extract_file_snippet(
                prod_path, impact.affected_field.split(".")[-1], max_lines=15
            )

        cons_path = Path(impact.consumer_contract)
        if cons_path.exists():
            entry["contract_snippets"]["consumer"] = _extract_file_snippet(
                cons_path, impact.affected_field.split(".")[-1], max_lines=15
            )

        # Confirmed source snippets (max 2 files)
        field_leaf = impact.affected_field.split(".")[-1]
        for src_rel in impact.confirmed_source_files[:2]:
            full_path = consumer_root / src_rel
            if full_path.exists():
                entry["source_snippets"][src_rel] = _extract_file_snippet(
                    full_path, field_leaf, max_lines=12
                )

        # Confirmed test snippets (max 2 files)
        for test_rel in impact.confirmed_test_files[:2]:
            full_path = consumer_root / test_rel
            if full_path.exists():
                entry["test_snippets"][test_rel] = _extract_file_snippet(
                    full_path, field_leaf, max_lines=12
                )

        snippets.append(entry)

    return snippets


SYSTEM_PROMPT = """You are ContractGuard AI, an API reliability specialist integrated with IBM Bob.
ContractGuard has already executed deterministic contract comparison.
CRITICAL RULES:
1. The deterministic compatibility verdict is FINAL and CANNOT be overridden.
   If ContractGuard says BREAKING, it IS breaking. You must explain why and help repair it.
2. Strictly distinguish CONFIRMED FACTS from INFERRED/LIKELY impact.
   - CONFIRMED: Exact contract diffs, fields removed/renamed, source/test files with exact matches.
   - LIKELY: Downstream usages, fixtures, or callers that might need adaptation.
3. Produce a structured, actionable repair plan that an autonomous agent (IBM Bob) or engineer can execute.
4. Propose backward-compatible alternatives or migration options for the producer.

You must reply with a valid JSON object matching this schema:
{
  "summary": "High-level summary of the contract drift and impact",
  "breaking_change_explanation": "Detailed explanation of what changed and why it breaks consumers",
  "impact": [
    {
      "consumer": "consumer-service-name",
      "files": ["path/to/affected/Source.java"],
      "tests_to_update": ["path/to/affectedTest.java"],
      "reason": "Why this consumer is affected",
      "confirmed_impact": ["Confirmed breaking point 1", "..."],
      "likely_impact": ["Likely affected area 1", "..."]
    }
  ],
  "repair_plan": [
    "1. Actionable step one...",
    "2. Actionable step two..."
  ],
  "migration_options": [
    "Alternative 1: Backward-compatible approach..."
  ]
}
"""


class ImpactAnalyzer:
    """Orchestrates AI-assisted impact analysis using an LLMProvider."""

    def __init__(self, provider: LLMProvider | None = None) -> None:
        self.provider = provider or MistralProvider()

    def analyze(self, report: DiscoveryReport) -> AIImpactReport:
        """
        Analyze a DiscoveryReport. If no breaking changes exist, returns a clean compatible summary.
        If the provider is not configured, returns an 'unavailable' report.
        If the provider fails or returns malformed output, gracefully returns an 'error' report.
        """
        if not report.affected_consumers and not report.breaking_findings:
            return AIImpactReport(
                status="available",
                provider=self.provider.name,
                model=self.provider.model_name,
                analysis=AIAnalysisResult(
                    summary="All checked consumer contracts are backward-compatible with the producer API. No breaking changes detected.",
                    breaking_change_explanation="None. All consumers match producer contract expectations.",
                    impact=[],
                    repair_plan=[],
                    migration_options=[],
                ),
            )

        if not self.provider.is_configured():
            return AIImpactReport.unavailable(
                "MISTRAL_API_KEY environment variable is not configured. AI impact analysis unavailable.",
                provider=self.provider.name,
                model=self.provider.model_name,
            )

        snippets = build_context_snippets(report)

        # Build focused prompt
        prompt_data = {
            "summary": report.summary,
            "consumers_checked": report.consumers_checked,
            "affected_consumers": report.affected_consumers,
            "breaking_findings": report.breaking_findings,
            "impact_details": [imp.to_dict() for imp in report.impacts],
            "focused_snippets": snippets,
        }

        user_prompt = (
            "Analyze the following deterministic contract findings and minimal context snippets.\n\n"
            f"{json.dumps(prompt_data, indent=2)}\n\n"
            "Return the structured JSON impact analysis and repair plan."
        )

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        try:
            response = self.provider.complete(messages, json_mode=True)
            content = response.content.strip()
            # Clean possible markdown fence blocks if present
            if content.startswith("```json"):
                content = content[7:]
            if content.startswith("```"):
                content = content[3:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()

            result = AIAnalysisResult.model_validate_json(content)
            return AIImpactReport(
                status="available",
                provider=self.provider.name,
                model=response.model or self.provider.model_name,
                analysis=result,
            )
        except (ValidationError, json.JSONDecodeError) as exc:
            return AIImpactReport.error(
                f"Failed to validate LLM response schema: {exc}",
                provider=self.provider.name,
                model=self.provider.model_name,
            )
        except LLMUnavailableError as exc:
            return AIImpactReport.unavailable(
                str(exc),
                provider=self.provider.name,
                model=self.provider.model_name,
            )
        except LLMRateLimitError as exc:
            return AIImpactReport.error(
                f"Mistral API rate limit reached (HTTP 429). Deterministic findings remain 100% active and accurate. Details: {exc}",
                provider=self.provider.name,
                model=self.provider.model_name,
            )
        except LLMError as exc:
            return AIImpactReport.error(
                f"LLM provider error: {exc}",
                provider=self.provider.name,
                model=self.provider.model_name,
            )
        except Exception as exc:
            return AIImpactReport.error(
                f"Unexpected error during AI analysis: {exc}",
                provider=self.provider.name,
                model=self.provider.model_name,
            )
