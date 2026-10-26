"""Alternative diagnosis classifiers for head-to-head comparison.

The deterministic rule engine stays the production reference. These
classifiers consume the same `SignalBag` and exist so the benchmark can
report how the rule engine compares against trivial baselines and an
LLM-based classifier on identical inputs.
"""

from __future__ import annotations

import json
import re
import time
from collections import Counter
from dataclasses import dataclass, fields
from typing import Any, Iterable, Protocol

from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.core.logging import get_logger
from app.services.diagnosis.models import SignalBag
from app.services.diagnosis.rules import apply_rules
from app.services.diagnosis.taxonomy import FAILURE_CODES
from app.services.llm_client import get_llm_provider

logger = get_logger(__name__)

CLASSIFIER_PROMPT_VERSION = "classifier.v2"


@dataclass
class Prediction:
    code: str
    score: float
    rule_id: str | None = None
    rationale: str | None = None
    latency_ms: float | None = None
    malformed: bool = False


class Classifier(Protocol):
    name: str

    def predict(self, signals: SignalBag) -> Prediction: ...


_SIGNAL_FIELDS = {f.name for f in fields(SignalBag)}


def signal_bag_from_dict(data: dict[str, Any]) -> SignalBag:
    """Rebuild a SignalBag from the dict persisted in Diagnosis.signals."""
    kwargs = {k: v for k, v in (data or {}).items() if k in _SIGNAL_FIELDS}
    kwargs.setdefault("retrieved_ids", [])
    kwargs.setdefault("gold_ids", [])
    kwargs.setdefault("chunk_relevance", [])
    return SignalBag(**kwargs)


class RuleEngineClassifier:
    name = "rule_engine"

    def predict(self, signals: SignalBag) -> Prediction:
        started = time.perf_counter()
        decision = apply_rules(signals)
        return Prediction(
            code=decision.primary_code,
            score=float(decision.diagnosis_score),
            rule_id=decision.rule_id,
            latency_ms=round((time.perf_counter() - started) * 1000, 3),
        )


class MajorityClassifier:
    """Predicts the most frequent label seen during fit (chance-level baseline)."""

    name = "majority"

    def __init__(self, labels: Iterable[str] | None = None) -> None:
        self.label = "OK_GROUNDED"
        self.distribution: dict[str, int] = {}
        if labels is not None:
            self.fit(labels)

    def fit(self, labels: Iterable[str]) -> "MajorityClassifier":
        counts = Counter(str(x) for x in labels)
        self.distribution = dict(counts)
        if counts:
            self.label = counts.most_common(1)[0][0]
        return self

    def predict(self, signals: SignalBag) -> Prediction:
        total = sum(self.distribution.values()) or 1
        return Prediction(code=self.label, score=self.distribution.get(self.label, 0) / total)


class HeuristicClassifier:
    """Four-branch baseline using only cheap, non-judge signals."""

    name = "heuristic"

    def predict(self, signals: SignalBag) -> Prediction:
        if signals.stage_error == "TIMEOUT":
            return Prediction("EVAL_MODEL_TIMEOUT", 1.0)
        if not signals.judge_schema_ok:
            return Prediction("EVAL_JUDGE_MALFORMED", 1.0)
        if signals.n_retrieved == 0:
            return Prediction("RETRIEVAL_EMPTY", 1.0)
        if signals.gold_ids and signals.gold_hit is False:
            return Prediction("RETRIEVAL_MISS", 0.9)
        if signals.answer_is_abstention:
            return Prediction("OK_CORRECT_ABSTENTION", 0.6)
        return Prediction("OK_GROUNDED", 0.6)


_CODE_LIST = "\n".join(
    f"- {code}: {meta.description}" for code, meta in FAILURE_CODES.items() if not meta.reserved
)

LLM_CLASSIFIER_SYSTEM = f"""You classify why a retrieval-augmented generation (RAG) answer failed.
You receive a short list of FACTS observed by the system about one RAG execution. Pick exactly ONE
failure code from this taxonomy:
{_CODE_LIST}

Decision guide (apply in this order, stop at the first that matches the facts):
1. A stage timed out → EVAL_MODEL_TIMEOUT. A judge returned malformed output → EVAL_JUDGE_MALFORMED.
2. Zero chunks retrieved → RETRIEVAL_EMPTY.
3. Gold-relevant chunks are known and NONE of them was retrieved → RETRIEVAL_MISS.
   (If the facts say gold labels are not available, RETRIEVAL_MISS is impossible.)
4. Context judged insufficient and the system abstained: mostly irrelevant chunks (70% or more) →
   RETRIEVAL_DISTRACTOR_DOMINANT, otherwise OK_CORRECT_ABSTENTION.
5. Context judged insufficient but the system answered anyway → ABSTENTION_FALSE_NEGATIVE.
6. Context judged sufficient but the system abstained → ABSTENTION_FALSE_POSITIVE.
7. Context sufficient and answered: the answer contradicts the context → GENERATION_CONTRADICTION;
   some claims supported and some unsupported → GROUNDING_PARTIAL; no claim supported and the
   faithfulness score is low → GENERATION_HALLUCINATION; all claims supported with a high
   faithfulness score → OK_GROUNDED.
8. If the facts conflict with each other → DIAGNOSIS_UNCERTAIN.

Use only the facts provided; never invent facts. Reply with ONLY JSON:
{{"failure_code": "...", "confidence": 0.0, "rationale": "..."}} where confidence is between 0 and 1.
"""


