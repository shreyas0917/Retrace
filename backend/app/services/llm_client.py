"""OpenAI-compatible chat completion client with retries (v1.0).

Temperature is fixed at 0 per PRD. Tests inject a fake provider via
set_llm_provider, or a fake HTTP layer via `transport=httpx.MockTransport(...)`
/ set_llm_transport().

Resilience model
----------------
* One shared httpx.Client (connection pooling) with separate connect and read
  timeouts: connect = MODEL_CONNECT_TIMEOUT_SECONDS, read = per-call timeout.
* The per-call `timeout` is the *total* budget. Every retry's read timeout is
  clipped to the remaining budget, and a retry is only scheduled when the
  backoff delay still fits inside the budget.
* Retries (MODEL_MAX_RETRIES, exponential backoff with jitter from
  MODEL_RETRY_BACKOFF_SECONDS, Retry-After honoured when small) only on:
  httpx transport errors (connection refused/reset, protocol errors) and HTTP
  429 / 5xx. Never on other 4xx, never on timeouts (a timeout already consumed
  the budget), never on malformed bodies.
* Metrics: llm.attempts, llm.retries, llm.failures, llm.timeouts.
"""

from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from app.core.config import Settings, get_settings
from app.core.errors import GenerationError, GenerationTimeoutError
from app.core.logging import get_logger
from app.core.metrics import get_metrics

logger = get_logger(__name__)

GENERATION_TEMPERATURE = 0.0

RETRYABLE_STATUS = {429, 500, 502, 503, 504}
MAX_RETRY_AFTER_SECONDS = 30.0


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


# ----------------------------------------------------------------------------
# Shared HTTP client
# ----------------------------------------------------------------------------

_client_lock = threading.Lock()
_shared_client: httpx.Client | None = None
_transport_override: httpx.BaseTransport | None = None


def set_llm_transport(transport: httpx.BaseTransport | None) -> None:
    """Test hook: route the shared client through e.g. httpx.MockTransport."""
    global _transport_override, _shared_client
    with _client_lock:
        _transport_override = transport
        if _shared_client is not None:
            try:
                _shared_client.close()
            except Exception:  # noqa: BLE001
                pass
            _shared_client = None


def get_shared_client() -> httpx.Client:
    global _shared_client
    with _client_lock:
        if _shared_client is None:
            _shared_client = httpx.Client(
                transport=_transport_override,
                limits=httpx.Limits(max_connections=32, max_keepalive_connections=8),
            )
        return _shared_client


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        seconds = float(value)
    except ValueError:
        return None  # HTTP-date form: ignore, use backoff
    if seconds < 0:
        return None
    return seconds


