"""`retrace retrieval-eval` — chunking x retriever ablation on a corpus directory."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.services.retrieval_eval import (
    DEFAULT_CONFIGS,
    QrelsValidationError,
    default_qrels_path,
    format_markdown,
    parse_configs,
    run_retrieval_ablation,
)

EXIT_OK = 0
EXIT_ERROR = 2


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def cmd_retrieval_eval(args: argparse.Namespace) -> int:
    try:
        configs = parse_configs(args.configs)
        report = run_retrieval_ablation(
            corpus_dir=args.corpus_dir,
            qrels_path=args.qrels,
            configs=configs,
            ks=tuple(int(k) for k in _split_csv(args.ks)),
            embedding_models=_split_csv(args.embedding_models),
        )
    except (QrelsValidationError, ValueError) as exc:
        print(f"retrieval-eval error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"wrote {out}")
    if args.markdown:
        md_path = Path(args.markdown)
        md_path.parent.mkdir(parents=True, exist_ok=True)
        existing = md_path.read_text(encoding="utf-8") if md_path.is_file() else None
        md_path.write_text(format_markdown(report, existing_markdown=existing), encoding="utf-8")
        print(f"wrote {md_path}")

    # Console summary: one line per (config, retriever).
    print(
        f"queries={report['qrels']['query_count']} "
        f"(answerable={report['qrels']['answerable']}, unanswerable={report['qrels']['unanswerable']})"
    )
    print(f"{'config':>9} {'retriever':<42} {'chunks':>6} {'R@1':>6} {'R@5':>6} {'MRR':>6} {'nDCG@10':>8} {'ms':>7}")
    for row in report["results"]:
        m = row["metrics"]
        label = row["retriever"] + (
            f" ({row['embedding_model'].split('/')[-1]})" if row.get("embedding_model") else ""
        )
        print(
            f"{row['config']:>9} {label:<42} {row['chunk_count']:>6} "
            f"{(m.get('recall@1') or 0):>6.3f} {(m.get('recall@5') or 0):>6.3f} "
            f"{(m.get('mrr') or 0):>6.3f} {(m.get('ndcg@10') or 0):>8.3f} {row['mean_latency_ms']:>7.2f}"
        )
    for name, status in report["embedding_models"].items():
        if status.get("status") != "ok":
            print(f"embedding model not run: {name}: {status.get('error')}")
    return EXIT_OK


def add_retrieval_eval_subparser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "retrieval-eval",
        help="Chunking x retriever ablation (Recall@k, MRR, nDCG) against a qrels file",
    )
    p.add_argument("--corpus-dir", default="/data/corpus/demo", help="Directory of *.md documents")
    p.add_argument("--qrels", default=str(default_qrels_path()), help="Qrels JSONL path")
    p.add_argument(
        "--configs",
        default=",".join(f"{s}:{o}" for s, o in DEFAULT_CONFIGS),
        help="Comma list of chunk_size:overlap (chars)",
    )
    p.add_argument("--ks", default="1,3,5,10", help="Comma list of cutoffs")
    p.add_argument(
        "--embedding-models",
        default=None,
        help="Comma list of extra sentence-transformers models to compare (downloaded directly)",
    )
    p.add_argument("--out", default=None, help="Write full JSON report here")
    p.add_argument("--markdown", default=None, help="Write/refresh a markdown report here")
    p.set_defaults(func=cmd_retrieval_eval)
