"""Thin operational metric helpers used by pipeline stages."""

from __future__ import annotations

from app.core.metrics import get_metrics


def record_retrieval(*, empty: bool, latency_ms: float | None) -> None:
    m = get_metrics()
    m.inc("retrieval.attempts")
    if empty:
        m.inc("retrieval.empty")
    if latency_ms is not None:
        m.observe("retrieval", latency_ms)


def record_generation(
    *,
    status: str,
    latency_ms: float | None,
    tokens: int | None = None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    cost_usd: float | None = None,
) -> None:
    """Record one generation attempt.

    Counters: generation.attempts/success/failures/timeout, token usage
    (generation.prompt_tokens / completion_tokens / tokens_total) and cost as
    integer micro-dollars (generation.cost_usd_micros) so it stays additive
    across processes and time windows.
    """
    m = get_metrics()
    m.inc("generation.attempts")
    if status == "GENERATION_TIMEOUT":
        m.inc("generation.timeout")
        m.inc("generation.failures")
    elif status == "FAILED":
        m.inc("generation.failures")
    else:
        m.inc("generation.success")
    if latency_ms is not None:
        m.observe("generation", latency_ms)
    if tokens is None and (prompt_tokens is not None or completion_tokens is not None):
        tokens = int(prompt_tokens or 0) + int(completion_tokens or 0)
    if tokens is not None:
        m.inc("generation.tokens_total", int(tokens))
    if prompt_tokens is not None:
        m.inc("generation.prompt_tokens", int(prompt_tokens))
    if completion_tokens is not None:
        m.inc("generation.completion_tokens", int(completion_tokens))
    if cost_usd is not None:
        m.inc("generation.cost_usd_micros", int(round(float(cost_usd) * 1_000_000)))


def record_judge(
    *,
    judge_type: str,
    ok: bool,
    malformed: bool = False,
    timeout: bool = False,
    latency_ms: float | None = None,
) -> None:
    m = get_metrics()
    m.inc("judge.attempts")
    m.inc(f"judge.type.{judge_type}")
    if timeout:
        m.inc("judge.timeout")
    elif malformed:
        m.inc("judge.malformed")
    elif ok:
        m.inc("judge.success")
    if latency_ms is not None:
        m.observe("judge", latency_ms)
        m.observe(f"judge.{judge_type}", latency_ms)


def record_diagnosis(
    *,
    failure_code: str,
    rule_id: str,
    layer: str,
    latency_ms: float | None = None,
) -> None:
    m = get_metrics()
    m.inc("diagnosis.total")
    m.inc(f"diagnosis.code.{failure_code}")
    m.inc(f"diagnosis.rule.{rule_id}")
    m.inc(f"diagnosis.layer.{layer}")
    if latency_ms is not None:
        m.observe("diagnosis", latency_ms)
