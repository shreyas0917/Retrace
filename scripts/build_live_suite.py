#!/usr/bin/env python3
"""Build the live_v1 run records: real retrieval, generation and judges.

Each query in backend/datasets/suites/live_v1/v1.0.0/queries.jsonl runs through
the real pipeline on its corpus variant (main, documents removed, or near-topic
documents added), with the generator prompt fault the query names, if any.
Generation uses the configured model at temperature 0; relevance and
contradiction use the configured LLM judge; faithfulness uses the NLI judge,
and the LLM faithfulness judge is recorded alongside for comparison.

One run record per query is appended to runs.jsonl as soon as it finishes, so
the build is resumable: on restart, queries already in runs.jsonl are skipped.
A record holds the query, corpus version, retrieved chunks with ranks and
scores, the answer, every judge's raw output, model and prompt versions, the
git commit and a timestamp, plus Retrace's live diagnosis. The diagnosis and
the injected condition are metadata for the report and are never shown on
the labelling sheet.

No labels are written here. Labels come from the author via
scripts/live_labelling.py; until then the suite is runs.jsonl plus
runs_manifest.json, which `build_heldout_suite.py --check` verifies.

Inside the backend image (needs Postgres, Chroma and the model server):

    scripts/dev_test.sh python /scripts/build_live_suite.py --git-commit "$(git describe --always --dirty)"
    scripts/dev_test.sh python /scripts/build_live_suite.py --verify-replay
    scripts/dev_test.sh python /scripts/build_live_suite.py --freeze
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

if Path("/app/app").is_dir():
    sys.path.insert(0, "/app")
else:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy import select  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.errors import GenerationError, GenerationTimeoutError  # noqa: E402
from app.db import session as db_session  # noqa: E402
from app.db.models import Chunk, ExecutionTrace, JudgeResult  # noqa: E402
from app.services.diagnosis.engine import diagnose_execution  # noqa: E402
from app.services.eval.faults import get_fault  # noqa: E402
from app.services.eval.live_suite import (  # noqa: E402
    RUN_RECORD_VERSION,
    RecordingLLM,
    prediction_summary,
    replay_record,
    runs_hash,
)
from app.services.eval.runner import _ensure_eval_corpus  # noqa: E402
from app.services.ingestion import create_corpus, ingest_corpus_version  # noqa: E402
from app.services.judges.contradiction import CONTRADICTION_PROMPT_VERSION  # noqa: E402
from app.services.judges.faithfulness import FAITHFULNESS_PROMPT_VERSION, judge_faithfulness  # noqa: E402
from app.services.judges.faithfulness_nli import NLI_FAITHFULNESS_VERSION  # noqa: E402
from app.services.judges.relevance import RELEVANCE_PROMPT_VERSION  # noqa: E402
from app.services.llm_client import get_llm_provider, set_llm_provider  # noqa: E402
from app.services.rag import run_rag  # noqa: E402

SUITE_ID = "live_v1"
SUITE_VERSION = "1.0.0"
TOP_K = 5


def suite_dir() -> Path:
    for root in (Path("/app/datasets/suites"), Path(__file__).resolve().parents[1] / "backend" / "datasets" / "suites"):
        candidate = root / SUITE_ID / f"v{SUITE_VERSION}"
        if candidate.is_dir():
            return candidate
    raise SystemExit("live_v1 suite directory not found")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def append_record(path: Path, record: dict[str, Any]) -> None:
    line = json.dumps(record, ensure_ascii=False, sort_keys=True)
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(line + "\n")
        fh.flush()
        os.fsync(fh.fileno())


# --------------------------------------------------------------------------
# corpus variants
# --------------------------------------------------------------------------
def variant_documents(config: dict[str, Any], name: str) -> list[dict[str, Any]]:
    spec = config["variants"][name]
    base = Path(config["base_dir"])
    if not base.is_dir():
        base = Path(__file__).resolve().parents[1] / "data" / "corpus" / "demo"
    docs = {p.stem: p for p in sorted(base.glob("*.md"))}
    for doc_id in spec.get("remove", []):
        if doc_id not in docs:
            raise SystemExit(f"variant {name}: cannot remove unknown document {doc_id}")
        del docs[doc_id]
    if spec.get("add_dir"):
        add = Path(spec["add_dir"])
        if not add.is_dir():
            add = Path(__file__).resolve().parents[1] / "data" / "corpus" / "variants" / add.name
        for p in sorted(add.glob("*.md")):
            if p.stem in docs:
                raise SystemExit(f"variant {name}: added document {p.stem} collides with the base corpus")
            docs[p.stem] = p
    return [{"id": stem, "text": p.read_text(encoding="utf-8"), "source_name": p.name} for stem, p in docs.items()]


def ensure_variant(db, config: dict[str, Any], name: str) -> dict[str, Any]:
    spec = config["variants"][name]
    documents = variant_documents(config, name)
    create_corpus(db, corpus_id=spec["corpus_id"], title=spec["title"])
    version = ingest_corpus_version(
        db, corpus_id=spec["corpus_id"], documents=documents, chunking_config=config["chunking_config"]
    )
    return {
        "variant": name,
        "corpus_id": spec["corpus_id"],
        "corpus_version_id": version.id,
        "corpus_hash": version.corpus_hash,
        "document_ids": sorted(d["id"] for d in documents),
        "chunk_count": version.chunk_count,
        "removed": list(spec.get("remove", [])),
        "added_dir": spec.get("add_dir"),
    }


def write_chunk_inventory(db, path: Path, info: dict[str, Any]) -> None:
    """The main corpus's chunks, for choosing gold chunk ids while labelling."""
    rows = db.execute(
        select(Chunk)
        .where(Chunk.corpus_version_id == info["corpus_version_id"])
        .order_by(Chunk.document_id, Chunk.ordinal)
    ).scalars()
    lines = [
        json.dumps(
            {"chunk_id": c.id, "document_id": c.document_id, "ordinal": c.ordinal, "text": c.text}, ensure_ascii=False
        )
        for c in rows
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


# --------------------------------------------------------------------------
# one live run
# --------------------------------------------------------------------------
def run_one(db, query: dict[str, Any], corpus: dict[str, Any], settings, git_commit: str) -> dict[str, Any]:
    started = time.perf_counter()
    fault = get_fault(query.get("eval_fault"))
    rag_error = None
    try:
        out = run_rag(
            db,
            corpus_version_id=corpus["corpus_version_id"],
            query=query["query"],
            top_k=TOP_K,
            settings=settings,
            eval_fault=fault,
        )
        execution_id = out["execution_id"]
    except (GenerationTimeoutError, GenerationError) as exc:
        execution_id = (exc.details or {}).get("execution_id")
        rag_error = {"code": exc.code, "message": exc.message}
        if not execution_id:
            raise
    row = db.get(ExecutionTrace, execution_id)
    chunks = list(row.retrieved_chunks or [])

    recorder = RecordingLLM(get_llm_provider(settings))
    set_llm_provider(recorder)
    faithfulness_llm_error = None
    try:
        diagnosis = diagnose_execution(db, execution_id=execution_id, gold_chunk_ids=None, settings=settings)
        if row.answer_text and not row.abstained and chunks:
            # Not used by the rules (the NLI judge is); recorded for comparison.
            try:
                judge_faithfulness(row.query, row.answer_text, chunks, settings=settings)
            except Exception as exc:  # noqa: BLE001 - keep the run, note the failure
                faithfulness_llm_error = f"{type(exc).__name__}: {str(exc)[:300]}"
    finally:
        set_llm_provider(None)

    nli_row = (
        db.execute(
            select(JudgeResult).where(
                JudgeResult.execution_id == execution_id,
                JudgeResult.judge_type == "faithfulness",
            )
        )
        .scalars()
        .first()
    )
    nli_output = (
        nli_row.output if nli_row is not None and str(nli_row.prompt_version).startswith("faithfulness.nli") else None
    )

    return {
        "record_version": RUN_RECORD_VERSION,
        "suite_id": SUITE_ID,
        "suite_version": SUITE_VERSION,
        "query_id": query["query_id"],
        "condition": query["condition"],
        "corpus_variant": query["corpus_variant"],
        "eval_fault": query.get("eval_fault"),
        "query": query["query"],
        "corpus": {
            k: corpus[k] for k in ("variant", "corpus_id", "corpus_version_id", "corpus_hash", "chunk_count", "removed")
        },
        "execution": {
            "execution_id": execution_id,
            "top_k": TOP_K,
            "retrieved_chunks": chunks,
            "answer": row.answer_text,
            "abstained": bool(row.abstained),
            "status": row.status,
            "error_code": row.error_code,
            "error_message": row.error_message,
            "rag_error": rag_error,
        },
        "retrieval": {
            "latency_ms": row.retrieval_latency_ms,
            "embedding_model": row.embedding_model,
            "embedding_revision": row.embedding_revision,
        },
        "generation": {
            "model": row.generation_model,
            "temperature": row.generation_temperature,
            "prompt_version": row.prompt_version,
            "latency_ms": row.generation_latency_ms,
            "prompt_tokens": row.prompt_tokens,
            "completion_tokens": row.completion_tokens,
        },
        "judges": {
            "model": settings.model_name,
            "prompt_versions": {
                "relevance": RELEVANCE_PROMPT_VERSION,
                "contradiction": CONTRADICTION_PROMPT_VERSION,
                "faithfulness_llm": FAITHFULNESS_PROMPT_VERSION,
                "faithfulness_nli": NLI_FAITHFULNESS_VERSION,
            },
            "relevance": recorder.replies.get("relevance", []),
            "contradiction": recorder.replies.get("contradiction", []),
            "faithfulness_llm": recorder.replies.get("faithfulness", []),
            "faithfulness_llm_error": faithfulness_llm_error,
            "faithfulness_nli": nli_output,
            "timeouts": recorder.timeouts,
            "calls": recorder.calls,
        },
        "live_diagnosis": {**prediction_summary(diagnosis), "explanation": diagnosis.get("explanation")},
        "settings": {
            "faithfulness_backend": settings.faithfulness_backend,
            "nli_max_pairs": settings.nli_max_pairs,
            "model_timeout_seconds": settings.model_timeout_seconds,
        },
        "git_commit": git_commit,
        "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "run_latency_ms": round((time.perf_counter() - started) * 1000, 1),
    }


def build(args: argparse.Namespace) -> int:
    settings = get_settings()
    if settings.faithfulness_backend != "nli":
        print("build_live_suite: FAITHFULNESS_BACKEND must be nli for live_v1", file=sys.stderr)
        return 2
    directory = suite_dir()
    queries = read_jsonl(directory / "queries.jsonl")
    config = json.loads((directory / "corpus_variants.json").read_text(encoding="utf-8"))
    runs_path = directory / "runs.jsonl"
    existing = read_jsonl(runs_path)
    done = {r["query_id"] for r in existing}
    models = {r["generation"]["model"] for r in existing if r.get("generation")}
    if existing and not args.allow_mixed and models and models != {settings.model_name}:
        print(
            f"build_live_suite: runs.jsonl was recorded with {sorted(models)}, the current model is "
            f"{settings.model_name}; pass --allow-mixed to continue anyway",
            file=sys.stderr,
        )
        return 2
    todo = [q for q in queries if q["query_id"] not in done]
    if args.only:
        wanted = set(args.only.split(","))
        todo = [q for q in todo if q["query_id"] in wanted]
    if args.limit is not None:
        todo = todo[: args.limit]
    print(f"live_v1: {len(done)} recorded, {len(todo)} to run, model {settings.model_name}", flush=True)

    db_session.init_db()
    db = db_session.SessionLocal()
    try:
        corpora: dict[str, dict[str, Any]] = {}
        for name in sorted({q["corpus_variant"] for q in queries} | {"main"}):
            corpora[name] = ensure_variant(db, config, name)
            print(
                f"  corpus {name}: version {corpora[name]['corpus_version_id']} chunks={corpora[name]['chunk_count']}",
                flush=True,
            )
        write_chunk_inventory(db, directory / "corpus_chunks.jsonl", corpora["main"])

        failures = 0
        for i, query in enumerate(todo, start=1):
            try:
                record = run_one(db, query, corpora[query["corpus_variant"]], settings, args.git_commit)
            except Exception as exc:  # noqa: BLE001 - not recorded; a restart retries it
                db.rollback()
                failures += 1
                print(
                    f"  [{i}/{len(todo)}] {query['query_id']} FAILED, not recorded: {type(exc).__name__}: {str(exc)[:200]}",
                    flush=True,
                )
                continue
            append_record(runs_path, record)
            print(
                f"  [{i}/{len(todo)}] {query['query_id']} {record['execution']['status']} "
                f"({record['run_latency_ms'] / 1000:.0f}s)",
                flush=True,
            )
    finally:
        db.close()
    total = len(read_jsonl(runs_path))
    print(
        f"live_v1: {total}/{len(queries)} recorded"
        + (f", {failures} failed this pass (rerun to retry)" if failures else "")
    )
    return 0 if not failures else 1


def verify_replay(args: argparse.Namespace) -> int:
    """Re-diagnose every record offline and compare with the live diagnosis."""
    records = read_jsonl(suite_dir() / "runs.jsonl")
    db_session.init_db()
    db = db_session.SessionLocal()
    mismatches = []
    try:
        stub = _ensure_eval_corpus(db)
        for record in records:
            replayed = prediction_summary(replay_record(db, record, corpus_version_id=stub))
            live = record["live_diagnosis"]
            if (replayed["failure_code"], replayed["rule_id"]) != (live["failure_code"], live["rule_id"]):
                mismatches.append((record["query_id"], live, replayed))
    finally:
        db.close()
    for qid, live, replayed in mismatches:
        print(
            f"  {qid}: live {live['failure_code']}/{live['rule_id']} replay {replayed['failure_code']}/{replayed['rule_id']}"
        )
    print(f"replay check: {len(records) - len(mismatches)}/{len(records)} records reproduce the live diagnosis offline")
    return 0 if not mismatches else 1


def freeze(args: argparse.Namespace) -> int:
    directory = suite_dir()
    queries = read_jsonl(directory / "queries.jsonl")
    lines = (directory / "runs.jsonl").read_text(encoding="utf-8").splitlines()
    records = [json.loads(line) for line in lines if line.strip()]
    missing = sorted({q["query_id"] for q in queries} - {r["query_id"] for r in records})
    if missing and not args.allow_partial:
        print(
            f"freeze: {len(missing)} queries have no record yet ({', '.join(missing[:10])}); run the build again",
            file=sys.stderr,
        )
        return 2
    manifest = {
        "suite_id": SUITE_ID,
        "suite_version": SUITE_VERSION,
        "status": "recorded, not yet labelled",
        "runs_file": "runs.jsonl",
        "runs_hash": runs_hash(lines),
        "queries_hash": runs_hash((directory / "queries.jsonl").read_text(encoding="utf-8").splitlines()),
        "run_count": len(records),
        "conditions": dict(sorted(Counter(r["condition"] for r in records).items())),
        "generation_models": sorted({r["generation"]["model"] for r in records}),
        "judge_models": sorted({r["judges"]["model"] for r in records}),
        "git_commits": sorted({r["git_commit"] for r in records}),
        "recorded_from": min(r["recorded_at"] for r in records),
        "recorded_to": max(r["recorded_at"] for r in records),
        "note": "Injected conditions and live diagnoses are metadata. Labels are added only from the author's labelling sheet.",
    }
    (directory / "runs_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(manifest, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Build, verify or freeze the live_v1 run records")
    parser.add_argument("--git-commit", default=os.environ.get("GIT_COMMIT", "unknown"))
    parser.add_argument("--only", default=None, help="Comma list of query ids to run")
    parser.add_argument("--limit", type=int, default=None, help="Run at most N pending queries")
    parser.add_argument("--allow-mixed", action="store_true", help="Resume even if the model changed")
    parser.add_argument("--verify-replay", action="store_true", help="Check offline replay reproduces live diagnoses")
    parser.add_argument("--freeze", action="store_true", help="Write runs_manifest.json")
    parser.add_argument("--allow-partial", action="store_true", help="Freeze even if some queries have no record")
    args = parser.parse_args()
    if args.verify_replay:
        return verify_replay(args)
    if args.freeze:
        return freeze(args)
    return build(args)


if __name__ == "__main__":
    raise SystemExit(main())
