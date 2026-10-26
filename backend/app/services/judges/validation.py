"""Judge validation against human-labeled examples.

Answers the question "can the LLM judges be trusted?" with measurements:

* per judge, per prompt variant: accuracy / precision / recall / F1 and Cohen's
  kappa for the binary labels, MAE between predicted and labeled scores,
  schema-failure rate and mean latency;
* inter-judge consistency: logically incompatible verdicts across the three
  judges on the same example (e.g. ``contradicts=true`` but
  ``faithfulness_score == 1.0``);
* prompt sensitivity: label flip rate and kappa between meaning-preserving
  prompt variants (see ``prompt_variants.py``).

The report pins the model name, temperature, prompt versions and sha256 of
every prompt actually sent, the example-set hash and a timestamp.
"""

from __future__ import annotations

import json
import time
from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, model_validator

from app.core.config import Settings, get_settings
from app.core.errors import GenerationError, GenerationTimeoutError
from app.core.logging import get_logger
from app.services import llm_client
from app.services.eval.suite_loader import compute_suite_hash
from app.services.judges.base import JudgeMalformedError, run_structured_judge
from app.services.judges.contradiction import build_contradiction_messages
from app.services.judges.faithfulness import build_faithfulness_messages
from app.services.judges.prompt_variants import (
    JUDGE_TYPES,
    PRODUCTION_VARIANT,
    describe_variants,
    get_system_prompt,
    prompt_version,
)
from app.services.judges.relevance import build_relevance_messages
from app.services.judges.schemas import (
    ContradictionJudgeResult,
    FaithfulnessJudgeResult,
    RelevanceJudgeResult,
)
from app.services.llm_client import GENERATION_TEMPERATURE, LLMProvider

logger = get_logger(__name__)

JudgeType = Literal["relevance", "faithfulness", "contradiction"]
FAITHFUL_THRESHOLD = 0.999  # predicted score >= this counts as "no unsupported claim"


# --------------------------------------------------------------------------- #
# Labeled example schema
# --------------------------------------------------------------------------- #


class LabeledChunk(BaseModel):
    chunk_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    relevant: bool | None = None
    score: float | None = Field(default=None, ge=0.0, le=1.0)

    @property
    def label_score(self) -> float:
        if self.score is not None:
            return self.score
        return 1.0 if self.relevant else 0.0


class LabeledClaim(BaseModel):
    claim: str = Field(min_length=1)
    supported: bool


class JudgeExample(BaseModel):
    example_id: str = Field(min_length=1)
    judge: JudgeType
    query: str = Field(min_length=1)
    chunks: list[LabeledChunk] = Field(min_length=1)
    context_sufficient: bool | None = None
    answer: str | None = None
    claims: list[LabeledClaim] | None = None
    faithfulness_band: list[float] | None = None
    contradicts: bool | None = None
    tags: list[str] = Field(default_factory=list)
    notes: str = ""
    annotator: str = Field(min_length=1)
    annotation_date: str = Field(min_length=8)

    @model_validator(mode="after")
    def _check_labels_for_judge(self) -> "JudgeExample":
        if self.judge == "relevance":
            if self.context_sufficient is None:
                raise ValueError("relevance examples need context_sufficient")
            if any(c.relevant is None for c in self.chunks):
                raise ValueError("relevance examples need a relevant label on every chunk")
            if len(self.chunks) < 2:
                raise ValueError("relevance examples need at least 2 chunks")
        elif self.judge == "faithfulness":
            if not self.answer or not self.claims:
                raise ValueError("faithfulness examples need answer and claims")
            if self.faithfulness_band is None or len(self.faithfulness_band) != 2:
                raise ValueError("faithfulness examples need faithfulness_band [lo, hi]")
            lo, hi = self.faithfulness_band
            if not (0.0 <= lo <= hi <= 1.0):
                raise ValueError("faithfulness_band must satisfy 0 <= lo <= hi <= 1")
            if not (lo - 1e-9 <= self.labeled_faithfulness_score <= hi + 1e-9):
                raise ValueError(
                    "faithfulness_band must contain the fraction of supported claims "
                    f"({self.labeled_faithfulness_score:.3f})"
                )
        elif self.judge == "contradiction":
            if not self.answer or self.contradicts is None:
                raise ValueError("contradiction examples need answer and contradicts")
        return self

    @property
    def labeled_faithfulness_score(self) -> float:
        if not self.claims:
            return 0.0
        return sum(1 for c in self.claims if c.supported) / len(self.claims)

    @property
    def labeled_has_unsupported(self) -> bool:
        return any(not c.supported for c in (self.claims or []))

    def chunk_dicts(self) -> list[dict[str, Any]]:
        return [{"chunk_id": c.chunk_id, "text": c.text} for c in self.chunks]


