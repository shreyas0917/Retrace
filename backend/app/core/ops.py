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


def record_generation(*, status: str, latency_ms: float | None, tokens: int | None = None) -> None:
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
    if tokens is not None:
        m.inc("generation.tokens_total", int(tokens))


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
