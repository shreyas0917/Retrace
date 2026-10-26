"""Retrieval ablation: chunking x retriever grid scored against chunking-independent qrels.

Why this exists: "we use embeddings + Chroma" is not evidence that retrieval
works. This module measures Recall@k, MRR and nDCG for several chunking
configurations and three retrievers (dense cosine, BM25, hybrid RRF) on the
same query set, so the production configuration can be compared to
alternatives with numbers instead of intuition.

Relevance is defined independently of chunking so that one qrels file serves
every chunk size: a chunk is relevant for a query iff its ``document_id``
matches one of the query's relevant spans AND the normalized chunk text
contains the normalized ``must_contain`` substring (case- and
whitespace-insensitive). ``must_contain`` is capped at
``MAX_MUST_CONTAIN_CHARS`` (32) so that it always fits inside the overlap of the
smallest configuration in the grid (256/32) and therefore appears intact in at
least one chunk for every configuration; the runner still reports any query
that ends up with zero matching chunks ("unmatched") and excludes it from
means rather than silently scoring it as a miss.

Dense scoring is exact brute-force cosine similarity in numpy over normalized
vectors. The production path (``app.services.retrieval``) uses Chroma's HNSW
index with the cosine space on the same normalized vectors and reports
``score = 1 - distance``; for a corpus of this size HNSW returns the exact
neighbours, so the two are equivalent up to ANN approximation at larger scale.
"""

from __future__ import annotations

import math
import re
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal, Sequence

import numpy as np
from pydantic import BaseModel, Field, field_validator

from app.core.logging import get_logger
from app.services import embeddings as embeddings_service
from app.services.chunking import DEFAULT_CHUNKING_CONFIG, chunk_text, make_chunk_id
from app.services.eval.suite_loader import compute_suite_hash
from app.services.metrics.retrieval import DEFAULT_KS, aggregate, evaluate_ranking

logger = get_logger(__name__)

MAX_MUST_CONTAIN_CHARS = 32
DEFAULT_CONFIGS: tuple[tuple[int, int], ...] = ((256, 32), (512, 64), (1024, 128))
PRODUCTION_CONFIG: tuple[int, int] = (
    int(DEFAULT_CHUNKING_CONFIG["chunk_size"]),
    int(DEFAULT_CHUNKING_CONFIG["chunk_overlap"]),
)
DEFAULT_EMBEDDING_MODEL = embeddings_service._PRD_MODEL  # noqa: SLF001
RRF_K = 60
BM25_K1 = 1.5
BM25_B = 0.75

EmbedFn = Callable[[Sequence[str]], np.ndarray]


# --------------------------------------------------------------------------- #
# Dataset schema + loading
# --------------------------------------------------------------------------- #


def normalize_text(text: str) -> str:
    """Lowercase and collapse all whitespace runs to one space."""
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


class RelevantSpan(BaseModel):
    document_id: str = Field(min_length=1)
    must_contain: str = Field(min_length=3)

    @field_validator("must_contain")
    @classmethod
    def _short_enough(cls, value: str) -> str:
        norm = normalize_text(value)
        if len(norm) > MAX_MUST_CONTAIN_CHARS:
            raise ValueError(
                f"must_contain must be <= {MAX_MUST_CONTAIN_CHARS} normalized chars "
                f"(got {len(norm)}): {value!r}"
            )
        return value


class RetrievalQuery(BaseModel):
    query_id: str = Field(min_length=1)
    query: str = Field(min_length=3)
    relevant: list[RelevantSpan] = Field(default_factory=list)
    difficulty: Literal["easy", "medium", "hard"]
    tags: list[str] = Field(default_factory=list)

    @property
    def answerable(self) -> bool:
        return bool(self.relevant)

    @property
    def relevant_document_ids(self) -> set[str]:
        return {span.document_id for span in self.relevant}


class QrelsValidationError(ValueError):
    pass