class JudgeLabelsValidationError(ValueError):
    pass


def default_labels_path() -> Path:
    here = Path(__file__).resolve()
    return here.parents[3] / "datasets" / "judges" / "judge_labels_v1.jsonl"


def load_judge_labels(path: str | Path) -> tuple[list[JudgeExample], str]:
    """Load + validate the labeled examples. Returns (examples, file hash)."""
    path = Path(path)
    if not path.is_file():
        raise JudgeLabelsValidationError(f"labels file not found: {path}")
    raw_lines = path.read_text(encoding="utf-8").splitlines()
    examples: list[JudgeExample] = []
    seen: set[str] = set()
    for lineno, line in enumerate(raw_lines, start=1):
        if not line.strip():
            continue
        try:
            ex = JudgeExample.model_validate_json(line)
        except Exception as exc:  # noqa: BLE001
            raise JudgeLabelsValidationError(f"{path}:{lineno}: {exc}") from exc
        if ex.example_id in seen:
            raise JudgeLabelsValidationError(f"{path}:{lineno}: duplicate example_id {ex.example_id}")
        seen.add(ex.example_id)
        examples.append(ex)
    if not examples:
        raise JudgeLabelsValidationError(f"labels file is empty: {path}")
    return examples, compute_suite_hash(raw_lines)


def compute_examples_hash(examples: Sequence[JudgeExample]) -> str:
    lines = [json.dumps(ex.model_dump(mode="json"), sort_keys=True) for ex in examples]
    return compute_suite_hash(lines)


def select_examples(examples: Sequence[JudgeExample], limit: int | None) -> list[JudgeExample]:
    """Interleave judges so a ``--limit`` still covers all three judge types."""
    if limit is None or limit >= len(examples):
        return list(examples)
    buckets: dict[str, list[JudgeExample]] = defaultdict(list)
    for ex in examples:
        buckets[ex.judge].append(ex)
    out: list[JudgeExample] = []
    i = 0
    while len(out) < limit and any(i < len(b) for b in buckets.values()):
        for judge in JUDGE_TYPES:
            bucket = buckets.get(judge, [])
            if i < len(bucket) and len(out) < limit:
                out.append(bucket[i])
        i += 1
    return out


# --------------------------------------------------------------------------- #
# Agreement statistics
# --------------------------------------------------------------------------- #


def cohen_kappa(a: Sequence[bool], b: Sequence[bool]) -> float | None:
    """Cohen's kappa for two binary label sequences; None when empty."""
    if len(a) != len(b):
        raise ValueError("sequences must have equal length")
    n = len(a)
    if n == 0:
        return None
    po = sum(1 for x, y in zip(a, b) if x == y) / n
    pa_true = sum(1 for x in a if x) / n
    pb_true = sum(1 for y in b if y) / n
    pe = pa_true * pb_true + (1 - pa_true) * (1 - pb_true)
    if pe >= 1.0 - 1e-12:
        # Both raters constant: perfect agreement if identical, else undefined -> 0.
        return 1.0 if po >= 1.0 - 1e-12 else 0.0
    return (po - pe) / (1 - pe)


