"""Generation service — call the configured LLM with a grounded prompt."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Sequence

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.services.llm_client import (
    GENERATION_TEMPERATURE,
    LLMResult,
    get_llm_provider,
)
from app.services.prompts import PROMPT_VERSION, build_chat_messages

logger = get_logger(__name__)


def _strip_bold_markers(text: str) -> str:
    """Remove literal Markdown bold markers only; leave all other characters intact."""
    return text.replace("**", "")


def generate_answer(
    *,
    query: str,
    retrieved_chunks: Sequence[dict[str, Any]],
    settings: Settings | None = None,
) -> LLMResult:
    """Generate an answer from query + retrieved chunks. Temperature is always 0."""
    settings = settings or get_settings()
    messages = build_chat_messages(query, retrieved_chunks)
    provider = get_llm_provider(settings)

    logger.info(
        "generation_started",
        model=settings.model_name,
        prompt_version=PROMPT_VERSION,
        temperature=GENERATION_TEMPERATURE,
        chunk_count=len(retrieved_chunks),
    )

    result = provider.complete(
        messages,
        model=settings.model_name,
        timeout=settings.model_timeout_seconds,
    )
    result = replace(result, content=_strip_bold_markers(result.content))

    logger.info(
        "generation_completed",
        model=result.model,
        latency_ms=result.latency_ms,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
    )
    return result