def load_qrels(path: str | Path) -> tuple[list[RetrievalQuery], str]:
    """Load + validate a qrels JSONL file. Returns (queries, sha256 hash)."""
    path = Path(path)
    if not path.is_file():
        raise QrelsValidationError(f"qrels file not found: {path}")
    raw_lines = path.read_text(encoding="utf-8").splitlines()
    queries: list[RetrievalQuery] = []
    seen: set[str] = set()
    for lineno, line in enumerate(raw_lines, start=1):
        if not line.strip():
            continue
        try:
            q = RetrievalQuery.model_validate_json(line)
        except Exception as exc:  # noqa: BLE001
            raise QrelsValidationError(f"{path}:{lineno}: {exc}") from exc
        if q.query_id in seen:
            raise QrelsValidationError(f"{path}:{lineno}: duplicate query_id {q.query_id}")
        seen.add(q.query_id)
        queries.append(q)
    if not queries:
        raise QrelsValidationError(f"qrels file is empty: {path}")
    return queries, compute_suite_hash(raw_lines)


def default_qrels_path() -> Path:
    here = Path(__file__).resolve()
    return here.parents[2] / "datasets" / "retrieval" / "demo_qrels_v1.jsonl"


def load_corpus_dir(corpus_dir: str | Path) -> list[tuple[str, str]]:
    """``(document_id, text)`` for every ``*.md`` in the directory (id = file stem)."""
    corpus_dir = Path(corpus_dir)
    docs = [
        (path.stem, path.read_text(encoding="utf-8"))
        for path in sorted(corpus_dir.glob("*.md"))
    ]
    if not docs:
        raise QrelsValidationError(f"no markdown documents in {corpus_dir}")
    return docs


def check_qrels_against_corpus(
    queries: Sequence[RetrievalQuery], docs: Sequence[tuple[str, str]]
) -> list[str]:
    """Return human-readable problems (unknown doc ids, substrings not in the doc)."""
    by_id = {doc_id: normalize_text(text) for doc_id, text in docs}
    problems: list[str] = []
    for q in queries:
        for span in q.relevant:
            doc = by_id.get(span.document_id)
            if doc is None:
                problems.append(f"{q.query_id}: unknown document_id {span.document_id}")
            elif normalize_text(span.must_contain) not in doc:
                problems.append(
                    f"{q.query_id}: {span.must_contain!r} not found in {span.document_id}"
                )
    return problems


def parse_configs(spec: str) -> list[tuple[int, int]]:
    """``"256:32,512:64"`` -> ``[(256, 32), (512, 64)]``."""
    configs: list[tuple[int, int]] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        size_s, _, overlap_s = part.partition(":")
        size, overlap = int(size_s), int(overlap_s or 0)
        if size <= 0 or overlap < 0 or overlap >= size:
            raise ValueError(f"invalid chunking config '{part}'")
        configs.append((size, overlap))
    if not configs:
        raise ValueError("no chunking configs given")
    return configs


# --------------------------------------------------------------------------- #
# Chunks and relevance
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ChunkRecord:
    chunk_id: str
    document_id: str
    text: str
    norm_text: str


def build_chunks(
    docs: Sequence[tuple[str, str]], chunk_size: int, chunk_overlap: int
) -> list[ChunkRecord]:
    records: list[ChunkRecord] = []
    for doc_id, text in docs:
        for piece in chunk_text(text, chunk_size=chunk_size, chunk_overlap=chunk_overlap):
            records.append(
                ChunkRecord(
                    chunk_id=make_chunk_id(doc_id, piece.ordinal),
                    document_id=doc_id,
                    text=piece.text,
                    norm_text=normalize_text(piece.text),
                )
            )
    return records


def relevant_chunk_ids(query: RetrievalQuery, chunks: Sequence[ChunkRecord]) -> set[str]:
    out: set[str] = set()
    for span in query.relevant:
        needle = normalize_text(span.must_contain)
        for chunk in chunks:
            if chunk.document_id == span.document_id and needle in chunk.norm_text:
                out.add(chunk.chunk_id)
    return out


# --------------------------------------------------------------------------- #
# Retrievers
# --------------------------------------------------------------------------- #

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall((text or "").lower())


