"""live_v1 building blocks: eval-only faults, recording, offline replay, blind sheet."""

from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.errors import GenerationTimeoutError
from app.db import session as db_session
from app.schemas.generate import GenerateRequest
from app.services.eval.fakes import contradiction_json, relevance_json
from app.services.eval.faults import EVAL_FAULTS, get_fault
from app.services.eval.live_suite import (
    RecordingLLM,
    prediction_summary,
    record_to_offline_execution,
    replay_record,
    runs_hash,
)
from app.services.eval.runner import _ensure_eval_corpus
from app.services.eval.schemas import GoldCase
from app.services.generation import generate_answer
from app.services.judges.faithfulness_nli import NLIScorer, judge_faithfulness_nli, set_nli_scorer
from app.services.llm_client import LLMResult, set_llm_provider
from app.services.prompts import SYSTEM_PROMPT, build_chat_messages


def _load_script(name: str):
    for candidate in (
        Path(__file__).resolve().parents[2] / "scripts" / f"{name}.py",
        Path(f"/scripts/{name}.py"),
    ):
        if candidate.is_file():
            spec = importlib.util.spec_from_file_location(name, candidate)
            module = importlib.util.module_from_spec(spec)
            assert spec.loader is not None
            spec.loader.exec_module(module)
            return module
    pytest.skip(f"scripts/{name}.py not available in this environment")


PTO = "Full-time employees accrue 1.25 days of PTO per month, for a total of 15 days per year."
CHUNKS = [{"chunk_id": "employee_handbook:c000", "rank": 1, "retrieval_score": 0.8, "text": PTO}]


class _CaptureProvider:
    def __init__(self, reply: str = "ok") -> None:
        self.messages: list[list[dict[str, str]]] = []
        self.reply = reply

    def complete(self, messages, *, model: str, timeout: float) -> LLMResult:
        self.messages.append(messages)
        return LLMResult(content=self.reply, model=model, latency_ms=1.0)


class _TimeoutProvider:
    def complete(self, messages, *, model: str, timeout: float) -> LLMResult:
        raise GenerationTimeoutError("slow", details={})


class _ExplodingScorer:
    def scorer(self) -> NLIScorer:
        def boom(pairs):
            raise AssertionError("the NLI model must not run during replay")

        return NLIScorer(
            predict_probs=boom,
            id2label={0: "contradiction", 1: "entailment", 2: "neutral"},
            token_spans=lambda t: [(0, len(t))],
            max_length=512,
        )


def _entailing_scorer() -> NLIScorer:
    def predict(pairs):
        return [[0.0, 1.0, 0.0] if h.rstrip(".").lower() in p.lower() else [0.0, 0.0, 1.0] for p, h in pairs]

    def spans(text):
        out, pos = [], 0
        for word in text.split():
            start = text.index(word, pos)
            out.append((start, start + len(word)))
            pos = start + len(word)
        return out

    return NLIScorer(
        predict_probs=predict,
        id2label={0: "contradiction", 1: "entailment", 2: "neutral"},
        token_spans=spans,
        max_length=512,
    )


# --- eval-only faults --------------------------------------------------------


def test_public_generate_request_has_no_fault_field() -> None:
    assert "eval_fault" not in GenerateRequest.model_fields
    body = GenerateRequest.model_validate({"corpus_version_id": "v", "query": "q", "eval_fault": "wrong_facts"})
    assert not hasattr(body, "eval_fault")


