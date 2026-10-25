#!/usr/bin/env python3
"""Seed the demo corpus and optionally run a RAG generate call."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx

API_BASE = os.environ.get("RETRACE_API_BASE", "http://localhost:8000")
API_KEY = os.environ.get("API_KEY", "dev-retrace-api-key-change-me")
CORPUS_DIR = Path(os.environ.get("DEMO_CORPUS_DIR", "/data/corpus/demo"))
MODEL_API_KEY = os.environ.get("MODEL_API_KEY", "")


def main() -> int:
    headers = {"Authorization": f"Bearer {API_KEY}"}
    if not CORPUS_DIR.exists():
        alt = Path(__file__).resolve().parents[1] / "data" / "corpus" / "demo"
        corpus_dir = alt if alt.exists() else CORPUS_DIR
    else:
        corpus_dir = CORPUS_DIR

    docs = []
    for path in sorted(corpus_dir.glob("*.md")):
        docs.append(
            {
                "id": path.stem,
                "text": path.read_text(encoding="utf-8"),
                "source_name": path.name,
            }
        )
    if not docs:
        print(f"No markdown files in {corpus_dir}", file=sys.stderr)
        return 1

    with httpx.Client(base_url=API_BASE, timeout=180.0, headers=headers) as client:
        r = client.post("/api/v1/corpora", json={"id": "demo", "title": "Demo Policies"})
        print("create corpus:", r.status_code)
        if r.status_code not in {200, 201, 409}:
            err = {}
            try:
                err = r.json().get("error") or {}
            except Exception:
                pass
            if err.get("code") != "CONFLICT":
                r.raise_for_status()

        r = client.post(
            "/api/v1/corpora/demo/versions",
            json={
                "documents": docs,
                "chunking_config": {
                    "strategy": "recursive_character",
                    "chunk_size": 512,
                    "chunk_overlap": 64,
                    "tokenizer": "char",
                },
            },
        )
        print("ingest version:", r.status_code)
        r.raise_for_status()
        version = r.json()
        print(
            "READY version:",
            version["id"],
            "chunks=",
            version["chunk_count"],
            "collection=",
            version["vector_collection"],
        )

        query = "How much PTO do full-time employees accrue per month?"
        r = client.post(
            "/api/v1/retrieve",
            json={"corpus_version_id": version["id"], "query": query, "top_k": 3},
        )
        print("retrieve:", r.status_code)
        r.raise_for_status()
        for item in r.json()["results"]:
            print(
                f"  rank={item['rank']} score={item['score']} "
                f"chunk={item['chunk_id']} source={item['source_name']}"
            )

        if not MODEL_API_KEY or MODEL_API_KEY.strip() in {"", "replace-me"}:
            print(
                "generate: SKIPPED — MODEL_API_KEY not configured "
                "(Phase 3 path covered by FakeLLM tests)"
            )
            return 0

        r = client.post(
            "/api/v1/generate",
            json={"corpus_version_id": version["id"], "query": query, "top_k": 3},
        )
        print("generate:", r.status_code)
        if r.status_code >= 400:
            print(r.text)
            return 1
        body = r.json()
        print("status:", body["status"], "abstained:", body["abstained"])
        print("execution_id:", body["execution_id"])
        print("answer:", body["answer"])
        print(
            "tokens:",
            body["generation"].get("total_tokens"),
            "gen_latency_ms:",
            body["generation"].get("latency_ms"),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