class BM25Index:
    """Okapi BM25 (k1=1.5, b=0.75) over a lowercase alphanumeric tokenization.

    idf(t) = ln((N - n_t + 0.5) / (n_t + 0.5) + 1), as in Lucene / rank_bm25.
    """

    def __init__(self, texts: Sequence[str], *, k1: float = BM25_K1, b: float = BM25_B) -> None:
        self.k1 = k1
        self.b = b
        self.docs = [tokenize(t) for t in texts]
        self.n = len(self.docs)
        self.doc_lens = np.array([len(d) for d in self.docs], dtype=float)
        self.avgdl = float(self.doc_lens.mean()) if self.n else 0.0
        self.tf: list[Counter[str]] = [Counter(d) for d in self.docs]
        df: Counter[str] = Counter()
        for counts in self.tf:
            df.update(counts.keys())
        self.idf = {
            term: math.log((self.n - n_t + 0.5) / (n_t + 0.5) + 1.0) for term, n_t in df.items()
        }

    def scores(self, query: str) -> np.ndarray:
        out = np.zeros(self.n, dtype=float)
        if self.n == 0:
            return out
        for term in tokenize(query):
            idf = self.idf.get(term)
            if idf is None:
                continue
            for i, counts in enumerate(self.tf):
                f = counts.get(term, 0)
                if not f:
                    continue
                denom = f + self.k1 * (1.0 - self.b + self.b * self.doc_lens[i] / self.avgdl)
                out[i] += idf * f * (self.k1 + 1.0) / denom
        return out

    def rank(self, query: str) -> list[int]:
        return _argsort_desc(self.scores(query))


def _argsort_desc(scores: np.ndarray) -> list[int]:
    # Stable: ties keep index order so results are deterministic.
    return [int(i) for i in np.argsort(-scores, kind="stable")]


class DenseIndex:
    """Exact cosine similarity over L2-normalized embeddings (brute force)."""

    def __init__(self, texts: Sequence[str], embed_fn: EmbedFn) -> None:
        self.embed_fn = embed_fn
        matrix = np.asarray(embed_fn(list(texts)), dtype=np.float32)
        if matrix.ndim != 2 or matrix.shape[0] != len(texts):
            raise ValueError("embed_fn must return one vector per text")
        self.matrix = _l2_normalize(matrix)

    def scores(self, query: str) -> np.ndarray:
        q = _l2_normalize(np.asarray(self.embed_fn([query]), dtype=np.float32))[0]
        return self.matrix @ q

    def rank(self, query: str) -> list[int]:
        return _argsort_desc(self.scores(query))


