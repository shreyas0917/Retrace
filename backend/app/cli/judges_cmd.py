"""`retrace judges validate` — score the LLM judges against human-labeled examples."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from app.core.config import get_settings
from app.services.judges.prompt_variants import PRODUCTION_VARIANT, available_variants
from app.services.judges.validation import (
    JudgeLabelsValidationError,
    default_labels_path,
    format_markdown,
    load_judge_labels,
    select_examples,
    validate_judges,
)
from app.services.llm_client import get_llm_provider

EXIT_OK = 0
EXIT_ERROR = 2


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def cmd_judges_validate(args: argparse.Namespace) -> int:
    try:
        examples, labels_hash = load_judge_labels(args.labels)
    except JudgeLabelsValidationError as exc:
        print(f"judges validate error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    variants = _split_csv(args.variants) or [PRODUCTION_VARIANT]
    known = set(available_variants("relevance"))
    unknown = [v for v in variants if v not in known]
    if unknown:
        print(f"judges validate error: unknown prompt variants {unknown}; known: {sorted(known)}", file=sys.stderr)
        return EXIT_ERROR
    primary = variants[0]

    examples = select_examples(examples, args.limit)
    settings = get_settings()
    provider = get_llm_provider(settings)

    started = time.perf_counter()
    last_print = [0.0]

    def progress(done: int, total: int, label: str) -> None:
        now = time.perf_counter()
        if now - last_print[0] >= 10.0 or done == total:
            last_print[0] = now
            print(f"  [{done}/{total}] {label} ({now - started:.0f}s)", file=sys.stderr, flush=True)

    print(
        f"validating {len(examples)} examples with model {settings.model_name} "
        f"variants={variants} consistency={not args.skip_consistency}",
        file=sys.stderr,
    )
    report = validate_judges(
        provider,
        examples,
        primary,
        variants=variants,
        settings=settings,
        include_consistency=not args.skip_consistency,
        progress=progress,
    )
    report["labels_file"] = str(args.labels)
    report["labels_file_hash"] = labels_hash
    report["limit"] = args.limit

    source_label = (
        f"live model run ({settings.model_name} via {report['model']['base_url']})"
        if args.source_label is None
        else args.source_label
    )
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"wrote {out}")
    if args.markdown:
        md = Path(args.markdown)
        md.parent.mkdir(parents=True, exist_ok=True)
        md.write_text(format_markdown(report, source_label=source_label), encoding="utf-8")
        print(f"wrote {md}")

    for judge, per_variant in report["per_judge"].items():
        for variant, r in per_variant.items():
            if judge == "relevance":
                head = r["chunk_relevant"]
                extra = f" sufficient_acc={r['context_sufficient']['accuracy']} score_mae={r['score_mae']}"
            elif judge == "faithfulness":
                head = r["has_unsupported_claim"]
                extra = f" score_mae={r['score_mae']} in_band={r['score_in_band_rate']}"
            else:
                head = r["contradicts"]
                extra = ""
            rel = r["reliability"]
            print(
                f"{judge:<13} {variant:<4} n={head['n']:<3} acc={head['accuracy']} f1={head['f1']} "
                f"kappa={head['kappa']}{extra} schema_fail={rel['schema_failure_rate']} "
                f"mean_ms={rel['mean_latency_ms']}"
            )
    if report.get("sensitivity"):
        for judge, pairs in report["sensitivity"].items():
            for pair, s in pairs.items():
                print(f"sensitivity {judge:<13} {pair}: flip_rate={s['flip_rate']} kappa={s['kappa']}")
    if report.get("consistency"):
        print("consistency flags:", report["consistency"]["counts"])
    return EXIT_OK


def add_judges_subparser(sub: argparse._SubParsersAction) -> None:
    judges_p = sub.add_parser("judges", help="LLM judge validation")
    judges_sub = judges_p.add_subparsers(dest="judges_command", required=True)
    p = judges_sub.add_parser(
        "validate",
        help="Score relevance/faithfulness/contradiction judges against labeled examples",
    )
    p.add_argument("--labels", default=str(default_labels_path()), help="Labeled examples JSONL")
    p.add_argument(
        "--variants",
        default="v1,v1b,v1c",
        help="Comma list of prompt variants; the first is primary (default v1,v1b,v1c)",
    )
    p.add_argument("--limit", type=int, default=None, help="Evaluate only the first N examples (interleaved by judge)")
    p.add_argument("--skip-consistency", action="store_true", help="Skip cross-judge consistency calls")
    p.add_argument("--out", default=None, help="Write full JSON report here")
    p.add_argument("--markdown", default=None, help="Write a markdown report here")
    p.add_argument(
        "--source-label",
        default=None,
        help="Override the 'source of these numbers' line in the markdown (e.g. for fixture runs)",
    )
    p.set_defaults(func=cmd_judges_validate)
