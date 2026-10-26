"""Judge validation: labels dataset integrity, agreement stats, prompt variants, offline runs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.cli.retrace import build_parser
from app.services.eval.fakes import (
    ScriptedJudgeLLM,
    contradiction_json,
    detect_judge_type,
    faithfulness_json,
    relevance_json,
)
from app.services.judges import contradiction, faithfulness, relevance
from app.services.judges.prompt_variants import (
    JUDGE_TYPES,
    available_variants,
    describe_variants,
    get_system_prompt,
    prompt_sha256,
    prompt_version,
)
from app.services.judges.validation import (
    JudgeExample,
    JudgeLabelsValidationError,
    binary_metrics,
    build_messages,
    cohen_kappa,
    compute_examples_hash,
    default_labels_path,
    format_markdown,
    load_judge_labels,
    select_examples,
    validate_judges,
)
from app.services.llm_client import LLMResult, get_llm_provider

DATASET_DIR = Path(__file__).resolve().parents[1] / "datasets" / "judges"


# --------------------------------------------------------------------------- #
# Agreement statistics
# --------------------------------------------------------------------------- #


def test_cohen_kappa_hand_values() -> None:
    assert cohen_kappa([True, False, True, False], [True, False, True, False]) == 1.0
    # po = 0.5, pa = 0.5, pb = 0.5 -> pe = 0.5 -> kappa 0
    assert cohen_kappa([True, True, False, False], [True, False, True, False]) == pytest.approx(0.0)
    # 3 agree of 4: po = .75; a: 2/4 true, b: 3/4 true -> pe = .5*.75 + .5*.25 = .5 -> (0.75-0.5)/0.5
    assert cohen_kappa([True, True, False, False], [True, True, True, False]) == pytest.approx(0.5)
    assert cohen_kappa([True, True], [True, True]) == 1.0  # degenerate but identical
    assert cohen_kappa([True, True], [False, False]) == 0.0
    assert cohen_kappa([], []) is None


def test_binary_metrics_hand_values() -> None:
    m = binary_metrics([True, True, False, False], [True, False, True, False])
    assert (m["tp"], m["fp"], m["fn"], m["tn"]) == (1, 1, 1, 1)
    assert m["accuracy"] == 0.5 and m["precision"] == 0.5 and m["recall"] == 0.5 and m["f1"] == 0.5
    perfect = binary_metrics([True, False], [True, False])
    assert perfect["f1"] == 1.0 and perfect["kappa"] == 1.0
    none_pred = binary_metrics([True], [False])
    assert none_pred["precision"] is None and none_pred["recall"] == 0.0 and none_pred["f1"] == 0.0


# --------------------------------------------------------------------------- #
# Dataset integrity
# --------------------------------------------------------------------------- #


def test_labels_load_and_match_manifest() -> None:
    examples, file_hash = load_judge_labels(default_labels_path())
    manifest = json.loads((DATASET_DIR / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["dataset_hash"] == file_hash
    assert manifest["example_count"] == len(examples) >= 60
    per_judge = {j: sum(1 for e in examples if e.judge == j) for j in JUDGE_TYPES}
    assert per_judge == manifest["per_judge"]
    assert all(per_judge[j] >= 15 for j in JUDGE_TYPES)
    assert all(e.annotator == "author" and e.annotation_date for e in examples)
    tags = {t for e in examples for t in e.tags}
    assert {"injection", "missing_info_not_contradiction", "numerically_wrong", "partially_supported"} <= tags
    # hard cases: injection chunks exist for every judge type
    assert all(any("injection" in e.tags for e in examples if e.judge == j) for j in JUDGE_TYPES)
    # balanced-ish contradiction labels
    cons = [e for e in examples if e.judge == "contradiction"]
    assert 0.3 <= sum(1 for e in cons if e.contradicts) / len(cons) <= 0.7


def test_labels_schema_rejects_inconsistent_rows(tmp_path: Path) -> None:
    base: dict[str, Any] = {
        "example_id": "x", "judge": "faithfulness", "query": "q", "annotator": "author",
        "annotation_date": "2026-10-26", "chunks": [{"chunk_id": "d:c000", "text": "t"}],
        "answer": "a", "claims": [{"claim": "c", "supported": True}, {"claim": "d", "supported": False}],
        "faithfulness_band": [1.0, 1.0],  # band does not contain 0.5
    }
    with pytest.raises(ValueError):
        JudgeExample.model_validate(base)
    with pytest.raises(ValueError):
        JudgeExample.model_validate({**base, "judge": "contradiction", "contradicts": None})
    bad = tmp_path / "bad.jsonl"
    bad.write_text(json.dumps({**base, "faithfulness_band": [0.5, 0.5]}) + "\n" + json.dumps({**base, "faithfulness_band": [0.5, 0.5]}) + "\n")
    with pytest.raises(JudgeLabelsValidationError, match="duplicate"):
        load_judge_labels(bad)


def test_select_examples_interleaves_judges() -> None:
    examples, _ = load_judge_labels(default_labels_path())
    picked = select_examples(examples, 6)
    assert len(picked) == 6
    assert {e.judge for e in picked} == set(JUDGE_TYPES)
    assert select_examples(examples, None) == examples


# --------------------------------------------------------------------------- #
# Prompt variants
# --------------------------------------------------------------------------- #


def test_prompt_variants_are_versioned_and_distinct() -> None:
    for judge in JUDGE_TYPES:
        assert available_variants(judge) == ["v1", "v1b", "v1c"]
        shas = {prompt_sha256(judge, v) for v in available_variants(judge)}
        assert len(shas) == 3
    assert get_system_prompt("relevance", "v1") == relevance.SYSTEM
    assert get_system_prompt("faithfulness", "v1") == faithfulness.SYSTEM
    assert get_system_prompt("contradiction", "v1") == contradiction.SYSTEM
    assert prompt_version("relevance", "v1") == relevance.RELEVANCE_PROMPT_VERSION == "relevance.v1"
    assert prompt_version("faithfulness", "v1b") == "faithfulness.v1b"
    desc = describe_variants(["v1", "v1c"])
    assert set(desc["contradiction"]) == {"v1", "v1c"}
    assert desc["relevance"]["v1"]["sha256"].startswith("sha256:")
    with pytest.raises(KeyError):
        get_system_prompt("relevance", "v9")
    # the offline fake detects judge type from the system prompt; variants must stay detectable
    for judge in JUDGE_TYPES:
        for v in available_variants(judge):
            assert detect_judge_type([{"role": "system", "content": get_system_prompt(judge, v)}]) == judge


def test_build_messages_swaps_only_system_prompt() -> None:
    ex = JudgeExample(
        example_id="e", judge="faithfulness", query="q?", annotator="author", annotation_date="2026-10-26",
        chunks=[{"chunk_id": "d:c000", "text": "ctx"}], answer="ans",
        claims=[{"claim": "c", "supported": True}], faithfulness_band=[1.0, 1.0],
    )
    prod = faithfulness.build_faithfulness_messages("q?", "ans", [{"chunk_id": "d:c000", "text": "ctx"}])
    v1 = build_messages("faithfulness", ex, "v1")
    v1b = build_messages("faithfulness", ex, "v1b")
    assert v1 == prod
    assert v1b[1] == prod[1] and v1b[0]["content"] == get_system_prompt("faithfulness", "v1b")


# --------------------------------------------------------------------------- #
# Offline providers
# --------------------------------------------------------------------------- #


class OracleJudgeLLM:
    """Answers every judge call with the labeled truth for the example in the prompt."""

    def __init__(self, examples: list[JudgeExample], *, flip_contradiction_on_variant: str | None = None) -> None:
        self.examples = examples
        self.flip_variant = flip_contradiction_on_variant
        self.calls = 0

    def _find(self, user: str) -> JudgeExample:
        matches = [e for e in self.examples if f"<question>\n{e.query}\n</question>" in user]
        if "<answer>" in user:
            matches = [e for e in matches if e.answer and f"<answer>\n{e.answer}\n</answer>" in user] or matches
        assert matches, "oracle could not locate example in prompt"
        return matches[0]

    def complete(self, messages, *, model, timeout) -> LLMResult:  # noqa: ANN001
        self.calls += 1
        judge = detect_judge_type(messages)
        ex = self._find(messages[-1]["content"] if messages[-1]["role"] == "user" else messages[1]["content"])
        if judge == "relevance":
            items = [
                {"chunk_id": c.chunk_id, "relevant": bool(c.relevant) if c.relevant is not None else True,
                 "score": c.label_score if c.relevant is not None else 1.0, "rationale": "oracle"}
                for c in ex.chunks
            ]
            body = {"items": items, "context_sufficient": ex.context_sufficient if ex.context_sufficient is not None else True}
        elif judge == "faithfulness":
            if ex.claims:
                claims = [{"claim": c.claim, "supported": c.supported, "supporting_chunk_ids": [ex.chunks[0].chunk_id] if c.supported else []} for c in ex.claims]
                score = ex.labeled_faithfulness_score
            else:  # contradiction example: consistent with its label
                bad = bool(ex.contradicts)
                claims = [{"claim": ex.answer or "", "supported": not bad, "supporting_chunk_ids": [] if bad else [ex.chunks[0].chunk_id]}]
                score = 0.0 if bad else 1.0
            body = {"faithfulness_score": score, "claims": claims}
        else:
            contradicts = bool(ex.contradicts) if ex.contradicts is not None else False
            if self.flip_variant and messages[0]["content"] == get_system_prompt("contradiction", self.flip_variant):
                contradicts = not contradicts
            body = {"contradicts": contradicts, "explanation": "oracle", "chunk_ids": [ex.chunks[0].chunk_id] if contradicts else []}
        return LLMResult(content=json.dumps(body), model=model, latency_ms=2.0)


def _subset() -> list[JudgeExample]:
    examples, _ = load_judge_labels(default_labels_path())
    picked: list[JudgeExample] = []
    seen_queries: set[str] = set()
    for ex in select_examples(examples, len(examples)):
        if ex.query in seen_queries:
            continue
        seen_queries.add(ex.query)
        picked.append(ex)
    picked = [e for e in picked if e.judge == "relevance"][:4] + [e for e in picked if e.judge == "faithfulness"][:4] + [e for e in picked if e.judge == "contradiction"][:4]
    assert len(picked) == 12
    return picked


def test_validate_judges_perfect_oracle_gives_kappa_one() -> None:
    examples = _subset()
    oracle = OracleJudgeLLM(examples)
    previous = get_llm_provider.__module__  # noqa: F841 - sanity that import works
    report = validate_judges(oracle, examples, "v1", variants=["v1", "v1b"], include_consistency=True)

    rel = report["per_judge"]["relevance"]["v1"]
    assert rel["chunk_relevant"]["accuracy"] == 1.0 and rel["chunk_relevant"]["kappa"] == 1.0
    assert rel["context_sufficient"]["accuracy"] == 1.0 and rel["score_mae"] == 0.0
    fai = report["per_judge"]["faithfulness"]["v1"]
    assert fai["has_unsupported_claim"]["kappa"] == 1.0 and fai["score_mae"] == 0.0 and fai["score_in_band_rate"] == 1.0
    con = report["per_judge"]["contradiction"]["v1"]
    assert con["contradicts"]["accuracy"] == 1.0 and con["contradicts"]["kappa"] == 1.0
    for judge in JUDGE_TYPES:
        for variant in ("v1", "v1b"):
            r = report["per_judge"][judge][variant]["reliability"]
            assert r["schema_failure_rate"] == 0.0 and r["error_rate"] == 0.0 and r["mean_latency_ms"] == 2.0
    # sensitivity: identical answers for both variants
    for judge in JUDGE_TYPES:
        s = report["sensitivity"][judge]["v1|v1b"]
        assert s["flip_rate"] == 0.0 and s["kappa"] == 1.0 and s["n_units"] > 0
    # consistency: the oracle is self-consistent
    assert all(v == 0 for v in report["consistency"]["counts"].values())
    assert report["consistency"]["examples_with_faithfulness_and_contradiction"] == 8
    # provenance
    assert report["model"]["temperature"] == 0.0 and report["model"]["provider"] == "OracleJudgeLLM"
    assert report["prompts"]["relevance"]["v1"]["prompt_version"] == "relevance.v1"
    assert report["examples"]["example_set_hash"] == compute_examples_hash(examples)
    assert report["variants"] == ["v1", "v1b"] and report["generated_at"]
    # call accounting: 12 examples x 2 variants + consistency (8 answered examples x 2 other judges)
    assert oracle.calls == 12 * 2 + 8 * 2
    assert get_llm_provider().__class__.__name__ != "OracleJudgeLLM", "provider override must be restored"

    md = format_markdown(report, source_label="fixture (OracleJudgeLLM), not a live model")
    assert "fixture (OracleJudgeLLM)" in md and "| relevance | v1 |" in md and "Prompt sensitivity" in md


def test_validate_judges_detects_prompt_sensitivity_flips() -> None:
    examples = _subset()
    oracle = OracleJudgeLLM(examples, flip_contradiction_on_variant="v1b")
    report = validate_judges(oracle, examples, "v1", variants=["v1", "v1b"], include_consistency=False)
    con = report["sensitivity"]["contradiction"]["v1|v1b"]
    assert con["flip_rate"] == 1.0 and con["kappa"] <= 0.0
    assert report["sensitivity"]["relevance"]["v1|v1b"]["flip_rate"] == 0.0
    # v1b contradiction accuracy is the mirror image of v1
    assert report["per_judge"]["contradiction"]["v1"]["contradicts"]["accuracy"] == 1.0
    assert report["per_judge"]["contradiction"]["v1b"]["contradicts"]["accuracy"] == 0.0
    assert report["consistency"] is None


def test_validate_judges_with_scripted_imperfect_outputs() -> None:
    examples, _ = load_judge_labels(default_labels_path())
    cons = [e for e in examples if e.judge == "contradiction"][:2]
    rels = [e for e in examples if e.judge == "relevance"][:1]
    fais = [e for e in examples if e.judge == "faithfulness"][:1]
    assert cons[0].contradicts is True and cons[1].contradicts is False  # con_001 / con_002
    rel_ex, fai_ex = rels[0], fais[0]
    assert fai_ex.labeled_faithfulness_score == 1.0  # fai_001 fully supported

    scripted = ScriptedJudgeLLM(
        {
            # ex1: two malformed attempts -> schema failure; ex2: predicts True (label False)
            "contradiction": ["not json", "still not json", contradiction_json(True)],
            # all chunks relevant, sufficient=True; label says chunk 2 is irrelevant
            "relevance": [relevance_json([c.chunk_id for c in rel_ex.chunks], sufficient=True, relevant=True, score=0.9)],
            # claims one supported + one unsupported -> score 0.5 vs label 1.0
            "faithfulness": [faithfulness_json(score=0.5, supported=1, unsupported=1)],
        }
    )
    report = validate_judges(scripted, cons + rels + fais, "v1", include_consistency=False)

    con = report["per_judge"]["contradiction"]["v1"]
    assert con["reliability"]["schema_failure_rate"] == 0.5 and con["reliability"]["retry_rate"] == 0.0
    assert con["contradicts"]["n"] == 1 and con["contradicts"]["accuracy"] == 0.0
    rel = report["per_judge"]["relevance"]["v1"]
    labels = [bool(c.relevant) for c in rel_ex.chunks]
    assert rel["chunk_relevant"]["accuracy"] == pytest.approx(sum(labels) / len(labels))
    assert rel["chunk_relevant"]["recall"] == 1.0 and rel["context_sufficient"]["accuracy"] == 1.0
    assert rel["score_mae"] == pytest.approx(sum(abs(0.9 - (1.0 if l else 0.0)) for l in labels) / len(labels))
    fai = report["per_judge"]["faithfulness"]["v1"]
    assert fai["score_mae"] == 0.5 and fai["score_in_band_rate"] == 0.0
    assert fai["has_unsupported_claim"]["accuracy"] == 0.0
    assert report["sensitivity"] == {}
    assert report["reliability_all_calls"]["n_calls"] == 4


def test_cli_has_judges_validate_subcommand() -> None:
    args = build_parser().parse_args(["judges", "validate", "--limit", "3", "--variants", "v1,v1c"])
    assert args.command == "judges" and args.judges_command == "validate"
    assert args.limit == 3 and args.variants == "v1,v1c"
    assert args.func.__name__ == "cmd_judges_validate"
    assert Path(args.labels).name == "judge_labels_v1.jsonl"