def _l2_normalize(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


def rrf_fuse(rankings: Sequence[Sequence[int]], *, k: int = RRF_K) -> list[int]:
    """Reciprocal rank fusion: score(d) = sum over lists of 1 / (k + rank)."""
    fused: dict[int, float] = defaultdict(float)
    for ranking in rankings:
        for rank, idx in enumerate(ranking, start=1):
            fused[idx] += 1.0 / (k + rank)
    return sorted(fused, key=lambda idx: (-fused[idx], idx))


def default_embed_fn(texts: Sequence[str]) -> np.ndarray:
    """Project embedder (Settings-locked MiniLM, normalized)."""
    return np.asarray(embeddings_service.embed_texts(list(texts)), dtype=np.float32)


def make_sentence_transformer_embed_fn(model_name: str) -> EmbedFn:
    """Load an arbitrary sentence-transformers model directly (bypasses Settings lock).

    Only used for ablations; the production embedder stays PRD-locked.
    """
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(model_name)

    def _embed(texts: Sequence[str]) -> np.ndarray:
        return np.asarray(
            model.encode(
                list(texts),
                show_progress_bar=False,
                convert_to_numpy=True,
                normalize_embeddings=True,
            ),
            dtype=np.float32,
        )

    return _embed


# --------------------------------------------------------------------------- #
# Ablation runner
# --------------------------------------------------------------------------- #


def _mean(values: Sequence[float]) -> float | None:
    return (sum(values) / len(values)) if values else None


def _round_metrics(metrics: dict[str, Any], digits: int = 4) -> dict[str, Any]:
    return {
        key: (round(value, digits) if isinstance(value, float) else value)
        for key, value in metrics.items()
    }


def run_retrieval_ablation(
    corpus_dir: str | Path,
    qrels_path: str | Path,
    configs: Sequence[tuple[int, int]] = DEFAULT_CONFIGS,
    ks: Sequence[int] = DEFAULT_KS,
    embedding_models: Sequence[str] | None = None,
    *,
    embed_fn: EmbedFn | None = None,
    production_config: tuple[int, int] = PRODUCTION_CONFIG,
    worst_n: int = 5,
    load_extra_model: Callable[[str], EmbedFn] = make_sentence_transformer_embed_fn,
) -> dict[str, Any]:
    """Evaluate every (chunking config, retriever) pair on the same qrels.

    ``embed_fn`` overrides the default project embedder (tests pass a fake).
    Extra ``embedding_models`` are loaded directly from sentence-transformers;
    a model that cannot be loaded (e.g. no network) is recorded as
    ``"not run"`` with the error and never produces fabricated numbers.
    """
    started = time.perf_counter()
    docs = load_corpus_dir(corpus_dir)
    queries, qrels_hash = load_qrels(qrels_path)
    problems = check_qrels_against_corpus(queries, docs)
    if problems:
        raise QrelsValidationError("qrels do not match corpus: " + "; ".join(problems[:10]))

    ks = tuple(int(k) for k in ks)
    max_k = max(ks)
    answerable = [q for q in queries if q.answerable]
    unanswerable = [q for q in queries if not q.answerable]

    # Embedding models: default first, then extras (best effort).
    embedders: list[tuple[str, EmbedFn]] = [
        (DEFAULT_EMBEDDING_MODEL, embed_fn or default_embed_fn)
    ]
    model_status: dict[str, dict[str, Any]] = {
        DEFAULT_EMBEDDING_MODEL: {"status": "ok", "source": "project embedder (Settings-locked)"}
    }
    for name in embedding_models or []:
        if name == DEFAULT_EMBEDDING_MODEL or name in model_status:
            continue
        try:
            fn = load_extra_model(name)
            embedders.append((name, fn))
            model_status[name] = {"status": "ok", "source": "sentence-transformers direct load"}
        except Exception as exc:  # noqa: BLE001
            logger.warning("ablation_embedding_model_not_run", model=name, error=str(exc)[:300])
            model_status[name] = {"status": "not run", "error": str(exc)[:300]}

    rows: list[dict[str, Any]] = []
    worst_queries: list[dict[str, Any]] = []
    abstention: dict[str, Any] = {}
    per_config_chunks: dict[str, int] = {}

    for chunk_size, chunk_overlap in configs:
        chunks = build_chunks(docs, chunk_size, chunk_overlap)
        config_key = f"{chunk_size}/{chunk_overlap}"
        per_config_chunks[config_key] = len(chunks)
        texts = [c.text for c in chunks]
        is_production = (chunk_size, chunk_overlap) == tuple(production_config)

        relevant_by_query = {q.query_id: relevant_chunk_ids(q, chunks) for q in answerable}
        unmatched = [q.query_id for q in answerable if not relevant_by_query[q.query_id]]
        scored_queries = [q for q in answerable if relevant_by_query[q.query_id]]

        bm25 = BM25Index(texts)
        retrievers: list[tuple[str, str | None, Callable[[str], tuple[list[int], np.ndarray | None]]]] = []

        def _bm25_run(query: str) -> tuple[list[int], np.ndarray]:
            scores = bm25.scores(query)
            return _argsort_desc(scores), scores

        retrievers.append(("bm25", None, _bm25_run))

        for model_name, fn in embedders:
            dense = DenseIndex(texts, fn)

            def _dense_run(query: str, _dense: DenseIndex = dense) -> tuple[list[int], np.ndarray]:
                scores = _dense.scores(query)
                return _argsort_desc(scores), scores

            def _hybrid_run(
                query: str, _dense: DenseIndex = dense
            ) -> tuple[list[int], np.ndarray | None]:
                d_rank = _dense.rank(query)
                b_rank = bm25.rank(query)
                return rrf_fuse([d_rank, b_rank]), None

            retrievers.append(("dense", model_name, _dense_run))
            retrievers.append(("hybrid_rrf", model_name, _hybrid_run))

        for retriever_name, model_name, run in retrievers:
            per_query: list[dict[str, Any]] = []
            per_difficulty: dict[str, list[dict[str, Any]]] = defaultdict(list)
            latencies: list[float] = []
            details: list[dict[str, Any]] = []
            answerable_top1: list[float] = []

            if scored_queries:
                run(scored_queries[0].query)  # warm-up (model/cache); not timed

            for q in scored_queries:
                t0 = time.perf_counter()
                order, scores = run(q.query)
                latencies.append((time.perf_counter() - t0) * 1000.0)
                ranked_ids = [chunks[i].chunk_id for i in order[:max_k]]
                relevant = relevant_by_query[q.query_id]
                metrics = evaluate_ranking(ranked_ids, relevant, ks=ks)
                per_query.append(metrics)
                per_difficulty[q.difficulty].append(metrics)
                if scores is not None and len(order):
                    answerable_top1.append(float(scores[order[0]]))
                first_rank = next(
                    (r for r, cid in enumerate(ranked_ids, start=1) if cid in relevant), None
                )
                details.append(
                    {
                        "query_id": q.query_id,
                        "query": q.query,
                        "difficulty": q.difficulty,
                        "relevant_chunk_ids": sorted(relevant),
                        "retrieved_top5": ranked_ids[:5],
                        "first_relevant_rank": first_rank,
                        "mrr": metrics["mrr"],
                        f"ndcg@{min(10, max_k)}": metrics.get(f"ndcg@{min(10, max_k)}"),
                    }
                )

            agg = aggregate(per_query)
            row = {
                "chunk_size": chunk_size,
                "chunk_overlap": chunk_overlap,
                "config": config_key,
                "is_production_config": is_production,
                "retriever": retriever_name,
                "embedding_model": model_name,
                "chunk_count": len(chunks),
                "n_queries": agg["n"],
                "unmatched_queries": unmatched,
                "metrics": _round_metrics({k: v for k, v in agg.items() if k != "n"}),
                "by_difficulty": {
                    diff: _round_metrics(aggregate(rows_))
                    for diff, rows_ in sorted(per_difficulty.items())
                },
                "mean_latency_ms": round(_mean(latencies) or 0.0, 3),
            }
            rows.append(row)

            if is_production:
                # Abstention diagnostics: do unanswerable queries look different?
                unans_top1: list[dict[str, Any]] = []
                for q in unanswerable:
                    order, scores = run(q.query)
                    unans_top1.append(
                        {
                            "query_id": q.query_id,
                            "query": q.query,
                            "top1_chunk_id": chunks[order[0]].chunk_id if order else None,
                            "top1_score": (
                                round(float(scores[order[0]]), 4)
                                if scores is not None and order
                                else None
                            ),
                        }
                    )
                key = retriever_name if model_name is None else f"{retriever_name}::{model_name}"
                abstention[key] = {
                    "answerable_top1_score_mean": (
                        round(_mean(answerable_top1), 4) if answerable_top1 else None
                    ),
                    "answerable_top1_score_min": (
                        round(min(answerable_top1), 4) if answerable_top1 else None
                    ),
                    "unanswerable": unans_top1,
                    "unanswerable_top1_score_mean": (
                        round(_mean([u["top1_score"] for u in unans_top1 if u["top1_score"] is not None]) or 0.0, 4)
                        if any(u["top1_score"] is not None for u in unans_top1)
                        else None
                    ),
                }
                if retriever_name == "dense" and model_name == DEFAULT_EMBEDDING_MODEL:
                    ndcg_key = f"ndcg@{min(10, max_k)}"
                    worst_queries = sorted(
                        details,
                        key=lambda d: (d["mrr"] or 0.0, d.get(ndcg_key) or 0.0, d["query_id"]),
                    )[:worst_n]

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "corpus_dir": str(corpus_dir),
        "document_count": len(docs),
        "document_ids": [doc_id for doc_id, _ in docs],
        "qrels": {
            "path": str(qrels_path),
            "hash": qrels_hash,
            "query_count": len(queries),
            "answerable": len(answerable),
            "unanswerable": len(unanswerable),
            "difficulty_counts": dict(sorted(Counter(q.difficulty for q in answerable).items())),
            "tag_counts": dict(sorted(Counter(t for q in queries for t in q.tags).items())),
            "relevance_definition": (
                "chunk relevant iff document_id matches and normalized chunk text contains "
                "normalized must_contain (case/whitespace-insensitive); "
                f"must_contain <= {MAX_MUST_CONTAIN_CHARS} chars"
            ),
        },
        "ks": list(ks),
        "configs": [f"{s}/{o}" for s, o in configs],
        "production_config": f"{production_config[0]}/{production_config[1]}",
        "chunk_counts": per_config_chunks,
        "embedding_models": model_status,
        "method": {
            "dense": "exact brute-force cosine over L2-normalized embeddings (numpy); "
            "equivalent to Chroma HNSW cosine on the same vectors up to ANN approximation",
            "bm25": f"Okapi BM25 k1={BM25_K1} b={BM25_B}, lowercase alphanumeric tokens",
            "hybrid_rrf": f"reciprocal rank fusion of dense and BM25 rankings, k={RRF_K}",
            "latency": "per-query scoring time including query embedding; excludes index build",
        },
        "results": rows,
        "worst_queries_production_dense": worst_queries,
        "abstention_production_config": abstention,
        "elapsed_seconds": round(time.perf_counter() - started, 2),
    }
    logger.info(
        "retrieval_ablation_completed",
        rows=len(rows),
        queries=len(queries),
        elapsed_seconds=report["elapsed_seconds"],
    )
    return report


