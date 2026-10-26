"""Judge runner: call LLM → parse JSON → validate → retry once → else malformed."""

from __future__ import annotations

import json
import re
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.core.ops import record_judge
from app.core.errors import GenerationTimeoutError
from app.services.llm_client import GENERATION_TEMPERATURE, get_llm_provider

logger = get_logger(__name__)

T = TypeVar("T", bound=BaseModel)


class JudgeMalformedError(Exception):
    """Raised when judge output fails schema validation after one retry."""

    def __init__(self, judge_type: str, detail: str) -> None:
        super().__init__(detail)
        self.judge_type = judge_type
        self.detail = detail


def _extract_json(text: str) -> Any:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


def run_structured_judge(
    *,
    judge_type: str,
    messages: list[dict[str, str]],
    schema: type[T],
    settings: Settings | None = None,
) -> tuple[T, dict[str, Any]]:
    """Returns (validated_model, meta) with attempts and latency."""
    settings = settings or get_settings()
    provider = get_llm_provider(settings)
    attempts = 0
    last_error = ""
    total_latency = 0.0
    raw_outputs: list[str] = []

    for attempt in range(2):  # original + one retry
        attempts = attempt + 1
        call_messages = list(messages)
        if attempt == 1:
            call_messages = messages + [
                {
                    "role": "user",
                    "content": (
                        "Your previous reply was invalid JSON for the required schema. "
                        f"Error: {last_error}. "
                        "Reply with ONLY valid JSON matching the schema. No markdown."
                    ),
                }
            ]

        try:
            result = provider.complete(
                call_messages,
                model=settings.model_name,
                timeout=settings.model_timeout_seconds,
            )
        except GenerationTimeoutError:
            record_judge(
                judge_type=judge_type,
                ok=False,
                timeout=True,
                latency_ms=round(total_latency, 2),
            )
            raise
        total_latency += result.latency_ms
        raw_outputs.append(result.content)

        try:
            data = _extract_json(result.content)
            parsed = schema.model_validate(data)
            meta = {
                "judge_type": judge_type,
                "attempts": attempts,
                "latency_ms": round(total_latency, 2),
                "schema_ok": True,
                "model": result.model,
                "temperature": GENERATION_TEMPERATURE,
                "raw": result.content[:2000],
            }
            logger.info(
                "judge_ok",
                judge_type=judge_type,
                attempts=attempts,
                latency_ms=meta["latency_ms"],
                operation="judge",
            )
            record_judge(
                judge_type=judge_type,
                ok=True,
                latency_ms=meta["latency_ms"],
            )
            return parsed, meta
        except (json.JSONDecodeError, ValidationError, TypeError, ValueError) as exc:
            last_error = str(exc)
            logger.warning(
                "judge_schema_invalid",
                judge_type=judge_type,
                attempt=attempts,
                error=last_error,
                operation="judge",
            )

    record_judge(
        judge_type=judge_type,
        ok=False,
        malformed=True,
        latency_ms=round(total_latency, 2),
    )
    raise JudgeMalformedError(judge_type, last_error)
