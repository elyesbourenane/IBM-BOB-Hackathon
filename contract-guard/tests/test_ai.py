"""Tests for the AI impact analysis layer and Mistral provider."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from contract_guard.ai.analyzer import ImpactAnalyzer, build_context_snippets
from contract_guard.ai.mistral import MistralProvider
from contract_guard.ai.provider import (
    LLMError,
    LLMProvider,
    LLMResponse,
    LLMTimeoutError,
    LLMUnavailableError,
)
from contract_guard.ai.schema import (
    AIAnalysisResult,
    AIImpactReport,
    ConsumerImpactAnalysis,
)
from contract_guard.discovery import DiscoveryReport
from contract_guard.impact import ConsumerImpact


class MockLLMProvider(LLMProvider):
    """Configurable mock provider for testing without network."""

    def __init__(
        self,
        configured: bool = True,
        response_content: str = "",
        raise_exc: Exception | None = None,
        model_name: str = "mock-model",
    ) -> None:
        self._configured = configured
        self._response_content = response_content
        self._raise_exc = raise_exc
        self._model_name = model_name
        self.call_history: list[dict] = []

    @property
    def name(self) -> str:
        return "mock"

    @property
    def model_name(self) -> str:
        return self._model_name

    def is_configured(self) -> bool:
        return self._configured

    def complete(
        self,
        messages: list[dict[str, str]],
        json_mode: bool = True,
        temperature: float = 0.1,
    ) -> LLMResponse:
        self.call_history.append({"messages": messages, "json_mode": json_mode})
        if self._raise_exc:
            raise self._raise_exc
        return LLMResponse(content=self._response_content, model=self._model_name)


def _make_sample_report() -> DiscoveryReport:
    impact = ConsumerImpact(
        consumer_service="payment-client",
        producer_service="payment-service",
        endpoint="GET /api/payments/{id}",
        affected_field="paymentAmount",
        change_kind="field_renamed",
        severity="breaking",
        producer_contract="/fake/docs/openapi.yaml",
        consumer_contract="/fake/contracts/payment-service.yaml",
        contract_path="contracts/payment-service.yaml",
        detail="Consumer expects paymentAmount but producer now uses totalAmount.",
        reason="Field was renamed.",
        confirmed_source_files=["src/main/PaymentResponse.java"],
        confirmed_test_files=["src/test/PaymentClientTest.java"],
    )
    return DiscoveryReport(
        workspace_root="/fake",
        producer_filter=None,
        configs_found=1,
        consumers_checked=["payment-client"],
        compatible_consumers=[],
        affected_consumers=["payment-client"],
        results=[],
        breaking_findings=[
            {
                "consumer_service": "payment-client",
                "producer_service": "payment-service",
                "endpoint": "GET /api/payments/{id}",
                "affected_field": "paymentAmount",
                "change_kind": "field_renamed",
                "severity": "breaking",
                "detail": "Consumer expects paymentAmount but producer now uses totalAmount.",
                "reason": "Field was renamed.",
            }
        ],
        impacts=[impact],
    )


# --- Mistral Provider Unit Tests ---

def test_mistral_provider_unconfigured_when_no_key(monkeypatch):
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    provider = MistralProvider()
    assert not provider.is_configured()
    with pytest.raises(LLMUnavailableError):
        provider.complete([{"role": "user", "content": "hi"}])


def test_mistral_provider_successful_response():
    fake_body = {
        "model": "mistral-small-latest",
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": json.dumps({"summary": "test passed"}),
                }
            }
        ],
    }

    def fake_post(url, headers, payload, timeout):
        assert "Bearer test-key" in headers["Authorization"]
        return 200, json.dumps(fake_body).encode("utf-8")

    provider = MistralProvider(api_key="test-key", http_post_fn=fake_post)
    assert provider.is_configured()
    resp = provider.complete([{"role": "user", "content": "hello"}])
    assert resp.model == "mistral-small-latest"
    assert "test passed" in resp.content


def test_mistral_provider_timeout_handling():
    def fake_post_timeout(url, headers, payload, timeout):
        raise TimeoutError("timed out")

    provider = MistralProvider(api_key="test-key", http_post_fn=fake_post_timeout)
    with pytest.raises(LLMTimeoutError):
        provider.complete([{"role": "user", "content": "hello"}])


def test_mistral_provider_http_error_handling():
    def fake_post_err(url, headers, payload, timeout):
        raise LLMError("HTTP 401 Unauthorized")

    provider = MistralProvider(api_key="test-key", http_post_fn=fake_post_err)
    with pytest.raises(LLMError):
        provider.complete([{"role": "user", "content": "hello"}])


def test_mistral_provider_rate_limit_retry_success():
    calls = 0
    fake_body = {
        "model": "mistral-small-latest",
        "choices": [{"message": {"role": "assistant", "content": json.dumps({"summary": "recovered"})}}],
    }

    def fake_post_429_then_ok(url, headers, payload, timeout):
        nonlocal calls
        calls += 1
        if calls == 1:
            # Simulate 429
            import urllib.error
            raise urllib.error.HTTPError(url, 429, "Too Many Requests", {"Retry-After": "0"}, None)
        return 200, json.dumps(fake_body).encode("utf-8")

    provider = MistralProvider(api_key="test-key", max_retries=2, http_post_fn=fake_post_429_then_ok)
    resp = provider.complete([{"role": "user", "content": "hello"}])
    assert calls == 2
    assert "recovered" in resp.content


def test_mistral_provider_rate_limit_exhausted():
    import urllib.error

    def fake_post_always_429(url, headers, payload, timeout):
        raise urllib.error.HTTPError(url, 429, "Too Many Requests", {"Retry-After": "0"}, None)

    from contract_guard.ai.provider import LLMRateLimitError
    provider = MistralProvider(api_key="test-key", max_retries=1, http_post_fn=fake_post_always_429)
    with pytest.raises(LLMRateLimitError):
        provider.complete([{"role": "user", "content": "hello"}])


# --- ImpactAnalyzer Unit Tests ---

def test_analyzer_unconfigured_returns_unavailable():
    provider = MockLLMProvider(configured=False)
    analyzer = ImpactAnalyzer(provider=provider)
    report = _make_sample_report()

    ai_report = analyzer.analyze(report)
    assert ai_report.status == "unavailable"
    assert "MISTRAL_API_KEY" in (ai_report.error_message or "")
    assert ai_report.analysis is None


def test_analyzer_compatible_returns_early():
    provider = MockLLMProvider(configured=True)
    analyzer = ImpactAnalyzer(provider=provider)
    clean_report = DiscoveryReport(
        workspace_root="/fake",
        producer_filter=None,
        configs_found=1,
        consumers_checked=["payment-client"],
        compatible_consumers=["payment-client"],
        affected_consumers=[],
        results=[],
        breaking_findings=[],
    )

    ai_report = analyzer.analyze(clean_report)
    assert ai_report.status == "available"
    assert ai_report.analysis is not None
    assert "All checked consumer contracts are backward-compatible" in ai_report.analysis.summary
    assert len(provider.call_history) == 0  # No LLM call needed


def test_analyzer_successful_mocked_analysis():
    sample_json = {
        "summary": "payment-service renamed paymentAmount to totalAmount breaking payment-client",
        "breaking_change_explanation": "paymentAmount was renamed to totalAmount in GET /api/payments/{id}.",
        "impact": [
            {
                "consumer": "payment-client",
                "files": ["src/main/PaymentResponse.java"],
                "tests_to_update": ["src/test/PaymentClientTest.java"],
                "reason": "Property paymentAmount missing",
                "confirmed_impact": ["paymentAmount property missing"],
                "likely_impact": ["PaymentDisplayService usage"],
            }
        ],
        "repair_plan": [
            "1. Update consumer contract payment-service.yaml with totalAmount",
            "2. Update PaymentResponse.java @JsonProperty('totalAmount')",
            "3. Update PaymentClientTest.java with totalAmount",
            "4. Run tests and re-run ContractGuard",
        ],
        "migration_options": [
            "Support both paymentAmount and totalAmount during deprecation window"
        ],
    }

    provider = MockLLMProvider(
        configured=True, response_content=json.dumps(sample_json)
    )
    analyzer = ImpactAnalyzer(provider=provider)
    report = _make_sample_report()

    ai_report = analyzer.analyze(report)
    assert ai_report.status == "available"
    assert ai_report.analysis is not None
    assert "payment-service renamed paymentAmount" in ai_report.analysis.summary
    assert len(ai_report.analysis.repair_plan) == 4
    assert ai_report.analysis.impact[0].consumer == "payment-client"
    assert "src/main/PaymentResponse.java" in ai_report.analysis.impact[0].files


def test_analyzer_malformed_json_fails_gracefully():
    provider = MockLLMProvider(configured=True, response_content="Not valid JSON at all")
    analyzer = ImpactAnalyzer(provider=provider)
    report = _make_sample_report()

    ai_report = analyzer.analyze(report)
    assert ai_report.status == "error"
    assert ai_report.analysis is None
    assert "Failed to validate" in (ai_report.error_message or "")


def test_analyzer_provider_timeout_fails_gracefully():
    provider = MockLLMProvider(
        configured=True, raise_exc=LLMTimeoutError("Request timed out")
    )
    analyzer = ImpactAnalyzer(provider=provider)
    report = _make_sample_report()

    ai_report = analyzer.analyze(report)
    assert ai_report.status == "error"
    assert ai_report.analysis is None
    assert "Request timed out" in (ai_report.error_message or "")


def test_build_context_snippets_only_includes_minimal_lines(tmp_path: Path):
    c_root = tmp_path / "payment-client"
    c_root.mkdir()
    (c_root / "src" / "main").mkdir(parents=True)
    src_file = c_root / "src" / "main" / "Model.java"
    # Write 50 lines
    lines = [f"// Line {i}" for i in range(50)]
    lines[25] = "private Double paymentAmount;"
    src_file.write_text("\n".join(lines), encoding="utf-8")

    impact = ConsumerImpact(
        consumer_service="payment-client",
        producer_service="payment-service",
        endpoint="GET /api/payments/{id}",
        affected_field="paymentAmount",
        change_kind="field_renamed",
        severity="breaking",
        producer_contract=str(tmp_path / "openapi.yaml"),
        consumer_contract=str(tmp_path / "contract.yaml"),
        contract_path="contract.yaml",
        detail="detail",
        reason="reason",
        confirmed_source_files=["src/main/Model.java"],
    )
    report = DiscoveryReport(
        workspace_root=str(tmp_path),
        producer_filter=None,
        configs_found=1,
        consumers_checked=["payment-client"],
        compatible_consumers=[],
        affected_consumers=["payment-client"],
        results=[],
        breaking_findings=[],
        impacts=[impact],
    )

    snippets = build_context_snippets(report)
    assert len(snippets) == 1
    src_snippets = snippets[0]["source_snippets"]
    assert "src/main/Model.java" in src_snippets
    snippet_content = src_snippets["src/main/Model.java"]
    assert "paymentAmount" in snippet_content
    # Ensure it's not the entire 50-line file
    assert len(snippet_content.splitlines()) <= 15