# --------------------------------------------------------------------------- #
# Markdown rendering
# --------------------------------------------------------------------------- #

INTERPRETATION_START = "<!-- interpretation:start -->"
INTERPRETATION_END = "<!-- interpretation:end -->"
_DEFAULT_INTERPRETATION = (
    "_Interpretation not yet written. Edit this section between the markers; the "
    "generator preserves it on re-runs._"
)


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def _row_label(row: dict[str, Any]) -> str:
    model = row.get("embedding_model")
    short = model.split("/")[-1] if model else ""
    label = row["retriever"] + (f" ({short})" if short else "")
    if row.get("is_production_config") and row["retriever"] == "dense" and model == DEFAULT_EMBEDDING_MODEL:
        label += " **[production]**"
    return label


def extract_interpretation(existing_markdown: str | None) -> str:
    if not existing_markdown:
        return _DEFAULT_INTERPRETATION
    start = existing_markdown.find(INTERPRETATION_START)
    end = existing_markdown.find(INTERPRETATION_END)
    if start == -1 or end == -1 or end < start:
        return _DEFAULT_INTERPRETATION
    body = existing_markdown[start + len(INTERPRETATION_START) : end].strip()
    return body or _DEFAULT_INTERPRETATION


def format_markdown(report: dict[str, Any], *, existing_markdown: str | None = None) -> str:
    ks = report["ks"]
    q = report["qrels"]
    lines: list[str] = []
    lines.append("# Retrieval ablation: chunking x retriever on the demo corpus")
    lines.append("")
    lines.append(
        f"Generated {report['generated_at']} by `retrace retrieval-eval` "
        f"(elapsed {report['elapsed_seconds']}s). Numbers below are measured, not estimated; "
        "re-run the command to refresh them."
    )
    lines.append("")
    lines.append("## Dataset")
    lines.append("")
    lines.append(
        f"- Corpus: `{report['corpus_dir']}`, {report['document_count']} markdown documents "
        f"({', '.join(report['document_ids'])})."
    )
    lines.append(
        f"- Qrels: `{q['path']}` (`{q['hash']}`): {q['query_count']} queries, "
        f"{q['answerable']} answerable + {q['unanswerable']} unanswerable (abstention cases, "
        "excluded from recall means)."
    )
    diff = ", ".join(f"{k}: {v}" for k, v in q["difficulty_counts"].items())
    lines.append(f"- Difficulty mix (answerable): {diff}.")
    tags = ", ".join(f"{k}: {v}" for k, v in q["tag_counts"].items())
    lines.append(f"- Tags: {tags}.")
    lines.append(f"- Relevance definition: {q['relevance_definition']}.")
    lines.append("")
    lines.append("## Method")
    lines.append("")
    for key, value in report["method"].items():
        lines.append(f"- **{key}**: {value}.")
    lines.append(
        f"- Chunking configs (chunk_size/overlap, characters): {', '.join(report['configs'])}; "
        f"production is {report['production_config']}. Chunk counts: "
        + ", ".join(f"{k} -> {v}" for k, v in report["chunk_counts"].items())
        + "."
    )
    lines.append("- Embedding models:")
    for name, status in report["embedding_models"].items():
        extra = f" ({status.get('source')})" if status.get("status") == "ok" else f" — {status.get('error', '')}"
        lines.append(f"  - `{name}`: {status['status']}{extra}")
    lines.append("")
    lines.append("## Results (all answerable queries)")
    lines.append("")
    header = (
        ["config", "retriever", "chunks", "n", "Hit@1"]
        + [f"R@{k}" for k in ks]
        + ["MRR", "nDCG@5", "nDCG@10", "lat ms"]
    )
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "---|" * len(header))
    for row in report["results"]:
        m = row["metrics"]
        cells = [
            row["config"],
            _row_label(row),
            str(row["chunk_count"]),
            str(row["n_queries"]),
            _fmt(m.get("hit_rate@1")),
        ]
        cells += [_fmt(m.get(f"recall@{k}")) for k in ks]
        cells += [_fmt(m.get("mrr")), _fmt(m.get("ndcg@5")), _fmt(m.get("ndcg@10")), _fmt(row["mean_latency_ms"])]
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    unmatched = {row["config"]: row["unmatched_queries"] for row in report["results"] if row["unmatched_queries"]}
    if unmatched:
        lines.append("Queries with no matching chunk (excluded from means): " + "; ".join(f"{k}: {v}" for k, v in unmatched.items()))
        lines.append("")
    lines.append("## Per-difficulty breakdown (MRR / R@5 / nDCG@10)")
    lines.append("")
    diffs = sorted({d for row in report["results"] for d in row["by_difficulty"]})
    header = ["config", "retriever"] + [f"{d} (n)" for d in diffs]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "---|" * len(header))
    for row in report["results"]:
        cells = [row["config"], _row_label(row)]
        for d in diffs:
            bd = row["by_difficulty"].get(d)
            if not bd:
                cells.append("n/a")
            else:
                cells.append(
                    f"{_fmt(bd.get('mrr'))} / {_fmt(bd.get('recall@5'))} / {_fmt(bd.get('ndcg@10'))} ({bd.get('n')})"
                )
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    lines.append("## Worst queries (production config, dense MiniLM)")
    lines.append("")
    lines.append("| query_id | difficulty | first relevant rank | query | relevant chunks | retrieved top-5 |")
    lines.append("|---|---|---|---|---|---|")
    for d in report["worst_queries_production_dense"]:
        lines.append(
            f"| {d['query_id']} | {d['difficulty']} | {_fmt(d['first_relevant_rank'])} | {d['query']} | "
            f"{', '.join(d['relevant_chunk_ids'])} | {', '.join(d['retrieved_top5'])} |"
        )
    lines.append("")
    lines.append("## Abstention cases (unanswerable queries, production config)")
    lines.append("")
    lines.append(
        "These queries have no relevant chunk anywhere in the corpus. A retriever always returns "
        "something; the question is whether its top-1 score separates them from answerable queries."
    )
    lines.append("")
    for key, info in report["abstention_production_config"].items():
        if info["answerable_top1_score_mean"] is None:
            continue  # RRF has no score comparable across queries; see JSON report
        lines.append(
            f"- **{key}**: answerable top-1 score mean {_fmt(info['answerable_top1_score_mean'])} "
            f"(min {_fmt(info['answerable_top1_score_min'])}); unanswerable top-1 mean "
            f"{_fmt(info['unanswerable_top1_score_mean'])}."
        )
        for u in info["unanswerable"]:
            lines.append(f"  - {u['query_id']}: \"{u['query']}\" -> {u['top1_chunk_id']} ({_fmt(u['top1_score'])})")
    lines.append("")
    lines.append("## Interpretation")
    lines.append("")
    lines.append(INTERPRETATION_START)
    lines.append(extract_interpretation(existing_markdown))
    lines.append(INTERPRETATION_END)
    lines.append("")
    return "\n".join(lines)
