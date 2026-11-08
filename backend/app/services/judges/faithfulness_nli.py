"""Claim-level NLI faithfulness judge (FAITHFULNESS_BACKEND=nli, the default).

The answer is split into claims with a deterministic sentence splitter. Each
claim is scored as a hypothesis by a pinned NLI cross-encoder against premise
units cut from every retrieved chunk: each sentence and each adjacent pair of
sentences (see `premise_units`). A unit longer than the model's token limit is
split into overlapping windows. All pairs are scored in one batched call.

A claim is supported when entailment is the top NLI label for at least one
premise unit. It is flagged contradicted only when no unit supports it and at
least one unit's top label is contradiction. These rules are fixed by design;
they are not tuned on any labels (see ADR-045). The result keeps the schema the rules already use:
`faithfulness_score` = supported claims / claims, plus the claim list.
"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from app.core.errors import AppError
from app.core.logging import get_logger
from app.services.abstention import is_abstention_text

logger = get_logger(__name__)

NLI_FAITHFULNESS_VERSION = "faithfulness.nli.v1"
NLI_MODEL_ID = "cross-encoder/nli-deberta-v3-small"
# Pinned commit of the Hugging Face repo; backend/Dockerfile pre-downloads it.
NLI_MODEL_REVISION = "fa2804872c3b4bd748f38c0185cc85775361e735"
DECISION_RULE = "entailment_is_top_label"
PREMISE_UNIT = "sentence_and_adjacent_pair"

MAX_CLAIMS = 20
MIN_CLAIM_WORDS = 3
WINDOW_OVERLAP_TOKENS = 64
# [CLS] premise [SEP] hypothesis [SEP]
SPECIAL_TOKENS = 3
PREDICT_BATCH_SIZE = 32
# Upper bound on (claim, premise window) pairs per answer; NLI_MAX_PAIRS overrides.
DEFAULT_MAX_PAIRS = 500

REQUIRED_LABELS = ("contradiction", "entailment", "neutral")


class NLIUnavailableError(AppError):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(code="NLI_MODEL_UNAVAILABLE", message=message, status_code=503, details=details)


# --------------------------------------------------------------------------
# claim splitting
# --------------------------------------------------------------------------
# Lowercased abbreviations whose trailing period does not end a sentence.
ABBREVIATIONS = frozenset(
    {
        "e.g",
        "i.e",
        "etc",
        "vs",
        "approx",
        "dept",
        "fig",
        "no",
        "nos",
        "mr",
        "mrs",
        "ms",
        "dr",
        "prof",
        "inc",
        "ltd",
        "co",
        "corp",
        "st",
        "jr",
        "sr",
        "u.s",
        "u.k",
        "a.m",
        "p.m",
        "jan",
        "feb",
        "mar",
        "apr",
        "jun",
        "jul",
        "aug",
        "sep",
        "sept",
        "oct",
        "nov",
        "dec",
        "min",
        "max",
        "avg",
    }
)
_BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")
# Candidate boundary: sentence punctuation, optional closing quote/bracket,
# whitespace, then something that can start a sentence.
_BOUNDARY = re.compile(r"([.!?])([\"'”’)\]]*)\s+(?=[\"'“‘(\[]?[A-Z0-9])")


def _ends_with_abbreviation(text_before: str) -> bool:
    token = text_before.rsplit(None, 1)[-1] if text_before.split() else ""
    token = token.strip("\"'([").lower()
    if not token:
        return False
    if token in ABBREVIATIONS:
        return True
    # A single initial such as "J." in "J. Smith".
    return len(token) == 1 and token.isalpha()


def _split_line(line: str) -> list[str]:
    out: list[str] = []
    start = 0
    for match in _BOUNDARY.finditer(line):
        punct_end = match.end(2)
        candidate = line[start : match.start(1)]
        if match.group(1) == "." and _ends_with_abbreviation(candidate):
            continue
        out.append(line[start:punct_end].strip())
        start = match.end()
    tail = line[start:].strip()
    if tail:
        out.append(tail)
    return out


def split_claims(answer: str, *, max_claims: int = MAX_CLAIMS) -> list[str]:
    """Deterministic claim list for an answer.

    Lines and bullet items are split first, then sentences. Empty sentences,
    sentences of fewer than MIN_CLAIM_WORDS words and refusal sentences are
    dropped, duplicates removed, and the list capped at `max_claims`. If
    nothing survives but the answer has words and is not a refusal, the whole
    answer is one claim, so short factual answers ("15 days.") still count.
    """
    if not answer or not answer.strip():
        return []
    sentences: list[str] = []
    for raw_line in answer.splitlines():
        line = _BULLET.sub("", raw_line).strip()
        if line:
            sentences.extend(_split_line(re.sub(r"\s+", " ", line)))

    claims: list[str] = []
    seen: set[str] = set()
    for sentence in sentences:
        text = sentence.strip()
        if len(text.split()) < MIN_CLAIM_WORDS or is_abstention_text(text):
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        claims.append(text)
        if len(claims) >= max_claims:
            break

    if not claims:
        whole = re.sub(r"\s+", " ", answer).strip()
        if whole.split() and not is_abstention_text(whole):
            claims = [whole]
    return claims


# --------------------------------------------------------------------------
# premise units and windows
# --------------------------------------------------------------------------
def split_sentences(text: str) -> list[str]:
    """Every sentence of `text`, in order, nothing dropped (unlike split_claims)."""
    out: list[str] = []
    for raw_line in (text or "").splitlines():
        line = _BULLET.sub("", raw_line).strip()
        if line:
            out.extend(s for s in _split_line(re.sub(r"\s+", " ", line)) if s)
    return out


def premise_units(text: str) -> list[str]:
    """Premises for one chunk: each sentence plus each adjacent pair.

    Small MNLI-trained models are reliable on sentence-length premises but
    tend to answer "neutral" when the supporting sentence sits inside a
    paragraph, even for a verbatim copy. Scoring each sentence, and each pair
    of neighbouring sentences for claims that span two, is the SummaC-style
    remedy (Laban et al., 2022). Single-sentence chunks are used as they are.
    """
    sentences = split_sentences(text)
    if len(sentences) <= 1:
        stripped = (text or "").strip()
        return [stripped] if stripped else []
    units = list(sentences)
    units.extend(f"{a} {b}" for a, b in zip(sentences, sentences[1:], strict=False))
    seen: set[str] = set()
    return [u for u in units if not (u in seen or seen.add(u))]


def premise_windows(
    text: str,
    *,
    budget_tokens: int,
    overlap_tokens: int,
    token_spans: Callable[[str], list[tuple[int, int]]],
) -> list[str]:
    """Split `text` into overlapping windows of at most `budget_tokens` tokens.

    Windows are cut on token character offsets, so every window is an exact
    substring of the original text.
    """
    if budget_tokens <= 0:
        raise ValueError("budget_tokens must be positive")
    spans = [s for s in token_spans(text) if s[1] > s[0]]
    if len(spans) <= budget_tokens:
        return [text]
    overlap = max(0, min(overlap_tokens, budget_tokens - 1))
    step = budget_tokens - overlap
    windows: list[str] = []
    start = 0
    while start < len(spans):
        end = min(start + budget_tokens, len(spans))
        windows.append(text[spans[start][0] : spans[end - 1][1]])
        if end == len(spans):
            break
        start += step
    return windows


# --------------------------------------------------------------------------
# scorer
# --------------------------------------------------------------------------
@dataclass
class NLIScorer:
    """Wraps an NLI cross-encoder. Inject a fake in tests."""

    predict_probs: Callable[[list[tuple[str, str]]], Sequence[Sequence[float]]]
    id2label: dict[int, str]
    token_spans: Callable[[str], list[tuple[int, int]]]
    max_length: int
    model_id: str = NLI_MODEL_ID
    revision: str = NLI_MODEL_REVISION
    label_index: dict[str, int] = field(init=False)

    def __post_init__(self) -> None:
        index = {str(name).strip().lower(): int(i) for i, name in self.id2label.items()}
        missing = [label for label in REQUIRED_LABELS if label not in index]
        if missing:
            raise NLIUnavailableError(
                "NLI model labels do not include contradiction/entailment/neutral",
                details={"id2label": {int(k): v for k, v in self.id2label.items()}, "missing": missing},
            )
        self.label_index = index

    @property
    def label_order(self) -> list[str]:
        return [self.id2label[i].lower() for i in sorted(self.id2label)]

    def count_tokens(self, text: str) -> int:
        return len(self.token_spans(text))


_scorer: NLIScorer | None = None
_scorer_lock = threading.Lock()


def set_nli_scorer(scorer: NLIScorer | None) -> None:
    """Install a scorer (tests) or clear the cached one."""
    global _scorer
    with _scorer_lock:
        _scorer = scorer


def _load_cross_encoder():
    from sentence_transformers import CrossEncoder

    try:
        # Offline first: the Docker image pre-downloads this exact revision.
        return CrossEncoder(NLI_MODEL_ID, revision=NLI_MODEL_REVISION, local_files_only=True)
    except Exception:  # noqa: BLE001 - not cached yet; fall back to downloading it
        return CrossEncoder(NLI_MODEL_ID, revision=NLI_MODEL_REVISION)


def get_nli_scorer() -> NLIScorer:
    global _scorer
    with _scorer_lock:
        if _scorer is not None:
            return _scorer
        started = time.perf_counter()
        try:
            model = _load_cross_encoder()
        except Exception as exc:  # noqa: BLE001
            raise NLIUnavailableError(
                "Could not load the NLI faithfulness model",
                details={"model": NLI_MODEL_ID, "revision": NLI_MODEL_REVISION, "error": str(exc)[:300]},
            ) from exc
        tokenizer = model.tokenizer

        def token_spans(text: str) -> list[tuple[int, int]]:
            enc = tokenizer(text, add_special_tokens=False, return_offsets_mapping=True)
            return [tuple(span) for span in enc["offset_mapping"]]

        def predict_probs(pairs: list[tuple[str, str]]):
            return model.predict(
                pairs,
                apply_softmax=True,
                batch_size=PREDICT_BATCH_SIZE,
                show_progress_bar=False,
            )

        max_length = int(model.max_length or tokenizer.model_max_length or 512)
        max_length = min(max_length, 512)
        _scorer = NLIScorer(
            predict_probs=predict_probs,
            id2label=dict(model.model.config.id2label),
            token_spans=token_spans,
            max_length=max_length,
        )
        logger.info(
            "nli_model_ready",
            model=NLI_MODEL_ID,
            revision=NLI_MODEL_REVISION,
            label_order=_scorer.label_order,
            load_ms=round((time.perf_counter() - started) * 1000, 1),
        )
        return _scorer


# --------------------------------------------------------------------------
# scoring
# --------------------------------------------------------------------------
class NLIClaimResult(BaseModel):
    claim: str
    supported: bool
    contradicted: bool
    best_chunk_id: str | None = None
    entailment: float = Field(ge=0.0, le=1.0)
    contradiction: float = Field(ge=0.0, le=1.0)
    neutral: float = Field(ge=0.0, le=1.0)
    # Kept for compatibility with the LLM judge's claim schema.
    supporting_chunk_ids: list[str] = Field(default_factory=list)


class NLIFaithfulnessResult(BaseModel):
    """Same core fields as FaithfulnessJudgeResult, plus NLI provenance."""

    faithfulness_score: float | None = Field(default=None, ge=0.0, le=1.0)
    claims: list[NLIClaimResult] = Field(default_factory=list)
    # Any claim whose top label was contradiction for some chunk window. A
    # cross-check signal only; the contradiction judge still decides R30.
    nli_contradiction: bool = False
    backend: str = "nli"
    version: str = NLI_FAITHFULNESS_VERSION
    model_id: str = NLI_MODEL_ID
    revision: str = NLI_MODEL_REVISION
    decision_rule: str = DECISION_RULE
    premise_unit: str = PREMISE_UNIT
    label_order: list[str] = Field(default_factory=list)
    pair_count: int = 0
    window_count: int = 0
    # True when NLI_MAX_PAIRS stopped scoring before every chunk was covered;
    # the least similar chunks are the ones skipped.
    truncated: bool = False
    max_pairs: int = DEFAULT_MAX_PAIRS
    chunks_total: int = 0
    chunks_skipped: int = 0


def score_claims(
    claims: Sequence[str],
    chunks: Sequence[dict[str, Any]],
    scorer: NLIScorer,
    *,
    max_pairs: int | None = None,
) -> tuple[list[NLIClaimResult], dict[str, Any]]:
    """Score every claim against every premise window in one batched call.

    At most `max_pairs` (claim, window) pairs are scored. Chunks are visited
    in order of retrieval similarity, highest first, so when the cap is hit
    the least similar chunks are the ones left out; the result reports it.
    """
    empty = {"pair_count": 0, "window_count": 0, "truncated": False, "chunks_total": 0, "chunks_skipped": 0}
    usable = [(str(c.get("chunk_id") or ""), str(c.get("text") or ""), _similarity(c), i) for i, c in enumerate(chunks)]
    usable = [u for u in usable if u[1].strip()]
    if not claims:
        return [], {**empty, "chunks_total": len(usable)}
    # Highest similarity first; chunks without a score keep their order, last.
    usable.sort(key=lambda u: (u[2] is None, -(u[2] or 0.0), u[3]))

    max_windows = max(1, (max_pairs or DEFAULT_MAX_PAIRS) // len(claims))
    longest_claim = max(scorer.count_tokens(c) for c in claims)
    budget = max(32, scorer.max_length - longest_claim - SPECIAL_TOKENS)
    windows: list[tuple[str, str]] = []
    truncated = False
    chunks_scored = 0
    for cid, text, _score, _i in usable:
        if len(windows) >= max_windows:
            truncated = True
            break
        chunks_scored += 1
        for unit in premise_units(text):
            # A unit over the token budget (a very long sentence) is windowed.
            for window in premise_windows(
                unit,
                budget_tokens=budget,
                overlap_tokens=WINDOW_OVERLAP_TOKENS,
                token_spans=scorer.token_spans,
            ):
                if len(windows) >= max_windows:
                    truncated = True
                    break
                windows.append((cid, window))

    pairs = [(window, claim) for claim in claims for _, window in windows]
    probs = list(scorer.predict_probs(pairs)) if pairs else []
    ent_i = scorer.label_index["entailment"]
    con_i = scorer.label_index["contradiction"]
    neu_i = scorer.label_index["neutral"]

    results: list[NLIClaimResult] = []
    n_windows = len(windows)
    for ci, claim in enumerate(claims):
        best_ent, best_chunk, best_neu = 0.0, None, 1.0 if not windows else 0.0
        max_con = 0.0
        supported = any_contradiction = False
        supporting: list[str] = []
        for wi, (cid, _window) in enumerate(windows):
            row = [float(x) for x in probs[ci * n_windows + wi]]
            top = max(range(len(row)), key=lambda k: row[k])
            if top == ent_i:
                supported = True
                if cid not in supporting:
                    supporting.append(cid)
            if top == con_i:
                any_contradiction = True
            if row[ent_i] > best_ent or best_chunk is None:
                best_ent, best_chunk, best_neu = row[ent_i], cid, row[neu_i]
            max_con = max(max_con, row[con_i])
        # With sentence-level premises an unrelated sentence of the same chunk
        # can "contradict" a claim another sentence supports ("30 days" vs a
        # "5 business days" sentence), so support takes precedence.
        contradicted = any_contradiction and not supported
        results.append(
            NLIClaimResult(
                claim=claim,
                supported=supported,
                contradicted=contradicted,
                best_chunk_id=best_chunk,
                entailment=round(min(1.0, max(0.0, best_ent)), 6),
                contradiction=round(min(1.0, max(0.0, max_con)), 6),
                neutral=round(min(1.0, max(0.0, best_neu)), 6),
                supporting_chunk_ids=supporting,
            )
        )
    return results, {
        "pair_count": len(pairs),
        "window_count": n_windows,
        "truncated": truncated,
        "chunks_total": len(usable),
        "chunks_skipped": len(usable) - chunks_scored,
    }


def _similarity(chunk: dict[str, Any]) -> float | None:
    for key in ("retrieval_score", "score"):
        value = chunk.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    return None


def judge_faithfulness_nli(
    query: str,
    answer: str,
    chunks: Sequence[dict[str, Any]],
    *,
    scorer: NLIScorer | None = None,
    max_pairs: int | None = None,
) -> tuple[NLIFaithfulnessResult, dict[str, Any]]:
    """Score `answer` against `chunks`. `query` is not part of NLI scoring."""
    del query  # the claims are checked against the evidence, not the question
    scorer = scorer or get_nli_scorer()
    started = time.perf_counter()
    claims = split_claims(answer)
    max_pairs = max_pairs or DEFAULT_MAX_PAIRS
    claim_results, counts = score_claims(claims, chunks, scorer, max_pairs=max_pairs)
    supported = sum(1 for c in claim_results if c.supported)
    result = NLIFaithfulnessResult(
        faithfulness_score=(round(supported / len(claim_results), 6) if claim_results else None),
        claims=claim_results,
        nli_contradiction=any(c.contradicted for c in claim_results),
        model_id=scorer.model_id,
        revision=scorer.revision,
        label_order=scorer.label_order,
        pair_count=counts["pair_count"],
        window_count=counts["window_count"],
        truncated=counts["truncated"],
        max_pairs=max_pairs,
        chunks_total=counts["chunks_total"],
        chunks_skipped=counts["chunks_skipped"],
    )
    latency_ms = round((time.perf_counter() - started) * 1000, 2)
    logger.info(
        "judge_ok",
        judge_type="faithfulness",
        backend="nli",
        claims=len(claim_results),
        pairs=counts["pair_count"],
        truncated=counts["truncated"],
        latency_ms=latency_ms,
        operation="judge",
    )
    meta = {
        "model": f"{scorer.model_id}@{scorer.revision[:12]}",
        "schema_ok": True,
        "attempts": 1,
        "latency_ms": latency_ms,
        "backend": "nli",
        "truncated": counts["truncated"],
    }
    return result, meta
