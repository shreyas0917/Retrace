"""Retrieval metrics, qrels dataset integrity, BM25/RRF, and the ablation runner (offline)."""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from app.cli.retrace import build_parser
from app.services.metrics.retrieval import (
    aggregate,
    evaluate_ranking,
    hit_rate_at_k,
    mrr,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
)
from app.services import retrieval_eval as re_mod
from app.services.retrieval_eval import (
    BM25Index,
    DenseIndex,
    MAX_MUST_CONTAIN_CHARS,
    QrelsValidationError,
    RetrievalQuery,
    build_chunks,
    check_qrels_against_corpus,
    default_qrels_path,
    format_markdown,
    load_corpus_dir,
    load_qrels,
    normalize_text,
    parse_configs,
    relevant_chunk_ids,
    rrf_fuse,
    run_retrieval_ablation,
    tokenize,
)

DATASET_DIR = Path(__file__).resolve().parents[1] / "datasets" / "retrieval"


def _demo_corpus_dir() -> Path:
    for candidate in (
        Path(__file__).resolve().parents[2] / "data" / "corpus" / "demo",
        Path("/data/corpus/demo"),
    ):
        if candidate.is_dir() and list(candidate.glob("*.md")):
            return candidate
    pytest.skip("demo corpus directory not available")


# --------------------------------------------------------------------------- #
# Metric math (hand-computed)
# --------------------------------------------------------------------------- #


def test_recall_precision_hit_rate_hand_values() -> None:
    ranked = ["a", "b", "c", "d"]
    relevant = {"a", "c"}
    assert recall_at_k(ranked, relevant, 1) == 0.5
    assert recall_at_k(ranked, relevant, 3) == 1.0
    assert precision_at_k(ranked, relevant, 3) == pytest.approx(2 / 3)
    assert precision_at_k(ranked, relevant, 10) == pytest.approx(2 / 10)
    assert hit_rate_at_k(ranked, relevant, 1) == 1.0
    assert hit_rate_at_k(["x", "y"], relevant, 2) == 0.0


def test_mrr_hand_values() -> None:
    assert mrr(["a", "b"], {"a"}) == 1.0
    assert mrr(["x", "a", "y", "c"], {"a", "c"}) == 0.5
    assert mrr(["x", "y"], {"a"}) == 0.0


def test_ndcg_hand_values() -> None:
    ranked = ["x", "a", "y", "c"]
    relevant = {"a", "c"}
    idcg3 = 1.0 + 1.0 / math.log2(3)
    assert ndcg_at_k(ranked, relevant, 3) == pytest.approx((1.0 / math.log2(3)) / idcg3)
    dcg4 = 1.0 / math.log2(3) + 1.0 / math.log2(5)
    assert ndcg_at_k(ranked, relevant, 4) == pytest.approx(dcg4 / idcg3)
    assert ndcg_at_k(["a", "c"], relevant, 5) == pytest.approx(1.0)
    assert ndcg_at_k(["x"], relevant, 5) == 0.0


def test_empty_relevant_returns_none_and_k_validation() -> None:
    assert recall_at_k(["a"], set(), 1) is None
    assert mrr(["a"], set()) is None
    assert ndcg_at_k(["a"], set(), 1) is None
    with pytest.raises(ValueError):
        precision_at_k(["a"], {"a"}, 0)


def test_evaluate_ranking_and_aggregate() -> None:
    rows = [
        evaluate_ranking(["a", "b"], {"a"}, ks=(1, 2)),
        evaluate_ranking(["b", "a"], {"a"}, ks=(1, 2)),
        evaluate_ranking(["b"], set(), ks=(1, 2)),  # unanswerable -> all None
    ]
    assert rows[0]["recall@1"] == 1.0 and rows[1]["recall@1"] == 0.0
    agg = aggregate(rows)
    assert agg["n"] == 3
    assert agg["recall@1"] == pytest.approx(0.5)  # None ignored
    assert agg["mrr"] == pytest.approx(0.75)
    assert aggregate([{"x": None}])["x"] is None


# --------------------------------------------------------------------------- #
# Dataset integrity
# --------------------------------------------------------------------------- #


