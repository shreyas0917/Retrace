"""Operational signal evaluation from metrics + YAML thresholds."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from app.core.metrics import get_metrics


DEFAULT_SIGNALS: dict[str, Any] = {
    "version": "observability_signals.v1",
    "signals": {
        "retrieval_miss_rate": {"enabled": True, "threshold": 0.10},
        "retrieval_empty_rate": {"enabled": True, "threshold": 0.15},
        "judge_timeout_rate": {"enabled": True, "threshold": 0.05},
        "judge_malformed_rate": {"enabled": True, "threshold": 0.05},
        "generation_timeout_rate": {"enabled": True, "threshold": 0.05},
        "request_error_rate": {"enabled": True, "threshold": 0.05},
        "p95_latency_ms": {"enabled": True, "threshold": 2000},
    },
}


def default_observability_path() -> Path:
    here = Path(__file__).resolve()
    return here.parents[2] / "configs" / "observability.default.yaml"


def load_observability_config(path: str | Path | None = None) -> dict[str, Any]:
    path = Path(path) if path else default_observability_path()
    if not path.is_file():
        return dict(DEFAULT_SIGNALS)
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    merged = dict(DEFAULT_SIGNALS)
    merged.update({k: v for k, v in raw.items() if k != "signals"})
    signals = dict(DEFAULT_SIGNALS["signals"])
    if isinstance(raw.get("signals"), dict):
        for name, cfg in raw["signals"].items():
            base = dict(signals.get(name, {}))
            if isinstance(cfg, dict):
                base.update(cfg)
            signals[name] = base
    merged["signals"] = signals
    merged["_source_path"] = str(path)
    return merged


def evaluate_signals(
    snapshot: dict[str, Any] | None = None,
    config: dict[str, Any] | None = None,
    *,
    source: str = "memory",
    window_minutes: int | None = None,
) -> dict[str, Any]:
    """Return signal rows with actual/threshold/status (OK|ALERT|INSUFFICIENT_DATA).

    source="memory" (default) evaluates the in-process snapshot; source="durable"
    uses the Postgres-backed window (falls back to memory when unavailable). The
    result reports which one was used in `metrics_source`.
    """
    config = config or load_observability_config()
    metrics_source = "in-memory"
    if snapshot is None:
        if source == "durable":
            from app.core.telemetry import try_durable_snapshot

            durable = try_durable_snapshot(window_minutes)
            if durable.get("available"):
                snapshot = durable
                metrics_source = "postgres"
            else:
                snapshot = get_metrics().snapshot()
                snapshot = dict(snapshot)
                snapshot["note"] = (
                    f"{snapshot.get('note') or ''} Durable store unavailable: "
                    f"{durable.get('reason')}"
                ).strip()
        else:
            snapshot = get_metrics().snapshot()
    elif snapshot.get("source") == "postgres":
        metrics_source = "postgres"
    derived = snapshot.get("derived") or {}
    latencies = snapshot.get("latencies") or {}
    http_lat = latencies.get("http.request") or {}

    values: dict[str, float | None] = {
        "retrieval_miss_rate": derived.get("retrieval_miss_rate"),
        "retrieval_empty_rate": derived.get("retrieval_empty_rate"),
        "judge_timeout_rate": derived.get("judge_timeout_rate"),
        "judge_malformed_rate": derived.get("judge_malformed_rate"),
        "generation_timeout_rate": derived.get("generation_timeout_rate"),
        "request_error_rate": derived.get("request_error_rate"),
        "p95_latency_ms": http_lat.get("p95_ms"),
    }

    rows: list[dict[str, Any]] = []
    alerts = 0
    for name, cfg in (config.get("signals") or {}).items():
        if not cfg.get("enabled", True):
            continue
        threshold = float(cfg.get("threshold", 0))
        actual = values.get(name)
        if actual is None:
            status = "INSUFFICIENT_DATA"
        elif name == "p95_latency_ms":
            status = "ALERT" if actual > threshold else "OK"
        else:
            status = "ALERT" if actual >= threshold else "OK"
        if status == "ALERT":
            alerts += 1
        rows.append(
            {
                "signal": name,
                "actual": actual,
                "threshold": threshold,
                "status": status,
                "description": cfg.get("description"),
            }
        )

    return {
        "version": config.get("version"),
        "alert_count": alerts,
        "signals": rows,
        "metrics_source": metrics_source,
        "window_minutes": snapshot.get("window_minutes"),
        "metrics_note": snapshot.get("note"),
    }