def binary_metrics(y_true: Sequence[bool], y_pred: Sequence[bool]) -> dict[str, Any]:
    if len(y_true) != len(y_pred):
        raise ValueError("sequences must have equal length")
    tp = sum(1 for t, p in zip(y_true, y_pred) if t and p)
    fp = sum(1 for t, p in zip(y_true, y_pred) if not t and p)
    fn = sum(1 for t, p in zip(y_true, y_pred) if t and not p)
    tn = sum(1 for t, p in zip(y_true, y_pred) if not t and not p)
    n = len(y_true)
    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision is not None and recall is not None and (precision + recall) > 0
        else (0.0 if (tp + fp + fn) else None)
    )
    return {
        "n": n,
        "accuracy": (tp + tn) / n if n else None,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "kappa": cohen_kappa(list(y_true), list(y_pred)),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
    }


def _mean(values: Iterable[float]) -> float | None:
    vals = [float(v) for v in values]
    return (sum(vals) / len(vals)) if vals else None


def _round(obj: Any, digits: int = 4) -> Any:
    if isinstance(obj, float):
        return round(obj, digits)
    if isinstance(obj, dict):
        return {k: _round(v, digits) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_round(v, digits) for v in obj]
    return obj


# --------------------------------------------------------------------------- #
# Running one judge with a prompt variant
# --------------------------------------------------------------------------- #

_SCHEMAS = {
    "relevance": RelevanceJudgeResult,
    "faithfulness": FaithfulnessJudgeResult,
    "contradiction": ContradictionJudgeResult,
}


def build_messages(judge_type: str, example: JudgeExample, variant: str) -> list[dict[str, str]]:
    """Production user-message formatting with the variant's system prompt swapped in."""
    chunks = example.chunk_dicts()
    if judge_type == "relevance":
        messages = build_relevance_messages(example.query, chunks)
    elif judge_type == "faithfulness":
        messages = build_faithfulness_messages(example.query, example.answer or "", chunks)
    elif judge_type == "contradiction":
        messages = build_contradiction_messages(example.query, example.answer or "", chunks)
    else:
        raise ValueError(f"unknown judge type {judge_type}")
    messages[0] = {"role": "system", "content": get_system_prompt(judge_type, variant)}
    return messages


def run_judge_on_example(
    judge_type: str, example: JudgeExample, variant: str, settings: Settings
) -> dict[str, Any]:
    """Returns a prediction record; never raises for model/schema failures."""
    messages = build_messages(judge_type, example, variant)
    record: dict[str, Any] = {
        "example_id": example.example_id,
        "judge": judge_type,
        "variant": variant,
        "prompt_version": prompt_version(judge_type, variant),
        "schema_ok": False,
        "error": None,
        "latency_ms": None,
        "attempts": None,
    }
    try:
        parsed, meta = run_structured_judge(
            judge_type=judge_type,
            messages=messages,
            schema=_SCHEMAS[judge_type],
            settings=settings,
        )
    except JudgeMalformedError as exc:
        record["error"] = f"malformed: {exc.detail[:200]}"
        return record
    except GenerationTimeoutError as exc:
        record["error"] = f"timeout: {str(exc)[:200]}"
        return record
    except GenerationError as exc:
        record["error"] = f"generation_error: {str(exc)[:200]}"
        return record

    record.update(
        schema_ok=True,
        latency_ms=meta.get("latency_ms"),
        attempts=meta.get("attempts"),
        model=meta.get("model"),
    )
    if judge_type == "relevance":
        assert isinstance(parsed, RelevanceJudgeResult)
        items = {item.chunk_id: item for item in parsed.items}
        known = {c.chunk_id for c in example.chunks}
        record["items"] = {
            cid: {"relevant": items[cid].relevant, "score": items[cid].score}
            for cid in known
            if cid in items
        }
        record["missing_chunk_ids"] = sorted(known - set(items))
        record["unknown_chunk_ids"] = sorted(set(items) - known)
        record["context_sufficient"] = parsed.context_sufficient
    elif judge_type == "faithfulness":
        assert isinstance(parsed, FaithfulnessJudgeResult)
        record["faithfulness_score"] = parsed.faithfulness_score
        record["claims"] = [
            {"claim": c.claim, "supported": c.supported, "supporting_chunk_ids": c.supporting_chunk_ids}
            for c in parsed.claims
        ]
        record["has_unsupported"] = (
            any(not c.supported for c in parsed.claims)
            or parsed.faithfulness_score < FAITHFUL_THRESHOLD
        )
    else:
        assert isinstance(parsed, ContradictionJudgeResult)
        record["contradicts"] = parsed.contradicts
        record["chunk_ids"] = list(parsed.chunk_ids)
        record["explanation"] = parsed.explanation[:300]
    return record


