#!/usr/bin/env python3
"""Retrace load test — fixed request count at a fixed concurrency (threads + httpx).

Examples
--------
  python scripts/load_test.py --endpoint ready --concurrency 10 --requests 300
  python scripts/load_test.py --endpoint retrieve --concurrency 25 --requests 300
  python scripts/load_test.py --endpoint generate --concurrency 2 --requests 10

For retrieve/investigate/generate a READY corpus version is auto-picked from
GET /api/v1/corpora (+ detail) unless --corpus-version-id is given.

Writes JSON to data/reports/load_<ts>.json and prints a markdown table.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import httpx

QUERIES = [
    "How much PTO do full-time employees accrue per month?",
    "What is the refund window after purchase?",
    "Can unused PTO be carried over to the next year?",
    "Who approves expense reports above the limit?",
    "What is the remote work policy for new hires?",
    "How do I reset my VPN credentials?",
    "What are the data retention rules for customer records?",
    "What is the on-call escalation path?",
]


def percentile(sorted_vals: list[float], pct: float) -> float | None:
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    k = (len(sorted_vals) - 1) * (pct / 100.0)
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    if f == c:
        return sorted_vals[f]
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def pick_ready_version(client: httpx.Client) -> str:
    r = client.get("/api/v1/corpora")
    r.raise_for_status()
    corpora = r.json()
    if isinstance(corpora, dict):
        corpora = corpora.get("corpora") or []
    for corpus in corpora:
        cid = corpus.get("id")
        if not cid:
            continue
        d = client.get(f"/api/v1/corpora/{cid}")
        if d.status_code != 200:
            continue
        detail = d.json()
        versions = detail.get("versions") or []
        for v in versions:
            if v.get("status") == "READY":
                return v["id"]
    raise SystemExit("No READY corpus version found; seed one first (scripts/seed_demo_corpus.py).")


def build_request(endpoint: str, version_id: str | None, i: int) -> tuple[str, str, dict | None]:
    q = QUERIES[i % len(QUERIES)]
    if endpoint == "ready":
        return "GET", "/health/ready", None
    if endpoint == "retrieve":
        return "POST", "/api/v1/retrieve", {"corpus_version_id": version_id, "query": q, "top_k": 5}
    if endpoint == "generate":
        return "POST", "/api/v1/generate", {"corpus_version_id": version_id, "query": q, "top_k": 5}
    if endpoint == "investigate":
        return "POST", "/api/v1/investigate", {"corpus_version_id": version_id, "query": q, "top_k": 5}
    raise ValueError(endpoint)


def run(args: argparse.Namespace) -> dict:
    headers = {"Authorization": f"Bearer {args.api_key}"} if args.api_key else {}
    limits = httpx.Limits(max_connections=args.concurrency + 4, max_keepalive_connections=args.concurrency + 4)
    client = httpx.Client(base_url=args.base_url, headers=headers, timeout=args.timeout, limits=limits)

    version_id = args.corpus_version_id
    if args.endpoint != "ready" and not version_id:
        version_id = pick_ready_version(client)

    # Warm-up (not measured): embedding model + connection pool.
    for i in range(min(args.warmup, args.requests)):
        method, path, body = build_request(args.endpoint, version_id, i)
        try:
            client.request(method, path, json=body)
        except httpx.HTTPError:
            pass

    latencies: list[float] = []
    status_counts: dict[str, int] = {}
    errors: list[str] = []
    lock = threading.Lock()

    def one(i: int) -> None:
        method, path, body = build_request(args.endpoint, version_id, i)
        t0 = time.perf_counter()
        try:
            r = client.request(method, path, json=body)
            key = str(r.status_code)
            err = None if r.status_code < 400 else (r.text or "")[:120]
        except httpx.HTTPError as exc:
            key = f"exc:{type(exc).__name__}"
            err = str(exc)[:120]
        ms = (time.perf_counter() - t0) * 1000.0
        with lock:
            latencies.append(ms)
            status_counts[key] = status_counts.get(key, 0) + 1
            if err and len(errors) < 10:
                errors.append(f"{key}: {err}")

    wall0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        list(pool.map(one, range(args.requests)))
    wall = time.perf_counter() - wall0
    client.close()

    ordered = sorted(latencies)
    ok = sum(v for k, v in status_counts.items() if k.isdigit() and int(k) < 400)
    failed = len(latencies) - ok
    result = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "base_url": args.base_url,
        "endpoint": args.endpoint,
        "corpus_version_id": version_id,
        "concurrency": args.concurrency,
        "requests": args.requests,
        "warmup": min(args.warmup, args.requests),
        "wall_seconds": round(wall, 3),
        "throughput_rps": round(len(latencies) / wall, 2) if wall > 0 else None,
        "ok": ok,
        "failed": failed,
        "error_rate": round(failed / len(latencies), 4) if latencies else None,
        "status_counts": status_counts,
        "latency_ms": {
            "min": round(ordered[0], 1) if ordered else None,
            "mean": round(statistics.fmean(ordered), 1) if ordered else None,
            "p50": round(percentile(ordered, 50) or 0, 1) if ordered else None,
            "p95": round(percentile(ordered, 95) or 0, 1) if ordered else None,
            "p99": round(percentile(ordered, 99) or 0, 1) if ordered else None,
            "max": round(ordered[-1], 1) if ordered else None,
        },
        "sample_errors": errors,
    }
    return result


def markdown_row(res: dict) -> str:
    lat = res["latency_ms"]
    return (
        f"| {res['endpoint']} | {res['concurrency']} | {res['requests']} | "
        f"{res['throughput_rps']} | {res['error_rate']:.2%} | {lat['p50']} | {lat['p95']} | "
        f"{lat['p99']} | {lat['max']} |"
    )


MD_HEADER = (
    "| endpoint | concurrency | requests | req/s | error rate | p50 ms | p95 ms | p99 ms | max ms |\n"
    "|---|---|---|---|---|---|---|---|---|"
)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base-url", default=os.environ.get("RETRACE_API_BASE", "http://localhost:8000"))
    p.add_argument("--api-key", default=os.environ.get("API_KEY", ""))
    p.add_argument("--endpoint", choices=["ready", "retrieve", "investigate", "generate"], default="ready")
    p.add_argument("--concurrency", type=int, default=10)
    p.add_argument("--requests", type=int, default=100)
    p.add_argument("--warmup", type=int, default=5)
    p.add_argument("--timeout", type=float, default=120.0)
    p.add_argument("--corpus-version-id", default=None)
    p.add_argument("--out-dir", default=os.environ.get("LOAD_REPORT_DIR", "data/reports"))
    p.add_argument("--no-write", action="store_true", help="Do not write the JSON report")
    args = p.parse_args()

    res = run(args)
    print(MD_HEADER)
    print(markdown_row(res))
    if res["sample_errors"]:
        print("\nSample errors:")
        for e in res["sample_errors"]:
            print(" -", e)

    if not args.no_write:
        out_dir = Path(args.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out = out_dir / f"load_{ts}_{res['endpoint']}_c{res['concurrency']}.json"
        out.write_text(json.dumps(res, indent=2), encoding="utf-8")
        print(f"\nReport: {out}")
    return 0 if res["failed"] == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