def test_generate_route_never_passes_a_fault(client: TestClient, api_key: str, monkeypatch) -> None:
    from app.api import routes_generate

    seen: dict = {}

    def fake_run_rag(db, **kwargs):
        seen.update(kwargs)
        return {
            "request_id": "r",
            "execution_id": "e",
            "corpus_version_id": "v",
            "query": "q",
            "answer": "a",
            "abstained": False,
            "status": "COMPLETED",
            "retrieval": {"retrieval_trace_id": None, "top_k": 5, "latency_ms": 1.0, "results": []},
            "generation": {},
            "latency_ms": {},
        }

    monkeypatch.setattr(routes_generate, "run_rag", fake_run_rag)
    resp = client.post(
        "/api/v1/generate",
        json={"corpus_version_id": "v", "query": "How much PTO?", "eval_fault": "wrong_facts"},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200, resp.text
    assert "eval_fault" not in seen


def test_fault_suffix_reaches_only_the_system_prompt() -> None:
    plain = build_chat_messages("q", CHUNKS)
    assert plain[0]["content"] == SYSTEM_PROMPT
    provider = _CaptureProvider()
    set_llm_provider(provider)
    try:
        generate_answer(query="q", retrieved_chunks=CHUNKS, eval_fault=get_fault("wrong_facts"))
        generate_answer(query="q", retrieved_chunks=CHUNKS)
    finally:
        set_llm_provider(None)
    faulted, clean = provider.messages
    assert faulted[0]["content"] == SYSTEM_PROMPT + EVAL_FAULTS["wrong_facts"].system_suffix
    assert clean[0]["content"] == SYSTEM_PROMPT
    assert faulted[1] == clean[1]


def test_unknown_fault_is_rejected() -> None:
    assert get_fault(None) is None
    with pytest.raises(ValueError):
        get_fault("delete_everything")
    assert {f.prompt_tag for f in EVAL_FAULTS.values()} == {
        "eval_fault.wrong_facts.v1",
        "eval_fault.extra_unsupported_claim.v1",
    }


# --- recording and replay -----------------------------------------------------


def test_recording_llm_keeps_raw_replies_per_judge_in_order() -> None:
    rec = RecordingLLM(_CaptureProvider(reply='{"x": 1}'))
    rel = [{"role": "system", "content": "Rate chunk relevance"}, {"role": "user", "content": "u"}]
    con = [{"role": "system", "content": "Does the answer contradict the context?"}, {"role": "user", "content": "u"}]
    rec.complete(rel, model="m", timeout=1)
    rec.complete(rel, model="m", timeout=1)
    rec.complete(con, model="m", timeout=1)
    assert rec.replies == {"relevance": ['{"x": 1}', '{"x": 1}'], "contradiction": ['{"x": 1}']}
    timing_out = RecordingLLM(_TimeoutProvider())
    with pytest.raises(GenerationTimeoutError):
        timing_out.complete(con, model="m", timeout=1)
    assert timing_out.timeouts == ["contradiction"]


def _record(answer: str, *, nli_result: dict, contradicts: bool = False) -> dict:
    return {
        "record_version": "live_run.v1",
        "query_id": "L99",
        "condition": "wrong_answer_prompt",
        "corpus_variant": "main",
        "eval_fault": "wrong_facts",
        "query": "How much PTO do full-time employees accrue per month?",
        "execution": {"retrieved_chunks": CHUNKS, "answer": answer, "abstained": False, "status": "COMPLETED"},
        "generation": {"model": "llama3.2:latest", "prompt_version": "generator.v1+eval_fault.wrong_facts.v1"},
        "judges": {
            "relevance": [relevance_json(["employee_handbook:c000"], sufficient=True)],
            "contradiction": [contradiction_json(contradicts, ["employee_handbook:c000"] if contradicts else None)],
            "faithfulness_llm": ['{"faithfulness_score": 1.0, "claims": []}'],
            "faithfulness_nli": nli_result,
            "timeouts": [],
        },
        "live_diagnosis": {
            "failure_code": "SECRET_LIVE_CODE",
            "rule_id": "R31",
            "explanation": "LIVE EXPLANATION TEXT",
        },
    }


def test_offline_execution_accepts_a_recorded_nli_object() -> None:
    nli, _ = judge_faithfulness_nli(
        "q", "Employees accrue 1.25 days of PTO per month.", CHUNKS, scorer=_entailing_scorer()
    )
    fixture = record_to_offline_execution(
        _record("Employees accrue 1.25 days of PTO per month.", nli_result=nli.model_dump())
    )
    assert fixture.judge_scripts["faithfulness_nli"]["version"] == nli.version
    assert fixture.generation_model == "llama3.2:latest"
    GoldCase.model_validate(
        {
            "case_id": "x",
            "suite_id": "live_v1",
            "suite_version": "1.0.0",
            "corpus_id": "demo",
            "corpus_version_pin": "recorded",
            "query": "q",
            "expected_abstention": False,
            "relevant_chunk_ids": [],
            "failure_label": "OK_GROUNDED",
            "acceptable_primary_codes": ["OK_GROUNDED"],
            "annotator": "test",
            "annotation_date": "2026-11-08",
            "offline_execution": fixture.model_dump(),
        }
    )


@pytest.mark.parametrize(
    ("answer", "contradicts", "expected"),
    [
        ("Employees accrue 1.25 days of PTO per month.", False, "OK_GROUNDED"),
        ("Employees accrue 3 days of PTO per month.", True, "GENERATION_CONTRADICTION"),
    ],
)
def test_replay_reproduces_from_recorded_outputs_without_live_models(
    answer, contradicts, expected, monkeypatch
) -> None:
    monkeypatch.setenv("FAITHFULNESS_BACKEND", "nli")
    nli, _ = judge_faithfulness_nli("q", answer, CHUNKS, scorer=_entailing_scorer())
    set_nli_scorer(_ExplodingScorer().scorer())
    db_session.init_db()
    db = db_session.SessionLocal()
    try:
        stub = _ensure_eval_corpus(db)
        diagnosis = replay_record(
            db, _record(answer, nli_result=nli.model_dump(), contradicts=contradicts), corpus_version_id=stub
        )
    finally:
        db.close()
        set_nli_scorer(None)
    assert prediction_summary(diagnosis)["failure_code"] == expected


def test_runs_hash_ignores_key_order_and_whitespace() -> None:
    a = ['{"b": 1, "a": [1, 2]}', ""]
    b = ['{"a":[1,2],"b":1}']
    assert runs_hash(a) == runs_hash(b)
    assert runs_hash(a) != runs_hash(['{"a":[1,2],"b":2}'])


# --- corpus variants -----------------------------------------------------------


def test_corpus_variants_remove_and_add_documents() -> None:
    builder = _load_script("build_live_suite")
    suite = Path(__file__).resolve().parents[1] / "datasets" / "suites" / "live_v1" / "v1.0.0"
    config = json.loads((suite / "corpus_variants.json").read_text(encoding="utf-8"))
    main = {d["id"] for d in builder.variant_documents(config, "main")}
    removed = {d["id"] for d in builder.variant_documents(config, "gold_removed")}
    added = {d["id"] for d in builder.variant_documents(config, "distractors")}
    assert len(main) == 13
    assert removed == main - set(config["variants"]["gold_removed"]["remove"])
    assert main < added and len(added - main) == 6
    queries = [
        json.loads(line) for line in (suite / "queries.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    assert len(queries) == 50 and len({q["query_id"] for q in queries}) == 50
    assert {q["corpus_variant"] for q in queries} <= set(config["variants"])
    assert {q["eval_fault"] for q in queries} - {None} <= set(EVAL_FAULTS)


# --- blind labelling sheet ------------------------------------------------------


def test_labelling_sheet_is_blind_and_stable(tmp_path: Path) -> None:
    sheet_tool = _load_script("live_labelling")
    suite = tmp_path / "suite"
    suite.mkdir()
    records = []
    for i, (condition, fault, variant) in enumerate(
        [
            ("wrong_answer_prompt", "wrong_facts", "main"),
            ("gold_removed", None, "gold_removed"),
            ("distractors", None, "distractors"),
        ]
    ):
        rec = _record(f"Answer number {i}.", nli_result={})
        rec.update(query_id=f"L{i:02d}", condition=condition, eval_fault=fault, corpus_variant=variant)
        records.append(rec)
    (suite / "runs.jsonl").write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    (suite / "corpus_chunks.jsonl").write_text(
        json.dumps({"chunk_id": "a:c000", "document_id": "a", "text": "t"}) + "\n", encoding="utf-8"
    )
    out = tmp_path / "out"

    class Args:
        suite_dir = str(suite)
        out_dir = str(out)
        force = False

    assert sheet_tool.export(Args) == 0
    text = (out / "live_v1_sheet.csv").read_text(encoding="utf-8") + (out / "live_v1_sheet.html").read_text(
        encoding="utf-8"
    )
    for leaked in (
        "wrong_answer_prompt",
        "wrong_facts",
        "gold_removed",
        "distractors",
        "eval_fault",
        "SECRET_LIVE_CODE",
        "LIVE EXPLANATION TEXT",
        "R31",
        "L00",
        "L01",
        "L02",
        "llama3.2",
        "relevance",
        "faithfulness",
        "contradiction",
    ):
        assert leaked not in text, leaked
    with (out / "live_v1_sheet.csv").open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert tuple(rows[0]) == sheet_tool.SHEET_COLUMNS
    assert [r["sheet_id"] for r in rows] == ["S01", "S02", "S03"]
    assert all(r[c] == "" for r in rows for c in sheet_tool.LABEL_COLUMNS)
    assert "#1 [employee_handbook:c000]" in rows[0]["retrieved_chunks"]
    # Same order every time, and an existing sheet (possibly labelled) is not overwritten.
    first = [r["query"] + r["answer"] for r in rows]
    assert sheet_tool.export(Args) == 2
    Args.force = True
    assert sheet_tool.export(Args) == 0
    with (out / "live_v1_sheet.csv").open(encoding="utf-8", newline="") as fh:
        assert [r["query"] + r["answer"] for r in csv.DictReader(fh)] == first


def test_suite_check_requires_frozen_runs(tmp_path: Path, monkeypatch) -> None:
    checker = _load_script("build_heldout_suite")
    live = tmp_path / "live_v1" / "v1.0.0"
    live.mkdir(parents=True)
    (live / "queries.jsonl").write_text('{"query_id": "L01"}\n', encoding="utf-8")
    monkeypatch.setattr(checker, "SUITES_ROOT", tmp_path)
    assert checker.check_live() is True  # nothing recorded yet
    (live / "runs.jsonl").write_text('{"query_id": "L01"}\n', encoding="utf-8")
    assert checker.check_live() is False  # recorded but not frozen
    lines = (live / "runs.jsonl").read_text(encoding="utf-8").splitlines()
    manifest = {"runs_hash": runs_hash(lines), "run_count": 1, "queries_hash": runs_hash(['{"query_id": "L01"}'])}
    (live / "runs_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert checker.check_live() is True
    (live / "runs.jsonl").write_text('{"query_id": "L01", "edited": true}\n', encoding="utf-8")
    assert checker.check_live() is False