# --------------------------------------------------------------------------- #
# Scoring predictions against labels
# --------------------------------------------------------------------------- #


def _score_relevance(examples: list[JudgeExample], preds: dict[str, dict[str, Any]]) -> dict[str, Any]:
    y_true: list[bool] = []
    y_pred: list[bool] = []
    abs_err: list[float] = []
    suff_true: list[bool] = []
    suff_pred: list[bool] = []
    missing = 0
    for ex in examples:
        rec = preds.get(ex.example_id)
        if not rec or not rec.get("schema_ok"):
            continue
        for chunk in ex.chunks:
            item = rec["items"].get(chunk.chunk_id)
            if item is None:
                # Judge dropped the chunk: counted as "not relevant, score 0" and flagged.
                missing += 1
                item = {"relevant": False, "score": 0.0}
            y_true.append(bool(chunk.relevant))
            y_pred.append(bool(item["relevant"]))
            abs_err.append(abs(float(item["score"]) - chunk.label_score))
        suff_true.append(bool(ex.context_sufficient))
        suff_pred.append(bool(rec["context_sufficient"]))
    return {
        "chunk_relevant": binary_metrics(y_true, y_pred),
        "score_mae": _mean(abs_err),
        "context_sufficient": binary_metrics(suff_true, suff_pred),
        "missing_chunk_items": missing,
    }


def _score_faithfulness(examples: list[JudgeExample], preds: dict[str, dict[str, Any]]) -> dict[str, Any]:
    y_true: list[bool] = []
    y_pred: list[bool] = []
    abs_err: list[float] = []
    in_band: list[bool] = []
    for ex in examples:
        rec = preds.get(ex.example_id)
        if not rec or not rec.get("schema_ok"):
            continue
        y_true.append(ex.labeled_has_unsupported)
        y_pred.append(bool(rec["has_unsupported"]))
        score = float(rec["faithfulness_score"])
        abs_err.append(abs(score - ex.labeled_faithfulness_score))
        lo, hi = ex.faithfulness_band or (0.0, 1.0)
        in_band.append(lo - 1e-9 <= score <= hi + 1e-9)
    return {
        "has_unsupported_claim": binary_metrics(y_true, y_pred),
        "score_mae": _mean(abs_err),
        "score_in_band_rate": _mean(1.0 if b else 0.0 for b in in_band),
    }


def _score_contradiction(examples: list[JudgeExample], preds: dict[str, dict[str, Any]]) -> dict[str, Any]:
    y_true: list[bool] = []
    y_pred: list[bool] = []
    for ex in examples:
        rec = preds.get(ex.example_id)
        if not rec or not rec.get("schema_ok"):
            continue
        y_true.append(bool(ex.contradicts))
        y_pred.append(bool(rec["contradicts"]))
    return {"contradicts": binary_metrics(y_true, y_pred)}


_SCORERS = {
    "relevance": _score_relevance,
    "faithfulness": _score_faithfulness,
    "contradiction": _score_contradiction,
}


