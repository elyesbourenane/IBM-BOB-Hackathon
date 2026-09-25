"""Mistral API provider implementation."""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Callable

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from .provider import (
    LLMError,
    LLMProvider,
    LLMRateLimitError,
    LLMResponse,
    LLMResponseParseError,
    LLMTimeoutError,
    LLMUnavailableError,
)

DEFAULT_MODEL = "mistral-small-latest"
DEFAULT_BASE_URL = "https://api.mistral.ai/v1"
DEFAULT_TIMEOUT = 30.0
DEFAULT_MAX_RETRIES = 3


def _default_http_post(url: str, headers: dict[str, str], payload: bytes, timeout: float) -> tuple[int, bytes, Any]:
    """Execute HTTP POST using urllib with timeout. Returns (status, body, headers)."""
    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.read(), resp.headers


class MistralProvider(LLMProvider):
    """
    Client for the official Mistral AI chat completions API.
    Uses pure standard library with minimal dependency footprint.
    Includes automatic rate limit backoff and retries.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        timeout: float | None = None,
        max_retries: int | None = None,
        http_post_fn: Callable[..., Any] | None = None,
    ) -> None:
        self._api_key = api_key or os.environ.get("MISTRAL_API_KEY")
        self._model = model or os.environ.get("MISTRAL_MODEL", DEFAULT_MODEL)
        self._base_url = (base_url or os.environ.get("MISTRAL_API_BASE", DEFAULT_BASE_URL)).rstrip("/")
        timeout_env = os.environ.get("MISTRAL_TIMEOUT")
        self._timeout = timeout or (float(timeout_env) if timeout_env else DEFAULT_TIMEOUT)
        retries_env = os.environ.get("MISTRAL_MAX_RETRIES")
        self._max_retries = max_retries if max_retries is not None else (int(retries_env) if retries_env else DEFAULT_MAX_RETRIES)
        self._http_post = http_post_fn or _default_http_post

    @property
    def name(self) -> str:
        return "mistral"

    @property
    def model_name(self) -> str:
        return self._model

    def is_configured(self) -> bool:
        """Check if an API key is provided or offline demo mode is active."""
        if os.environ.get("CONTRACTGUARD_MOCK_AI") == "1":
            return True
        return bool(self._api_key and self._api_key.strip())

    def complete(
        self,
        messages: list[dict[str, str]],
        json_mode: bool = True,
        temperature: float = 0.1,
    ) -> LLMResponse:
        """Send chat completion request to Mistral."""
        if not self.is_configured():
            raise LLMUnavailableError(
                "MISTRAL_API_KEY environment variable is not configured."
            )

        # Offline / Demo mode fallback when API quota is exhausted
        if os.environ.get("CONTRACTGUARD_MOCK_AI") == "1":
            mock_payload = {
                "summary": "payment-service renamed paymentAmount to totalAmount breaking downstream consumer contracts.",
                "breaking_change_explanation": "The producer renamed 'paymentAmount' to 'totalAmount' in GET /api/payments/{id}. Existing consumers expect 'paymentAmount' and will fail to deserialize API responses.",
                "impact": [
                    {
                        "consumer": "payment-client",
                        "files": [
                            "src/main/java/com/example/paymentclient/model/PaymentResponse.java",
                            "src/main/java/com/example/paymentclient/service/PaymentDisplayService.java",
                        ],
                        "tests_to_update": [
                            "src/test/java/com/example/paymentclient/client/PaymentClientTest.java",
                            "src/test/java/com/example/paymentclient/model/PaymentResponseSerializationTest.java",
                            "src/test/java/com/example/paymentclient/service/PaymentDisplayServiceTest.java",
                        ],
                        "reason": "Consumer depends on paymentAmount in DTO and service layer",
                        "confirmed_impact": [
                            "paymentAmount field removed from API response schema",
                            "PaymentResponse.java directly maps paymentAmount",
                        ],
                        "likely_impact": [
                            "PaymentClient.java and PaymentDisplayService.java data formatting",
                        ],
                    },
                    {
                        "consumer": "order-service",
                        "files": [],
                        "tests_to_update": [],
                        "reason": "Contract expects paymentAmount",
                        "confirmed_impact": ["Contract dependency broken"],
                        "likely_impact": [],
                    },
                    {
                        "consumer": "reporting-service",
                        "files": [],
                        "tests_to_update": [],
                        "reason": "Contract expects paymentAmount",
                        "confirmed_impact": ["Contract dependency broken"],
                        "likely_impact": [],
                    },
                ],
                "repair_plan": [
                    "1. Update consumer contracts (contracts/payment-service.yaml) across payment-client, order-service, and reporting-service to expect totalAmount",
                    "2. In payment-client: update PaymentResponse.java @JsonProperty('totalAmount') and getter/setter",
                    "3. Update PaymentDisplayService.java to use getTotalAmount()",
                    "4. Update test fixtures and assertions in PaymentClientTest, PaymentResponseSerializationTest, and PaymentDisplayServiceTest",
                    "5. Run consumer unit tests (mvn test)",
                    "6. Re-run ContractGuard (contract-guard discover ..) to verify 3/3 compatibility",
                    "7. Evaluate release safety gate (contract-guard verify ..) and generate evidence",
                ],
                "migration_options": [
                    "Producer can temporarily support both 'paymentAmount' and 'totalAmount' during a deprecation window."
                ],
            }
            content_str = json.dumps(mock_payload) if json_mode else "CONTRACTGUARD MISTRAL OK"
            return LLMResponse(content=content_str, model=f"{self._model} (mock-demo)", raw=mock_payload)

        endpoint = f"{self._base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        body: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}

        payload = json.dumps(body).encode("utf-8")

        for attempt in range(self._max_retries + 1):
            try:
                post_res = self._http_post(endpoint, headers, payload, self._timeout)
                if len(post_res) == 3:
                    status, raw_bytes, resp_headers = post_res
                else:
                    status, raw_bytes = post_res
                    resp_headers = {}
                break
            except urllib.error.HTTPError as exc:
                err_body = ""
                try:
                    if getattr(exc, "fp", None) is not None:
                        err_body = exc.read().decode("utf-8", errors="replace")
                except Exception:
                    err_body = str(exc)

                if exc.code == 429:
                    if attempt < self._max_retries:
                        retry_after = exc.headers.get("Retry-After") if getattr(exc, "headers", None) else None
                        wait_time = float(retry_after) if retry_after and str(retry_after).isdigit() else float((2 ** attempt) * 0.1)
                        wait_time = min(wait_time, 10.0)
                        time.sleep(wait_time)
                        continue
                    raise LLMRateLimitError(
                        f"Mistral API rate limit exceeded (HTTP 429) after {self._max_retries} retries: {err_body}"
                    ) from exc
                raise LLMError(f"Mistral API returned HTTP {exc.code}: {err_body}") from exc
            except urllib.error.URLError as exc:
                if "timed out" in str(exc).lower() or isinstance(exc.reason, TimeoutError):
                    raise LLMTimeoutError(f"Mistral API request timed out after {self._timeout}s: {exc}") from exc
                raise LLMError(f"Mistral API connection failed: {exc}") from exc
            except TimeoutError as exc:
                raise LLMTimeoutError(f"Mistral API request timed out after {self._timeout}s: {exc}") from exc
            except LLMError:
                raise
            except Exception as exc:
                raise LLMError(f"Mistral API request failed: {exc}") from exc

        try:
            data = json.loads(raw_bytes.decode("utf-8"))
        except Exception as exc:
            raise LLMResponseParseError(f"Failed to parse Mistral API JSON response: {exc}") from exc

        choices = data.get("choices")
        if not choices or not isinstance(choices, list):
            raise LLMResponseParseError(f"Mistral API response missing choices: {data}")

        first_choice = choices[0]
        message = first_choice.get("message") or {}
        content = message.get("content", "")

        return LLMResponse(
            content=content,
            model=data.get("model", self._model),
            raw=data,
        )
