"""Claim-level NLI faithfulness backend (Phase 2, ADR-045).

A fake scorer stands in for the cross-encoder, so these tests need no model
download. The fake reads the label order from the id2label it is given, which
lets the tests prove the code never assumes an order.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db import session as db_session
from app.db.models import JudgeResult
from app.services.diagnosis.engine import diagnose_execution
from app.services.diagnosis.models import SignalBag
from app.services.diagnosis.rules import apply_rules
from app.services.eval.evaluate import run_evaluation
from app.services.eval.fakes import ScriptedJudgeLLM, contradiction_json, relevance_json
from app.services.judges.faithfulness_nli import (
    DECISION_RULE,
    MAX_CLAIMS,
    NLI_FAITHFULNESS_VERSION,
    NLI_MODEL_ID,
    NLI_MODEL_REVISION,
    NLIScorer,
    NLIUnavailableError,
    judge_faithfulness_nli,
    premise_units,
    premise_windows,
    score_claims,
    set_nli_scorer,
    split_claims,
)
from app.services.judges.nli_validation import (
    format_nli_markdown,
    threshold_sensitivity,
    validate_nli_faithfulness,
)
from app.services.judges.replay import replaying_judges
from app.services.judges.validation import JudgeExample
from app.services.llm_client import set_llm_provider

DEFAULT_ORDER = {0: "contradiction", 1: "entailment", 2: "neutral"}
# Words and decimals ("1.25"), without sentence-ending periods.
_WORD = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?")
_STOP = {"the", "a", "an", "of", "per", "is", "are", "and", "to", "in", "for", "be", "can"}


def whitespace_spans(text: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in re.finditer(r"\S+", text)]


def fake_verdict(premise: str, hypothesis: str) -> str:
    """Entailed if every content word appears in the premise; contradicted if
    the hypothesis has a number the premise lacks while sharing its topic."""
    p_words = set(_WORD.findall(premise.lower()))
    h_words = [w for w in _WORD.findall(hypothesis.lower()) if w not in _STOP]
    if h_words and all(w in p_words for w in h_words):
        return "entailment"
    numbers = [w for w in h_words if any(ch.isdigit() for ch in w)]
    shared = [w for w in h_words if w in p_words and not any(ch.isdigit() for ch in w)]
    if numbers and shared and any(n not in p_words for n in numbers):
        return "contradiction"
    return "neutral"


class FakeScorer:
    def __init__(self, id2label=None, max_length: int = 512) -> None:
        self.id2label = dict(id2label or DEFAULT_ORDER)
        self.calls = 0
        self.max_length = max_length

    def predict(self, pairs):
        self.calls += 1
        out = []
        for premise, hypothesis in pairs:
            verdict = fake_verdict(premise, hypothesis)
            out.append([0.9 if self.id2label[i].lower() == verdict else 0.05 for i in sorted(self.id2label)])
        return out

    def scorer(self) -> NLIScorer:
        return NLIScorer(
            predict_probs=self.predict,
            id2label=self.id2label,
            token_spans=whitespace_spans,
            max_length=self.max_length,
        )


class ExplodingScorer:
    def scorer(self) -> NLIScorer:
        def boom(pairs):
            raise AssertionError("the NLI model must not run here")

        return NLIScorer(predict_probs=boom, id2label=DEFAULT_ORDER, token_spans=whitespace_spans, max_length=512)


PTO = "Full-time employees accrue 1.25 days of PTO per month, for a total of 15 days per year."
HOURS = "Standard office hours are Monday through Friday, 9:00 to 17:30 local time."


@pytest.fixture(autouse=True)
def _reset():
    yield
    set_nli_scorer(None)
    set_llm_provider(None)


# --- claim splitting ---------------------------------------------------------


def test_split_claims_sentences_decimals_and_abbreviations() -> None:
    answer = (
        "Employees accrue 1.25 days per month. That is 15 days per year! "
        "Leave types differ, e.g. sick leave is separate. Dr. Smith approves exceptions."
    )
    assert split_claims(answer) == [
        "Employees accrue 1.25 days per month.",
        "That is 15 days per year!",
        "Leave types differ, e.g. sick leave is separate.",
        "Dr. Smith approves exceptions.",
    ]


def test_split_claims_bullets_short_refusals_and_duplicates() -> None:
    answer = "- Employees accrue 1.25 days monthly.\n- Too short.\n* Employees accrue 1.25 days monthly.\nI don't know the carry-over limit."
    assert split_claims(answer) == ["Employees accrue 1.25 days monthly."]


def test_split_claims_fallbacks_and_cap() -> None:
    assert split_claims("15 days.") == ["15 days."]  # short answer still checked
    assert split_claims("I don't know.") == []  # a refusal is not a claim
    assert split_claims("   ") == []
    many = " ".join(f"Claim number {i} is here." for i in range(30))
    assert len(split_claims(many)) == MAX_CLAIMS


# --- windows and label order -------------------------------------------------


def test_premise_windows_overlap_and_exact_substrings() -> None:
    text = " ".join(f"w{i}" for i in range(25))
    windows = premise_windows(text, budget_tokens=10, overlap_tokens=3, token_spans=whitespace_spans)
    assert windows[0].split()[0] == "w0" and windows[-1].split()[-1] == "w24"
    assert all(w in text for w in windows)
    # Consecutive windows share the overlap tokens.
    assert windows[0].split()[-3:] == windows[1].split()[:3]
    assert premise_windows("short text", budget_tokens=10, overlap_tokens=3, token_spans=whitespace_spans) == ["short text"]
    with pytest.raises(ValueError):
        premise_windows(text, budget_tokens=0, overlap_tokens=0, token_spans=whitespace_spans)


def test_premise_units_are_sentences_and_adjacent_pairs() -> None:
    text = "Refunds take 30 days. Contact support first. Refunds go to the card."
    units = premise_units(text)
    assert units[:3] == ["Refunds take 30 days.", "Contact support first.", "Refunds go to the card."]
    assert units[3:] == [
        "Refunds take 30 days. Contact support first.",
        "Contact support first. Refunds go to the card.",
    ]
    assert premise_units("One sentence only") == ["One sentence only"]
    assert premise_units("   ") == []


class _SentenceScorer:
    """Entails only the exact sentence; any other sentence 'contradicts'."""

    def __init__(self) -> None:
        self.premises: list[str] = []

    def scorer(self) -> NLIScorer:
        def predict(pairs):
            self.premises.extend(p for p, _ in pairs)
            # DEFAULT_ORDER: 0 contradiction, 1 entailment, 2 neutral
            return [[0.0, 1.0, 0.0] if p == h else [1.0, 0.0, 0.0] for p, h in pairs]

        return NLIScorer(predict_probs=predict, id2label=DEFAULT_ORDER, token_spans=whitespace_spans, max_length=512)


def test_claims_are_scored_against_sentences_and_support_beats_contradiction() -> None:
    fake = _SentenceScorer()
    chunk = "Refunds take 30 days to arrive. Contact support with your order."
    results, _ = score_claims(
        ["Refunds take 30 days to arrive.", "Refunds are paid in store credit."],
        [{"chunk_id": "r:c0", "text": chunk}],
        fake.scorer(),
    )
    assert "Refunds take 30 days to arrive." in fake.premises
    # Supported by one sentence, "contradicted" by the other: support wins.
    assert results[0].supported and not results[0].contradicted
    assert not results[1].supported and results[1].contradicted


@pytest.mark.parametrize(
    "order",
    [
        DEFAULT_ORDER,
        {0: "entailment", 1: "neutral", 2: "contradiction"},
        {0: "NEUTRAL", 1: "Contradiction", 2: "ENTAILMENT"},
    ],
)
def test_label_order_is_read_from_the_model_config(order) -> None:
    fake = FakeScorer(order)
    claims = ["Full-time employees accrue 1.25 days of PTO per month.", "Full-time employees accrue 3 days of PTO per month."]
    results, _ = score_claims(claims, [{"chunk_id": "h:c0", "text": PTO}], fake.scorer())
    assert [r.supported for r in results] == [True, False]
    assert [r.contradicted for r in results] == [False, True]


def test_missing_labels_are_rejected() -> None:
    with pytest.raises(NLIUnavailableError):
        FakeScorer({0: "yes", 1: "no", 2: "maybe"}).scorer()


def test_all_pairs_scored_in_one_call_with_windowing() -> None:
    fake = FakeScorer(max_length=40)
    long_chunk = " ".join(["filler"] * 60) + " " + PTO
    results, counts = score_claims(
        ["Full-time employees accrue 1.25 days of PTO per month."],
        [{"chunk_id": "long:c0", "text": long_chunk}, {"chunk_id": "h:c1", "text": HOURS}],
        fake.scorer(),
    )
    assert fake.calls == 1
    assert counts["window_count"] > 2  # the long chunk was split
    assert results[0].supported and results[0].best_chunk_id == "long:c0"


def test_pair_cap_scores_most_similar_chunks_first_and_records_truncation() -> None:
    fake = _SentenceScorer()
    claim = "Refunds take 30 days to arrive."
    chunks = [
        {"chunk_id": "low:c0", "text": "Unrelated text about parking.", "retrieval_score": 0.10},
        {"chunk_id": "high:c0", "text": claim, "retrieval_score": 0.90},
        {"chunk_id": "mid:c0", "text": "Something about hotels.", "retrieval_score": 0.50},
    ]
    results, counts = score_claims([claim], chunks, fake.scorer(), max_pairs=1)
    assert fake.premises == [claim]  # only the most similar chunk was scored
    assert results[0].supported
    assert counts["truncated"] is True
    assert (counts["chunks_total"], counts["chunks_skipped"]) == (3, 2)

    full, counts = score_claims([claim], chunks, _SentenceScorer().scorer(), max_pairs=2000)
    assert counts["truncated"] is False and counts["chunks_skipped"] == 0 and counts["pair_count"] == 3


def test_judge_output_records_truncation() -> None:
    chunks = [{"chunk_id": f"d{i}:c0", "text": PTO, "retrieval_score": 1 - i / 10} for i in range(5)]
    result, meta = judge_faithfulness_nli(
        "q", "Full-time employees accrue 1.25 days of PTO per month.", chunks, scorer=FakeScorer().scorer(), max_pairs=2
    )
    assert result.truncated is True and meta["truncated"] is True
    assert result.max_pairs == 2 and result.pair_count == 2 and result.chunks_skipped == 3
    assert result.claims[0].best_chunk_id == "d0:c0"


def test_nli_max_pairs_default_is_500(monkeypatch) -> None:
    from app.core.config import get_settings
    from app.services.judges.faithfulness_nli import DEFAULT_MAX_PAIRS

    monkeypatch.delenv("NLI_MAX_PAIRS", raising=False)
    assert DEFAULT_MAX_PAIRS == 500
    assert get_settings().nli_max_pairs == DEFAULT_MAX_PAIRS


def test_nli_max_pairs_setting_reaches_the_judge(monkeypatch) -> None:
    from app.core.config import get_settings
    from app.services.judges.faithfulness_router import judge_faithfulness_routed

    monkeypatch.setenv("FAITHFULNESS_BACKEND", "nli")
    monkeypatch.setenv("NLI_MAX_PAIRS", "20")
    set_nli_scorer(FakeScorer().scorer())
    chunks = [{"chunk_id": f"d{i}:c0", "text": PTO, "retrieval_score": 0.5} for i in range(30)]
    result, _, _ = judge_faithfulness_routed("q", "Full-time employees accrue 1.25 days of PTO per month.", chunks, get_settings())
    assert result.max_pairs == 20 and result.pair_count == 20 and result.truncated
    monkeypatch.setenv("NLI_MAX_PAIRS", "5")
    with pytest.raises(Exception):
        get_settings()


# --- judge output and the rules ----------------------------------------------


def test_judge_output_schema_and_provenance() -> None:
    answer = "Full-time employees accrue 1.25 days of PTO per month. They also get a free car."
    result, meta = judge_faithfulness_nli("q", answer, [{"chunk_id": "h:c0", "text": PTO}], scorer=FakeScorer().scorer())
    assert result.faithfulness_score == 0.5
    assert [c.supported for c in result.claims] == [True, False]
    assert result.claims[0].supporting_chunk_ids == ["h:c0"]
    assert (result.model_id, result.revision, result.decision_rule) == (NLI_MODEL_ID, NLI_MODEL_REVISION, DECISION_RULE)
    assert result.version == NLI_FAITHFULNESS_VERSION
    assert result.label_order == ["contradiction", "entailment", "neutral"]
    assert meta["schema_ok"] and meta["backend"] == "nli"
    empty, _ = judge_faithfulness_nli("q", "I don't know.", [{"chunk_id": "h:c0", "text": PTO}], scorer=FakeScorer().scorer())
    assert empty.faithfulness_score is None and empty.claims == []


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ("Full-time employees accrue 1.25 days of PTO per month.", "OK_GROUNDED"),
        ("Full-time employees accrue 1.25 days of PTO per month. They also get a free car.", "GROUNDING_PARTIAL"),
        ("Employees get a company car and a parking space.", "GENERATION_HALLUCINATION"),
    ],
)
def test_nli_output_drives_the_rules(answer: str, expected: str) -> None:
    result, _ = judge_faithfulness_nli("q", answer, [{"chunk_id": "h:c0", "text": PTO}], scorer=FakeScorer().scorer())
    bag = SignalBag(
        n_retrieved=1,
        retrieved_ids=["h:c0"],
        context_sufficient=True,
        answer_contradicts_context=False,
        faithfulness_score=result.faithfulness_score,
        supported_claim_count=sum(c.supported for c in result.claims),
        unsupported_claim_count=sum(not c.supported for c in result.claims),
    )
    assert apply_rules(bag).primary_code == expected


# --- backend flag and replay --------------------------------------------------


def _scripts(chunk_ids: list[str]) -> dict:
    return {
        "relevance": [relevance_json(chunk_ids, sufficient=True)],
        "contradiction": [contradiction_json(False)],
        "faithfulness": ["NOT USED"],
    }


def _trace(client: TestClient, api_key: str) -> str:
    body = {
        "query": "How much PTO do full-time employees accrue per month?",
        "retrieved_chunks": [{"chunk_id": "h:c0", "text": PTO}],
        "answer": "Full-time employees accrue 1.25 days of PTO per month.",
        "diagnose": False,
    }
    resp = client.post("/api/v1/traces", json=body, headers={"Authorization": f"Bearer {api_key}"})
    assert resp.status_code == 200, resp.text
    return resp.json()["execution_id"]


def _faithfulness_row(execution_id: str) -> JudgeResult:
    db_session.init_db()
    db = db_session.SessionLocal()
    try:
        return db.query(JudgeResult).filter_by(execution_id=execution_id, judge_type="faithfulness").one()
    finally:
        db.close()


def test_nli_backend_is_used_when_selected(client: TestClient, api_key: str, monkeypatch) -> None:
    monkeypatch.setenv("FAITHFULNESS_BACKEND", "nli")
    fake = FakeScorer()
    set_nli_scorer(fake.scorer())
    llm = ScriptedJudgeLLM(_scripts(["h:c0"]))
    set_llm_provider(llm)
    eid = _trace(client, api_key)
    db_session.init_db()
    db = db_session.SessionLocal()
    try:
        diag = diagnose_execution(db, execution_id=eid)
    finally:
        db.close()
    assert diag["failure_code"] == "OK_GROUNDED"
    assert fake.calls == 1 and "faithfulness" not in llm.calls
    row = _faithfulness_row(eid)
    assert row.prompt_version == NLI_FAITHFULNESS_VERSION
    assert row.output["revision"] == NLI_MODEL_REVISION
    assert diag["signals"]["nli_contradiction"] is False


def test_llm_backend_still_available(client: TestClient, api_key: str, monkeypatch) -> None:
    monkeypatch.setenv("FAITHFULNESS_BACKEND", "llm")
    set_nli_scorer(ExplodingScorer().scorer())
    scripts = _scripts(["h:c0"])
    scripts["faithfulness"] = [json.dumps({"faithfulness_score": 1.0, "claims": [{"claim": "c", "supported": True}]})]
    set_llm_provider(ScriptedJudgeLLM(scripts))
    eid = _trace(client, api_key)
    db_session.init_db()
    db = db_session.SessionLocal()
    try:
        diag = diagnose_execution(db, execution_id=eid)
    finally:
        db.close()
    assert diag["failure_code"] == "OK_GROUNDED"
    assert _faithfulness_row(eid).prompt_version == "faithfulness.v1"


def test_scripted_suites_replay_whatever_the_backend(monkeypatch) -> None:
    """The replay rule: heldout/planted keep their scripted outputs under nli."""
    monkeypatch.setenv("FAITHFULNESS_BACKEND", "nli")
    set_nli_scorer(ExplodingScorer().scorer())
    db_session.init_db()
    db = db_session.SessionLocal()
    try:
        result = run_evaluation(db, suite_id="planted_v1", suite_version="1.0.0", persist=False)
    finally:
        db.close()
    assert result["summary"]["failure_code_accuracy"] == 1.0


def test_recorded_nli_output_replays_without_the_model(client: TestClient, api_key: str, monkeypatch) -> None:
    monkeypatch.setenv("FAITHFULNESS_BACKEND", "nli")
    set_nli_scorer(ExplodingScorer().scorer())
    recorded, _ = judge_faithfulness_nli(
        "q", "Full-time employees accrue 1.25 days of PTO per month.",
        [{"chunk_id": "h:c0", "text": PTO}], scorer=FakeScorer().scorer(),
    )
    scripts = _scripts(["h:c0"]) | {"faithfulness_nli": recorded.model_dump()}
    set_llm_provider(ScriptedJudgeLLM(scripts))
    eid = _trace(client, api_key)
    db_session.init_db()
    db = db_session.SessionLocal()
    try:
        with replaying_judges(scripts):
            diag = diagnose_execution(db, execution_id=eid)
    finally:
        db.close()
    assert diag["failure_code"] == "OK_GROUNDED"
    assert _faithfulness_row(eid).prompt_version == NLI_FAITHFULNESS_VERSION


def test_dockerfile_pins_the_same_model_revision() -> None:
    dockerfile = Path(__file__).resolve().parents[1] / "Dockerfile"
    if not dockerfile.is_file():
        pytest.skip("Dockerfile not available in this environment")
    text = dockerfile.read_text(encoding="utf-8")
    assert f"CrossEncoder('{NLI_MODEL_ID}', revision='{NLI_MODEL_REVISION}')" in text


# --- validation tooling (synthetic examples; no numbers are published) -------


def _example(eid: str, judge: str, **fields) -> JudgeExample:
    base = {
        "example_id": eid,
        "judge": judge,
        "query": "How much PTO?",
        "chunks": [{"chunk_id": "h:c0", "text": PTO}],
        "annotator": "test",
        "annotation_date": "2026-11-08",
    }
    return JudgeExample.model_validate(base | fields)


def test_validate_nli_faithfulness_and_markdown() -> None:
    supported = "Full-time employees accrue 1.25 days of PTO per month."
    invented = "Employees get a company car."
    examples = [
        _example("f1", "faithfulness", answer=supported, claims=[{"claim": supported, "supported": True}], faithfulness_band=[1.0, 1.0]),
        _example("f2", "faithfulness", answer=f"{supported} {invented}",
                 claims=[{"claim": supported, "supported": True}, {"claim": invented, "supported": False}],
                 faithfulness_band=[0.5, 0.5]),
        _example("f3", "faithfulness", answer=invented, claims=[{"claim": invented, "supported": False}], faithfulness_band=[0.0, 0.0]),
        _example("c1", "contradiction", answer="Full-time employees accrue 3 days of PTO per month.", contradicts=True),
        _example("c2", "contradiction", answer=supported, contradicts=False),
    ]
    llm_report = {"predictions": [
        {"judge": "contradiction", "variant": "v1", "schema_ok": True, "example_id": "c1", "contradicts": True},
        {"judge": "contradiction", "variant": "v1", "schema_ok": True, "example_id": "c2", "contradicts": True},
    ]}
    section = validate_nli_faithfulness(examples, FakeScorer().scorer(), llm_report=llm_report, k_folds=3)
    assert section["claim_level"]["n"] == 4 and section["claim_level"]["accuracy"] == 1.0
    assert section["answer_level"]["has_unsupported_claim"]["accuracy"] == 1.0
    assert section["contradiction"]["vs_labels"]["accuracy"] == 1.0
    assert section["contradiction"]["vs_llm_judge"]["raw_agreement"] == 0.5
    assert len(section["sensitivity"]["sweep"]) == 9
    assert section["sensitivity"]["cross_validation"]["folds"]
    md = format_nli_markdown(section, llm_faithfulness={"has_unsupported_claim": section["answer_level"]["has_unsupported_claim"], "score_mae": 0.1, "score_in_band_rate": 0.5})
    assert "not used to choose the rule" in md and DECISION_RULE in md and "| llm |" in md


def test_threshold_sensitivity_groups_folds_by_example() -> None:
    units = [
        {"example_id": f"e{i}", "label": i % 2 == 0, "pred": i % 2 == 0, "entailment": 0.9 if i % 2 == 0 else 0.1}
        for i in range(10)
    ]
    out = threshold_sensitivity(units, k_folds=5)
    assert out["cross_validation"]["k"] == 5
    assert out["cross_validation"]["mean_test_accuracy"] == 1.0
    assert "Sensitivity only" in out["note"]


def test_cli_nli_only_validation_writes_markdown(tmp_path: Path) -> None:
    from app.cli.retrace import build_parser

    set_nli_scorer(FakeScorer().scorer())
    md = tmp_path / "nli.md"
    args = build_parser().parse_args(
        ["judges", "validate", "--faithfulness-backend", "nli", "--limit", "12", "--markdown", str(md)]
    )
    assert args.func(args) == 0
    assert md.read_text(encoding="utf-8").startswith("# NLI faithfulness validation")
