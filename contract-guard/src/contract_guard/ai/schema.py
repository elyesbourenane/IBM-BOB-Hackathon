"""Pydantic schemas for AI impact analysis and repair plans."""

from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, Field


class ConsumerImpactAnalysis(BaseModel):
    """AI analysis of impact on a single consumer."""

    consumer: str = Field(description="Name of the affected consumer service")
    files: list[str] = Field(
        default_factory=list,
        description="Source files in the consumer affected by this change",
    )
    tests_to_update: list[str] = Field(
        default_factory=list,
        description="Test files that should be updated to verify the repair",
    )
    reason: str = Field(
        default="",
        description="Explanation of why this consumer is affected",
    )
    confirmed_impact: list[str] = Field(
        default_factory=list,
        description="Definite, confirmed broken points (e.g. removed fields directly referenced)",
    )
    likely_impact: list[str] = Field(
        default_factory=list,
        description="Inferred or secondary impacts (e.g. callers, fixtures)",
    )


class AIAnalysisResult(BaseModel):
    """Structured output expected from the LLM."""

    summary: str = Field(description="High-level executive summary of the API change and impact")
    breaking_change_explanation: str = Field(
        default="",
        description="Detailed technical explanation of what changed and why it breaks backward compatibility",
    )
    impact: list[ConsumerImpactAnalysis] = Field(
        default_factory=list,
        description="Impact breakdown by consumer",
    )
    repair_plan: list[str] = Field(
        default_factory=list,
        description="Step-by-step actionable repair plan for IBM Bob / developers",
    )
    migration_options: list[str] = Field(
        default_factory=list,
        description="Backward-compatible alternatives or migration paths",
    )


class AIImpactReport(BaseModel):
    """Enriched report wrapping deterministic and AI analysis."""

    status: str = Field(
        description="Availability status: 'available', 'unavailable', or 'error'"
    )
    provider: str = Field(default="mistral")
    model: str = Field(default="")
    analysis: Optional[AIAnalysisResult] = None
    error_message: Optional[str] = None

    @classmethod
    def unavailable(cls, reason: str, provider: str = "mistral", model: str = "") -> "AIImpactReport":
        return cls(
            status="unavailable",
            provider=provider,
            model=model,
            analysis=None,
            error_message=reason,
        )

    @classmethod
    def error(cls, message: str, provider: str = "mistral", model: str = "") -> "AIImpactReport":
        return cls(
            status="error",
            provider=provider,
            model=model,
            analysis=None,
            error_message=message,
        )