def test_qrels_load_matches_manifest_and_corpus() -> None:
    queries, qrels_hash = load_qrels(default_qrels_path())
    manifest = json.loads((DATASET_DIR / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["dataset_hash"] == qrels_hash
    assert manifest["query_count"] == len(queries) >= 60
    unanswerable = [q for q in queries if not q.answerable]
    assert len(unanswerable) == manifest["unanswerable"] == 5
    assert {q.difficulty for q in queries} == {"easy", "medium", "hard"}
    assert any(len(q.relevant_document_ids) > 1 for q in queries), "needs multi-doc queries"
    assert all(len(normalize_text(s.must_contain)) <= MAX_MUST_CONTAIN_CHARS for q in queries for s in q.relevant)

    docs = load_corpus_dir(_demo_corpus_dir())
    assert len(docs) >= 12
    assert check_qrels_against_corpus(queries, docs) == []


def test_qrels_schema_rejects_bad_rows(tmp_path: Path) -> None:
    bad = tmp_path / "bad.jsonl"
    bad.write_text(
        json.dumps({"query_id": "q1", "query": "hello?", "relevant": [], "difficulty": "trivial", "tags": []}) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(QrelsValidationError):
        load_qrels(bad)
    with pytest.raises(ValueError):
        RetrievalQuery(
            query_id="q", query="long?", difficulty="easy",
            relevant=[{"document_id": "d", "must_contain": "x" * (MAX_MUST_CONTAIN_CHARS + 1)}],
        )


def test_relevance_is_chunking_independent() -> None:
    docs = [("doc", "alpha " * 100 + "the magic phrase here " + "beta " * 100)]
    q = RetrievalQuery(query_id="q", query="magic?", difficulty="easy",
                       relevant=[{"document_id": "doc", "must_contain": "MAGIC   phrase"}])
    for size, overlap in ((64, 32), (256, 32), (512, 64)):
        chunks = build_chunks(docs, size, overlap)
        rel = relevant_chunk_ids(q, chunks)
        assert rel, f"substring must survive chunking at {size}/{overlap}"
        assert all(cid.startswith("doc:c") for cid in rel)


# --------------------------------------------------------------------------- #
# Retrievers
# --------------------------------------------------------------------------- #


def test_tokenizer_and_bm25_ranks_exact_term_first() -> None:
    assert tokenize("Form EXP-7 ($25)") == ["form", "exp", "7", "25"]
    texts = [
        "Hotel rates are capped at $250 per night for domestic travel.",
        "Passwords must be rotated every 180 days and stored in Vaultkeeper.",
        "Expense reports must be submitted within 45 days of the expense.",
    ]
    index = BM25Index(texts)
    assert index.rank("which password manager is Vaultkeeper")[0] == 1
    assert index.rank("hotel rate cap per night")[0] == 0
    scores = index.scores("zzz unknown words")
    assert np.all(scores == 0.0)


def test_rrf_fusion_prefers_consensus() -> None:
    dense = [0, 1, 2]
    bm25 = [1, 0, 2]
    fused = rrf_fuse([dense, bm25], k=60)
    assert fused[:2] in ([0, 1], [1, 0]) and fused[2] == 2
    assert rrf_fuse([[2, 0], [2, 1]])[0] == 2


def _fake_embed(texts):
    """Deterministic bag-of-hashed-words embedding (no model needed)."""
    import zlib

    out = np.zeros((len(texts), 64), dtype=np.float32)
    for i, text in enumerate(texts):
        for tok in tokenize(text):
            # Stable across processes (built-in str hash is salted per process,
            # which made token collisions, and this test, non-deterministic).
            out[i, zlib.crc32(tok.encode("utf-8")) % 64] += 1.0
    return out


def test_dense_index_exact_cosine() -> None:
    texts = ["refund within 30 days", "password rotation 180 days", "refund refund refund"]
    index = DenseIndex(texts, _fake_embed)
    assert np.allclose(np.linalg.norm(index.matrix, axis=1), 1.0)
    assert index.rank("refund")[0] in (0, 2)
    assert index.rank("password")[0] == 1


def test_parse_configs() -> None:
    assert parse_configs("256:32, 512:64") == [(256, 32), (512, 64)]
    with pytest.raises(ValueError):
        parse_configs("100:100")


# --------------------------------------------------------------------------- #
# Ablation runner end-to-end on a tiny corpus with a fake embedder
# --------------------------------------------------------------------------- #


def _tiny_corpus(tmp_path: Path) -> tuple[Path, Path]:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "pto.md").write_text(
        "# PTO\n\nFull-time employees accrue 1.25 days of PTO per month. " + "Filler sentence about calendars. " * 20,
        encoding="utf-8",
    )
    (corpus / "refund.md").write_text(
        "# Refunds\n\nCustomers may request a refund within 30 days of purchase. " + "Filler about packaging. " * 20,
        encoding="utf-8",
    )
    (corpus / "passwords.md").write_text(
        "# Passwords\n\nPasswords must be at least 14 characters long. " + "Filler about Vaultkeeper. " * 20,
        encoding="utf-8",
    )
    rows = [
        {"query_id": "q1", "query": "How much PTO accrues per month?", "difficulty": "easy", "tags": [],
         "relevant": [{"document_id": "pto", "must_contain": "1.25 days of PTO per month"}]},
        {"query_id": "q2", "query": "refund window after purchase", "difficulty": "medium", "tags": [],
         "relevant": [{"document_id": "refund", "must_contain": "within 30 days of purchase"}]},
        {"query_id": "q3", "query": "minimum password length characters", "difficulty": "hard", "tags": [],
         "relevant": [{"document_id": "passwords", "must_contain": "at least 14 characters"}]},
        {"query_id": "q4", "query": "pet policy at the office", "difficulty": "hard", "tags": ["unanswerable"],
         "relevant": []},
    ]
    qrels = tmp_path / "qrels.jsonl"
    qrels.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return corpus, qrels


def test_run_retrieval_ablation_end_to_end(tmp_path: Path) -> None:
    corpus, qrels = _tiny_corpus(tmp_path)

    def failing_loader(name: str):
        raise RuntimeError("no network in tests")

    report = run_retrieval_ablation(
        corpus, qrels,
        configs=[(128, 16), (512, 64)],
        ks=(1, 3, 5, 10),
        embedding_models=["BAAI/bge-small-en-v1.5"],
        embed_fn=_fake_embed,
        load_extra_model=failing_loader,
    )
    assert report["qrels"]["answerable"] == 3 and report["qrels"]["unanswerable"] == 1
    assert report["embedding_models"]["BAAI/bge-small-en-v1.5"]["status"] == "not run"
    assert "no network" in report["embedding_models"]["BAAI/bge-small-en-v1.5"]["error"]
    rows = report["results"]
    assert len(rows) == 2 * 3  # 2 configs x (bm25, dense, hybrid)
    assert {r["retriever"] for r in rows} == {"bm25", "dense", "hybrid_rrf"}
    for row in rows:
        assert row["n_queries"] == 3 and row["unmatched_queries"] == []
        for key in ("recall@1", "recall@5", "mrr", "ndcg@5", "ndcg@10", "hit_rate@1"):
            assert 0.0 <= row["metrics"][key] <= 1.0
        assert set(row["by_difficulty"]) == {"easy", "medium", "hard"}
        assert row["mean_latency_ms"] >= 0.0
    # Keyword-exact queries on a 3-doc corpus: BM25 must find them.
    bm25_prod = next(r for r in rows if r["retriever"] == "bm25" and r["config"] == "512/64")
    assert bm25_prod["metrics"]["recall@5"] == 1.0
    assert bm25_prod["is_production_config"] is True
    assert report["chunk_counts"]["128/16"] > report["chunk_counts"]["512/64"]
    assert len(report["worst_queries_production_dense"]) == 3
    assert report["abstention_production_config"]["bm25"]["unanswerable"][0]["query_id"] == "q4"

    md = format_markdown(report, existing_markdown="x\n<!-- interpretation:start -->\nKEEP ME\n<!-- interpretation:end -->")
    assert "| config | retriever |" in md and "KEEP ME" in md
    assert "**[production]**" in md


def test_ablation_rejects_qrels_not_matching_corpus(tmp_path: Path) -> None:
    corpus, qrels = _tiny_corpus(tmp_path)
    qrels.write_text(
        json.dumps({"query_id": "q", "query": "x?", "difficulty": "easy", "tags": [],
                    "relevant": [{"document_id": "pto", "must_contain": "not in the doc"}]}) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(QrelsValidationError):
        run_retrieval_ablation(corpus, qrels, configs=[(512, 64)], embed_fn=_fake_embed)


def test_cli_has_retrieval_eval_subcommand() -> None:
    args = build_parser().parse_args(["retrieval-eval", "--configs", "256:32", "--out", "x.json"])
    assert args.command == "retrieval-eval" and args.configs == "256:32"
    assert args.func.__name__ == "cmd_retrieval_eval"
    assert Path(args.qrels).name == "demo_qrels_v1.jsonl"
    assert re_mod.PRODUCTION_CONFIG == (512, 64)