def _yes_no(value: bool | None, unknown: str = "unknown") -> str:
    if value is None:
        return unknown
    return "yes" if value else "no"


def _signal_summary(signals: SignalBag) -> str:
    """Render the signal bag as plain facts a small model can follow."""
    lines: list[str] = []
    if signals.stage_error == "TIMEOUT":
        lines.append("- A generation or judge stage TIMED OUT.")
    else:
        lines.append("- No stage timed out.")
    lines.append(
        "- Judge outputs were well-formed." if signals.judge_schema_ok else "- A judge returned MALFORMED output."
    )
    lines.append(f"- Chunks retrieved: {signals.n_retrieved}.")
    if signals.gold_ids:
        hit = "yes" if signals.gold_hit else "no"
        lines.append(
            f"- Gold-relevant chunks are labelled for this query ({len(signals.gold_ids)}); "
            f"at least one gold chunk retrieved: {hit}."
        )
    else:
        lines.append("- Gold labels are NOT available for this query (retrieval miss cannot be determined).")
    if signals.context_sufficient is None:
        lines.append("- Relevance judge verdict: not available.")
    else:
        rel = signals.chunk_relevance or []
        relevant = sum(1 for i in rel if i.get("relevant") is True or (isinstance(i.get("score"), (int, float)) and float(i["score"]) >= 0.5))
        frac = signals.irrelevant_frac
        frac_txt = f"{frac:.0%}" if frac is not None else "unknown"
        lines.append(
            f"- Relevance judge: {relevant}/{len(rel) or signals.n_retrieved} chunks relevant, "
            f"{frac_txt} irrelevant; context sufficient: {_yes_no(signals.context_sufficient)}."
        )
    lines.append(
        "- The system ABSTAINED (no answer)." if signals.answer_is_abstention else "- The system ANSWERED."
    )
    if signals.faithfulness_score is not None and not signals.answer_is_abstention and signals.context_sufficient:
        lines.append(
            f"- Faithfulness judge: score {signals.faithfulness_score:.2f}; "
            f"{signals.supported_claim_count or 0} supported claim(s), "
            f"{signals.unsupported_claim_count or 0} unsupported claim(s)."
        )
        lines.append(
            f"- Contradiction judge: answer contradicts context: {_yes_no(signals.answer_contradicts_context)}."
        )
    else:
        lines.append("- Grounding judges did not run (not needed for this case).")
    return "\n".join(lines)


def _extract_json(text: str) -> Any:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


class LLMClassifier:
    """Prompts an LLM with the signal bag; malformed output → DIAGNOSIS_UNCERTAIN."""

    name = "llm"

    def __init__(self, settings: Settings | None = None, *, max_attempts: int = 2) -> None:
        self.settings = settings or get_settings()
        self.max_attempts = max_attempts
        self.model = self.settings.model_name
        self.prompt_version = CLASSIFIER_PROMPT_VERSION

    def predict(self, signals: SignalBag) -> Prediction:
        provider = get_llm_provider(self.settings)
        messages = [
            {"role": "system", "content": LLM_CLASSIFIER_SYSTEM},
            {"role": "user", "content": f"<signals>\n{_signal_summary(signals)}\n</signals>"},
        ]
        started = time.perf_counter()
        last_error = ""
        for attempt in range(self.max_attempts):
            call = list(messages)
            if attempt:
                call.append(
                    {
                        "role": "user",
                        "content": (
                            "Your previous reply was not valid JSON with a known failure_code. "
                            f"Error: {last_error}. Reply with ONLY the JSON object."
                        ),
                    }
                )
            try:
                result = provider.complete(
                    call, model=self.settings.model_name, timeout=self.settings.model_timeout_seconds
                )
            except AppError as exc:
                last_error = exc.message
                logger.warning("llm_classifier_call_failed", error=exc.message, attempt=attempt + 1)
                continue
            try:
                data = _extract_json(result.content)
                code = str(data.get("failure_code", "")).strip().upper()
                if code not in FAILURE_CODES:
                    raise ValueError(f"unknown failure_code {code!r}")
                conf = float(data.get("confidence", 0.5))
                conf = 0.0 if conf < 0 else 1.0 if conf > 1 else conf
                return Prediction(
                    code=code,
                    score=conf,
                    rationale=str(data.get("rationale") or "")[:500],
                    latency_ms=round((time.perf_counter() - started) * 1000, 2),
                )
            except (ValueError, TypeError, AttributeError, json.JSONDecodeError) as exc:
                last_error = str(exc)
        return Prediction(
            code="DIAGNOSIS_UNCERTAIN",
            score=0.0,
            rationale=f"malformed classifier output: {last_error}"[:500],
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
            malformed=True,
        )
