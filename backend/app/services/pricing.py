"""Per-model token pricing -> estimated USD cost per execution (v1.0).

Pricing lives in configs/pricing.yaml (override with PRICING_PATH). Values are
illustrative; estimates are for relative comparison, not billing.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import yaml

from app.core.logging import get_logger

logger = get_logger(__name__)

_FALLBACK: dict[str, Any] = {
    "version": "pricing.builtin-zero",
    "currency": "USD",
    "unit": "per_1m_tokens",
    "default": {"prompt": 0.0, "completion": 0.0},
    "models": {},
}

_lock = threading.Lock()
_cache: dict[str, dict[str, Any]] = {}


def default_pricing_path() -> Path:
    return Path(__file__).resolve().parents[2] / "configs" / "pricing.yaml"


def _resolve_path(path: str | Path | None) -> Path:
    if path:
        return Path(path)
    try:
        from app.core.config import get_settings

        configured = get_settings().pricing_path
    except Exception:  # noqa: BLE001
        configured = None
    return Path(configured) if configured else default_pricing_path()


def _normalise(raw: dict[str, Any], source: str) -> dict[str, Any]:
    default = raw.get("default") or {}
    models: dict[str, dict[str, float]] = {}
    for name, cfg in (raw.get("models") or {}).items():
        if not isinstance(cfg, dict):
            continue
        models[str(name)] = {
            "prompt": float(cfg.get("prompt", 0.0) or 0.0),
            "completion": float(cfg.get("completion", 0.0) or 0.0),
        }
    return {
        "version": str(raw.get("version") or "pricing.unversioned"),
        "currency": str(raw.get("currency") or "USD"),
        "unit": str(raw.get("unit") or "per_1m_tokens"),
        "default": {
            "prompt": float(default.get("prompt", 0.0) or 0.0),
            "completion": float(default.get("completion", 0.0) or 0.0),
        },
        "models": models,
        "_source_path": source,
    }


def load_pricing(path: str | Path | None = None) -> dict[str, Any]:
    """Load + cache the pricing table. Missing/invalid file -> zero-cost fallback."""
    resolved = _resolve_path(path)
    key = str(resolved)
    with _lock:
        cached = _cache.get(key)
    if cached is not None:
        return cached
    if not resolved.is_file():
        logger.warning("pricing_file_missing", path=key)
        table = dict(_FALLBACK, _source_path=key)
    else:
        try:
            raw = yaml.safe_load(resolved.read_text(encoding="utf-8")) or {}
            table = _normalise(raw, key)
        except Exception as exc:  # noqa: BLE001
            logger.warning("pricing_file_invalid", path=key, error=str(exc))
            table = dict(_FALLBACK, _source_path=key)
    with _lock:
        _cache[key] = table
    return table


def reset_pricing_cache() -> None:
    with _lock:
        _cache.clear()


def pricing_version(path: str | Path | None = None) -> str:
    return str(load_pricing(path)["version"])


def resolve_model_pricing(
    model: str | None, table: dict[str, Any] | None = None
) -> tuple[str, dict[str, float]]:
    """Return (matched_key, {prompt, completion}): exact, longest prefix, default."""
    table = table or load_pricing()
    models: dict[str, dict[str, float]] = table.get("models") or {}
    if model:
        if model in models:
            return model, models[model]
        best = ""
        for key in models:
            if model.startswith(key) and len(key) > len(best):
                best = key
        if best:
            return best, models[best]
    return "default", table["default"]


def estimate_cost_usd(
    model: str | None,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    *,
    path: str | Path | None = None,
) -> float | None:
    """Estimated USD cost; None when token counts are unknown."""
    if prompt_tokens is None and completion_tokens is None:
        return None
    _, rates = resolve_model_pricing(model, load_pricing(path))
    cost = (
        (prompt_tokens or 0) * rates["prompt"]
        + (completion_tokens or 0) * rates["completion"]
    ) / 1_000_000.0
    return round(cost, 8)