class OpenAICompatibleProvider:
    """Minimal OpenAI-compatible /chat/completions client with bounded retries."""

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep=time.sleep,
    ) -> None:
        self._base_url = settings.model_base_url.rstrip("/")
        self._api_key = settings.model_api_key
        self._default_timeout = settings.model_timeout_seconds
        self._connect_timeout = settings.model_connect_timeout_seconds
        self._max_retries = max(0, int(settings.model_max_retries))
        self._backoff = max(0.0, float(settings.model_retry_backoff_seconds))
        self._sleep = sleep
        # Per-instance client only when a transport is injected (tests);
        # otherwise the process-wide pooled client.
        self._client: httpx.Client | None = (
            httpx.Client(transport=transport) if transport is not None else None
        )

    @property
    def client(self) -> httpx.Client:
        return self._client if self._client is not None else get_shared_client()

    def _timeout_for(self, remaining: float, total: float) -> httpx.Timeout:
        read = max(0.05, min(total, remaining))
        connect = max(0.05, min(self._connect_timeout, read))
        return httpx.Timeout(connect=connect, read=read, write=read, pool=connect)

    def _delay(self, attempt: int, retry_after: float | None) -> float:
        base = self._backoff * (2**attempt)
        jitter = random.uniform(0, self._backoff * 0.25) if self._backoff else 0.0
        delay = base + jitter
        if retry_after is not None and retry_after <= MAX_RETRY_AFTER_SECONDS:
            delay = max(delay, retry_after)
        return delay

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        model: str,
        timeout: float | None = None,
    ) -> LLMResult:
        timeout = float(timeout if timeout is not None else self._default_timeout)
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
        metrics = get_metrics()

        started = time.perf_counter()
        deadline = started + timeout
        attempt = 0
        response: httpx.Response | None = None

        while True:
            attempt += 1
            metrics.inc("llm.attempts")
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                metrics.inc("llm.timeouts")
                metrics.inc("llm.failures")
                raise GenerationTimeoutError(
                    "LLM request timed out",
                    details={"timeout_seconds": timeout, "attempts": attempt - 1},
                )

            retryable_reason: str | None = None
            retry_after: float | None = None
            last_error_details: dict[str, Any] = {}
            try:
                response = self.client.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=self._timeout_for(remaining, timeout),
                )
            except httpx.TimeoutException as exc:
                # Timeouts are never retried: the budget is the budget.
                metrics.inc("llm.timeouts")
                metrics.inc("llm.failures")
                raise GenerationTimeoutError(
                    "LLM request timed out",
                    details={"timeout_seconds": timeout, "attempts": attempt},
                ) from exc
            except httpx.HTTPError as exc:
                retryable_reason = f"transport_error: {type(exc).__name__}"
                last_error_details = {"error": str(exc)}
            else:
                if response.status_code in RETRYABLE_STATUS:
                    retryable_reason = f"http_{response.status_code}"
                    retry_after = _parse_retry_after(response.headers.get("Retry-After"))
                    last_error_details = {
                        "status_code": response.status_code,
                        "body": (response.text or "")[:300],
                    }

            if retryable_reason is None:
                break

            # Decide whether another attempt fits in retries + time budget.
            can_retry = attempt <= self._max_retries
            delay = self._delay(attempt - 1, retry_after) if can_retry else 0.0
            if can_retry and time.perf_counter() + delay >= deadline:
                can_retry = False
                retryable_reason += " (budget_exhausted)"
            if not can_retry:
                metrics.inc("llm.failures")
                logger.warning(
                    "llm_request_failed",
                    reason=retryable_reason,
                    attempts=attempt,
                    max_retries=self._max_retries,
                )
                details = dict(last_error_details)
                details["attempts"] = attempt
                if retryable_reason.startswith("transport_error"):
                    raise GenerationError("LLM request failed", details=details)
                raise GenerationError("LLM provider returned an error", details=details)

            metrics.inc("llm.retries")
            logger.warning(
                "llm_request_retry",
                reason=retryable_reason,
                attempt=attempt,
                next_delay_seconds=round(delay, 3),
                retry_after=retry_after,
            )
            self._sleep(delay)

        assert response is not None
        latency_ms = round((time.perf_counter() - started) * 1000, 2)

        if response.status_code == 401:
            metrics.inc("llm.failures")
            raise GenerationError(
                "LLM authentication failed",
                details={"status_code": 401},
            )
        if response.status_code >= 400:
            # Never echo Authorization; truncate body for logs/details.
            metrics.inc("llm.failures")
            body_preview = (response.text or "")[:300]
            raise GenerationError(
                "LLM provider returned an error",
                details={"status_code": response.status_code, "body": body_preview},
            )

        try:
            data = response.json()
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            metrics.inc("llm.failures")
            raise GenerationError(
                "LLM returned a malformed response",
                details={"error": str(exc)},
            ) from exc

        if content is None or str(content).strip() == "":
            metrics.inc("llm.failures")
            raise GenerationError("LLM returned an empty answer")

        usage = data.get("usage") or {}
        return LLMResult(
            content=str(content).strip(),
            model=data.get("model") or model,
            latency_ms=latency_ms,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            total_tokens=usage.get("total_tokens"),
            raw={"id": data.get("id"), "model": data.get("model"), "attempts": attempt},
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
