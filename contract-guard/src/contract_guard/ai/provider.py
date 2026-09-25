"""LLM Provider abstraction."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


class LLMError(Exception):
    """Base exception for LLM provider errors."""


class LLMUnavailableError(LLMError):
    """Raised when the LLM provider is not configured or unavailable."""


class LLMTimeoutError(LLMError):
    """Raised when an LLM request times out."""


class LLMRateLimitError(LLMError):
    """Raised when the LLM provider rate limit is exceeded (HTTP 429)."""


class LLMResponseParseError(LLMError):
    """Raised when the LLM response cannot be parsed."""


@dataclass
class LLMResponse:
    """Standardized response from an LLM provider."""

    content: str
    model: str
    raw: dict[str, Any] = field(default_factory=dict)


class LLMProvider(ABC):
    """Abstract interface for LLM integrations."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Name of the provider (e.g. 'mistral')."""

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Name of the configured model."""

    @abstractmethod
    def is_configured(self) -> bool:
        """Return True if credentials and configuration are present."""

    @abstractmethod
    def complete(
        self,
        messages: list[dict[str, str]],
        json_mode: bool = True,
        temperature: float = 0.1,
    ) -> LLMResponse:
        """
        Send a chat completion request to the LLM.

        Parameters
        ----------
        messages:
            List of message dicts with 'role' ('system', 'user', 'assistant') and 'content'.
        json_mode:
            Whether to enforce JSON object response format.
        temperature:
            Sampling temperature (low for deterministic analysis).

        Returns
        -------
        LLMResponse
        """