def _reliability(records: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(records)
    schema_failures = sum(1 for r in records if r.get("error", "") and str(r["error"]).startswith("malformed"))
    other_errors = sum(1 for r in records if r.get("error") and not str(r["error"]).startswith("malformed"))
    latencies = [float(r["latency_ms"]) for r in records if r.get("latency_ms") is not None]
    retries = sum(1 for r in records if (r.get("attempts") or 1) > 1)
    return {
        "n_calls": n,
        "schema_failure_rate": (schema_failures / n) if n else None,
        "error_rate": (other_errors / n) if n else None,
        "retry_rate": (retries / n) if n else None,
        "mean_latency_ms": _mean(latencies),
        "p95_latency_ms": (sorted(latencies)[int(0.95 * (len(latencies) - 1))] if latencies else None),
    }


# --------------------------------------------------------------------------- #
# Binary "unit" extraction for sensitivity / consistency
# --------------------------------------------------------------------------- #


def _units(judge_type: str, example: JudgeExample, rec: dict[str, Any]) -> dict[str, bool]:
    """Binary decisions keyed by unit name (per chunk for relevance)."""
    if not rec.get("schema_ok"):
        return {}
    if judge_type == "relevance":
        units = {
            f"relevant:{c.chunk_id}": bool(rec["items"].get(c.chunk_id, {}).get("relevant", False))
            for c in example.chunks
        }
        units["context_sufficient"] = bool(rec["context_sufficient"])
        return units
    if judge_type == "faithfulness":
        return {"has_unsupported": bool(rec["has_unsupported"])}
    return {"contradicts": bool(rec["contradicts"])}


def _score_value(judge_type: str, rec: dict[str, Any]) -> dict[str, float]:
    if not rec.get("schema_ok"):
        return {}
    if judge_type == "relevance":
        return {f"score:{cid}": float(item["score"]) for cid, item in rec["items"].items()}
    if judge_type == "faithfulness":
        return {"faithfulness_score": float(rec["faithfulness_score"])}
    return {}


def prompt_sensitivity(
    judge_type: str,
    examples: list[JudgeExample],
    preds_by_variant: dict[str, dict[str, dict[str, Any]]],
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for va, vb in combinations(sorted(preds_by_variant), 2):
        a_vals: list[bool] = []
        b_vals: list[bool] = []
        score_diffs: list[float] = []
        for ex in examples:
            ra = preds_by_variant[va].get(ex.example_id)
            rb = preds_by_variant[vb].get(ex.example_id)
            if not ra or not rb:
                continue
            ua, ub = _units(judge_type, ex, ra), _units(judge_type, ex, rb)
            for key in ua.keys() & ub.keys():
                a_vals.append(ua[key])
                b_vals.append(ub[key])
            sa, sb = _score_value(judge_type, ra), _score_value(judge_type, rb)
            for key in sa.keys() & sb.keys():
                score_diffs.append(abs(sa[key] - sb[key]))
        flips = sum(1 for x, y in zip(a_vals, b_vals) if x != y)
        out[f"{va}|{vb}"] = {
            "n_units": len(a_vals),
            "flip_rate": (flips / len(a_vals)) if a_vals else None,
            "kappa": cohen_kappa(a_vals, b_vals),
            "mean_abs_score_diff": _mean(score_diffs),
        }
    return out


# --------------------------------------------------------------------------- #
# Cross-judge consistency
# --------------------------------------------------------------------------- #

CONSISTENCY_CHECKS = {
    "contradiction_true_but_faithfulness_1": "contradicts=true while faithfulness_score == 1.0",
    "insufficient_context_but_faithfulness_1": "context_sufficient=false yet faithfulness_score == 1.0 with >= 1 claim",
    "faithfulness_score_claims_mismatch": "faithfulness_score differs from supported/total claims by > 0.05",
    "contradiction_without_evidence": "contradicts=true but chunk_ids is empty",
    "relevance_items_missing": "relevance judge omitted or invented chunk ids",
}


def consistency_checks(
    examples: list[JudgeExample],
    preds: dict[str, dict[str, dict[str, Any]]],
) -> dict[str, Any]:
    """``preds[judge][example_id]`` -> record (production variant)."""
    counts = {k: 0 for k in CONSISTENCY_CHECKS}
    flags: list[dict[str, str]] = []
    evaluated_pairs = 0

    def flag(check: str, ex: JudgeExample, detail: str) -> None:
        counts[check] += 1
        flags.append({"check": check, "example_id": ex.example_id, "detail": detail})

    for ex in examples:
        rel = preds.get("relevance", {}).get(ex.example_id)
        fai = preds.get("faithfulness", {}).get(ex.example_id)
        con = preds.get("contradiction", {}).get(ex.example_id)
        if fai and fai.get("schema_ok"):
            claims = fai["claims"]
            if claims:
                frac = sum(1 for c in claims if c["supported"]) / len(claims)
                if abs(frac - float(fai["faithfulness_score"])) > 0.05:
                    flag(
                        "faithfulness_score_claims_mismatch",
                        ex,
                        f"score={fai['faithfulness_score']:.2f} supported_fraction={frac:.2f}",
                    )
        if con and con.get("schema_ok") and con["contradicts"] and not con["chunk_ids"]:
            flag("contradiction_without_evidence", ex, "contradicts=true with no chunk_ids")
        if rel and rel.get("schema_ok") and (rel["missing_chunk_ids"] or rel["unknown_chunk_ids"]):
            flag(
                "relevance_items_missing",
                ex,
                f"missing={rel['missing_chunk_ids']} unknown={rel['unknown_chunk_ids']}",
            )
        if fai and fai.get("schema_ok") and con and con.get("schema_ok"):
            evaluated_pairs += 1
            if con["contradicts"] and float(fai["faithfulness_score"]) >= FAITHFUL_THRESHOLD:
                flag("contradiction_true_but_faithfulness_1", ex, "")
        if fai and fai.get("schema_ok") and rel and rel.get("schema_ok"):
            if (
                not rel["context_sufficient"]
                and float(fai["faithfulness_score"]) >= FAITHFUL_THRESHOLD
                and fai["claims"]
            ):
                flag("insufficient_context_but_faithfulness_1", ex, "")
    return {
        "descriptions": CONSISTENCY_CHECKS,
        "counts": counts,
        "examples_with_faithfulness_and_contradiction": evaluated_pairs,
        "flags": flags,
    }


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #


def _redact_base_url(url: str) -> str:
    try:
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    except Exception:  # noqa: BLE001
        return "<unparseable>"


def validate_judges(
    provider: LLMProvider,
    examples: Sequence[JudgeExample],
    prompt_variant: str = PRODUCTION_VARIANT,
    *,
    variants: Sequence[str] | None = None,
    settings: Settings | None = None,
    include_consistency: bool = True,
    progress: Any | None = None,
) -> dict[str, Any]:
    """Run every example through its judge (for each variant) and score it.

    ``prompt_variant`` is the primary variant (used for the headline metrics and
    the cross-judge consistency run); ``variants`` adds further variants for the
    sensitivity analysis. ``provider`` is installed via ``set_llm_provider`` for
    the duration of the run and the previous provider is restored afterwards.
    """
    settings = settings or get_settings()
    examples = list(examples)
    variant_list = [prompt_variant] + [v for v in (variants or []) if v != prompt_variant]
    started = time.perf_counter()

    previous = llm_client._override_provider  # noqa: SLF001
    llm_client.set_llm_provider(provider)
    try:
        by_judge: dict[str, list[JudgeExample]] = defaultdict(list)
        for ex in examples:
            by_judge[ex.judge].append(ex)

        # preds[judge][variant][example_id] -> record (judge == example.judge)
        preds: dict[str, dict[str, dict[str, dict[str, Any]]]] = defaultdict(lambda: defaultdict(dict))
        all_records: list[dict[str, Any]] = []
        total_calls = len(examples) * len(variant_list)
        done = 0
        for variant in variant_list:
            for ex in examples:
                rec = run_judge_on_example(ex.judge, ex, variant, settings)
                preds[ex.judge][variant][ex.example_id] = rec
                all_records.append(rec)
                done += 1
                if progress:
                    progress(done, total_calls, f"{ex.judge}:{variant}:{ex.example_id}")

        # Cross-judge consistency: production variant, other judges on the same inputs.
        cross: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
        cross_records: list[dict[str, Any]] = []
        consistency: dict[str, Any] | None = None
        if include_consistency:
            for ex in examples:
                cross[ex.judge][ex.example_id] = preds[ex.judge][prompt_variant][ex.example_id]
                if ex.answer:
                    others = [j for j in ("faithfulness", "contradiction", "relevance") if j != ex.judge]
                    for other in others:
                        rec = run_judge_on_example(other, ex, prompt_variant, settings)
                        rec["purpose"] = "consistency"
                        cross[other][ex.example_id] = rec
                        cross_records.append(rec)
                        if progress:
                            progress(done, total_calls, f"consistency:{other}:{ex.example_id}")
            consistency = consistency_checks(examples, cross)

        per_judge: dict[str, Any] = {}
        sensitivity: dict[str, Any] = {}
        for judge in JUDGE_TYPES:
            judge_examples = by_judge.get(judge, [])
            if not judge_examples:
                continue
            per_judge[judge] = {}
            for variant in variant_list:
                records = [preds[judge][variant][ex.example_id] for ex in judge_examples]
                per_judge[judge][variant] = _round(
                    {
                        "n_examples": len(judge_examples),
                        "prompt_version": prompt_version(judge, variant),
                        **_SCORERS[judge](judge_examples, preds[judge][variant]),
                        "reliability": _reliability(records),
                    }
                )
            if len(variant_list) > 1:
                sensitivity[judge] = _round(
                    prompt_sensitivity(judge, judge_examples, preds[judge])
                )

        report = {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "model": {
                "name": settings.model_name,
                "temperature": GENERATION_TEMPERATURE,
                "base_url": _redact_base_url(settings.model_base_url),
                "provider": type(provider).__name__,
            },
            "prompts": describe_variants(variant_list),
            "primary_variant": prompt_variant,
            "variants": variant_list,
            "examples": {
                "n": len(examples),
                "per_judge": {j: len(by_judge.get(j, [])) for j in JUDGE_TYPES},
                "example_set_hash": compute_examples_hash(examples),
            },
            "per_judge": per_judge,
            "consistency": _round(consistency) if consistency else None,
            "sensitivity": sensitivity,
            "reliability_all_calls": _round(_reliability(all_records + cross_records)),
            "predictions": _round(all_records + cross_records),
            "elapsed_seconds": round(time.perf_counter() - started, 2),
        }
        logger.info(
            "judge_validation_completed",
            examples=len(examples),
            variants=variant_list,
            calls=len(all_records) + len(cross_records),
            elapsed_seconds=report["elapsed_seconds"],
        )
        return report
    finally:
        llm_client.set_llm_provider(previous)


# --------------------------------------------------------------------------- #
# Markdown rendering
# --------------------------------------------------------------------------- #


def _f(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def format_markdown(report: dict[str, Any], *, source_label: str, notes: str = "") -> str:
    """Render the validation report. ``source_label`` must say live model vs fixture."""
    lines: list[str] = []
    m = report["model"]
    lines.append("# Judge validation against labeled examples")
    lines.append("")
    lines.append(f"**Source of these numbers: {source_label}.**")
    lines.append("")
    lines.append(
        f"Generated {report['generated_at']} by `retrace judges validate` "
        f"(elapsed {report['elapsed_seconds']}s). Model `{m['name']}` at `{m['base_url']}`, "
        f"temperature {m['temperature']}, provider class `{m['provider']}`."
    )
    if notes:
        lines.append("")
        lines.append(notes)
    lines.append("")
    ex = report["examples"]
    lines.append("## Labeled example set")
    lines.append("")
    lines.append(
        f"- {ex['n']} examples (" + ", ".join(f"{j}: {n}" for j, n in ex["per_judge"].items()) + ")."
    )
    lines.append(f"- Example-set hash: `{ex['example_set_hash']}`" + (f"; labels file hash: `{report['labels_file_hash']}`" if report.get("labels_file_hash") else "") + ".")
    lines.append("")
    lines.append("## Prompt versions")
    lines.append("")
    lines.append("| judge | variant | prompt_version | sha256 |")
    lines.append("|---|---|---|---|")
    for judge, variants in report["prompts"].items():
        for variant, info in variants.items():
            lines.append(f"| {judge} | {variant} | {info['prompt_version']} | `{info['sha256'][:23]}...` |")
    lines.append("")
    lines.append("## Accuracy vs labels (per judge, per prompt variant)")
    lines.append("")
    lines.append(
        "| judge | variant | n | metric | acc | prec | rec | F1 | kappa | score MAE | schema fail | mean ms |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for judge, variants in report["per_judge"].items():
        for variant, r in variants.items():
            rel = r["reliability"]
            if judge == "relevance":
                blocks = [("chunk relevant", r["chunk_relevant"], r["score_mae"]), ("context_sufficient", r["context_sufficient"], None)]
            elif judge == "faithfulness":
                blocks = [("has unsupported claim", r["has_unsupported_claim"], r["score_mae"])]
            else:
                blocks = [("contradicts", r["contradicts"], None)]
            for name, b, mae in blocks:
                lines.append(
                    f"| {judge} | {variant} | {b['n']} | {name} | {_f(b['accuracy'])} | {_f(b['precision'])} | "
                    f"{_f(b['recall'])} | {_f(b['f1'])} | {_f(b['kappa'])} | {_f(mae)} | "
                    f"{_f(rel['schema_failure_rate'])} | {_f(rel['mean_latency_ms'])} |"
                )
            if judge == "faithfulness":
                lines.append(
                    f"| {judge} | {variant} | {r['has_unsupported_claim']['n']} | score within labeled band | "
                    f"{_f(r['score_in_band_rate'])} | | | | | | | |"
                )
    lines.append("")
    if report.get("sensitivity"):
        lines.append("## Prompt sensitivity (meaning-preserving rewordings)")
        lines.append("")
        lines.append("| judge | variants | units | flip rate | kappa | mean abs score diff |")
        lines.append("|---|---|---|---|---|---|")
        for judge, pairs in report["sensitivity"].items():
            for pair, s in pairs.items():
                lines.append(
                    f"| {judge} | {pair} | {s['n_units']} | {_f(s['flip_rate'])} | {_f(s['kappa'])} | {_f(s['mean_abs_score_diff'])} |"
                )
        lines.append("")
    if report.get("consistency"):
        c = report["consistency"]
        lines.append("## Inter-judge consistency (production prompts)")
        lines.append("")
        lines.append(
            f"Faithfulness and contradiction were both run on {c['examples_with_faithfulness_and_contradiction']} examples that carry an answer."
        )
        lines.append("")
        lines.append("| check | count | meaning |")
        lines.append("|---|---|---|")
        for check, count in c["counts"].items():
            lines.append(f"| {check} | {count} | {c['descriptions'][check]} |")
        if c["flags"]:
            lines.append("")
            lines.append("Flagged examples: " + "; ".join(f"{f['example_id']} ({f['check']})" for f in c["flags"][:30]))
        lines.append("")
    rel = report["reliability_all_calls"]
    lines.append("## Reliability over all calls")
    lines.append("")
    lines.append(
        f"- {rel['n_calls']} judge calls; schema-failure rate {_f(rel['schema_failure_rate'])}, "
        f"other error rate {_f(rel['error_rate'])}, retry rate {_f(rel['retry_rate'])}, "
        f"mean latency {_f(rel['mean_latency_ms'])} ms, p95 {_f(rel['p95_latency_ms'])} ms."
    )
    lines.append("")
    return "\n".join(lines)
