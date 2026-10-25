"""OpenAI-compatible chat completion client.

Temperature is fixed at 0 per PRD. Tests inject a fake provider via set_llm_provider.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from app.core.config import Settings, get_settings
from app.core.errors import GenerationError, GenerationTimeoutError
from app.core.logging import get_logger

logger = get_logger(__name__)

GENERATION_TEMPERATURE = 0.0


@dataclass
class LLMResult:
    content: str
    model: str
    latency_ms: float
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    raw: dict[str, Any] | None = None


class LLMProvider(Protocol):
    def complete(self, messages: list[dict[str, str]], *, model: str, timeout: float) -> LLMResult:
        ...


class OpenAICompatibleProvider:
    """Minimal OpenAI-compatible /chat/completions client."""

    def __init__(self, settings: Settings) -> None:
        self._base_url = settings.model_base_url.rstrip("/")
        self._api_key = settings.model_api_key
        self._default_timeout = settings.model_timeout_seconds

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        model: str,
        timeout: float | None = None,
    ) -> LLMResult:
        import time

        timeout = timeout if timeout is not None else self._default_timeout
        url = f"{self._base_url}/chat/completions"
        payload = {
            "model": model,
            "temperature": GENERATION_TEMPERATURE,
            "messages": messages,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        started = time.perf_counter()
        try:
            response = httpx.post(url, headers=headers, json=payload, timeout=timeout)
        except httpx.TimeoutException as exc:
            raise GenerationTimeoutError(
                "LLM request timed out",
                details={"timeout_seconds": timeout},
            ) from exc
        except httpx.HTTPError as exc:
            raise GenerationError(
                "LLM request failed",
                details={"error": str(exc)},
            ) from exc

        latency_ms = round((time.perf_counter() - started) * 1000, 2)

        if response.status_code == 401:
            raise GenerationError(
                "LLM authentication failed",
                details={"status_code": 401},
            )
        if response.status_code >= 400:
            # Never echo Authorization; truncate body for logs/details.
            body_preview = (response.text or "")[:300]
            raise GenerationError(
                "LLM provider returned an error",
                details={"status_code": response.status_code, "body": body_preview},
            )

        try:
            data = response.json()
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise GenerationError(
                "LLM returned a malformed response",
                details={"error": str(exc)},
            ) from exc

        if content is None or str(content).strip() == "":
            raise GenerationError("LLM returned an empty answer")

        usage = data.get("usage") or {}
        return LLMResult(
            content=str(content).strip(),
            model=data.get("model") or model,
            latency_ms=latency_ms,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            total_tokens=usage.get("total_tokens"),
            raw={"id": data.get("id"), "model": data.get("model")},
        )


_override_provider: LLMProvider | None = None


def set_llm_provider(provider: LLMProvider | None) -> None:
    """Test hook to replace the live OpenAI-compatible provider."""
    global _override_provider
    _override_provider = provider


def get_llm_provider(settings: Settings | None = None) -> LLMProvider:
    if _override_provider is not None:
        return _override_provider
    return OpenAICompatibleProvider(settings or get_settings())
