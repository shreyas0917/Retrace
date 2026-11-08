#!/usr/bin/env python3
"""Measure NLI faithfulness latency on CPU and write docs/benchmarks/nli_latency.md.

Times `judge_faithfulness_nli` (claim splitting, premise units, one batched
cross-encoder call) on the three single-trace examples in examples/traces/,
plus one synthetic answer sized to hit the default NLI_MAX_PAIRS cap. Each
case is run once to warm up and then `--repeats` times (`--cap-repeats` for the
cap case, which is far more expensive); the table reports the median, min and
max. Model load time and the machine's load average are reported alongside,
because on a shared machine contention changes these numbers a lot.

Run inside the backend image (the model is pre-downloaded there):

    scripts/dev_test.sh python /scripts/measure_nli_latency.py --out /docs/benchmarks/nli_latency.md
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

if Path("/app/app").is_dir():
    sys.path.insert(0, "/app")
else:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.services.judges.faithfulness_nli import (  # noqa: E402
    DEFAULT_MAX_PAIRS,
    MAX_CLAIMS,
    NLI_MODEL_ID,
    NLI_MODEL_REVISION,
    PREMISE_UNIT,
    get_nli_scorer,
    judge_faithfulness_nli,
)

EXAMPLES = ("contradiction", "retrieval_miss", "correct_abstention")


def _examples_dir() -> Path:
    for candidate in (Path("/examples/traces"), Path(__file__).resolve().parents[1] / "examples" / "traces"):
        if candidate.is_dir():
            return candidate
    raise SystemExit("examples/traces not found")


def _synthetic_cap_case() -> dict:
    """20 claims x 100 one-sentence chunks = 2000 pairs, the default cap."""
    claims = [f"Policy item {i} applies to every full-time employee in the company." for i in range(MAX_CLAIMS)]
    chunks = [
        {"chunk_id": f"synthetic:c{i:03d}", "text": f"Section {i} describes the rules for office access badges.", "retrieval_score": 1 - i / 1000}
        for i in range(DEFAULT_MAX_PAIRS // MAX_CLAIMS)
    ]
    return {"query": "synthetic", "answer": " ".join(claims), "retrieved_chunks": chunks}


def _time_case(trace: dict, repeats: int, scorer) -> dict:
    chunks = trace.get("retrieved_chunks") or []
    answer = trace.get("answer") or ""
    judge_faithfulness_nli(trace.get("query", ""), answer, chunks, scorer=scorer)  # warm-up
    samples = []
    result = None
    for _ in range(repeats):
        started = time.perf_counter()
        result, _ = judge_faithfulness_nli(trace.get("query", ""), answer, chunks, scorer=scorer)
        samples.append((time.perf_counter() - started) * 1000)
    assert result is not None
    return {
        "chunks": len(chunks),
        "claims": len(result.claims),
        "windows": result.window_count,
        "pairs": result.pair_count,
        "truncated": result.truncated,
        "median_ms": round(statistics.median(samples), 1),
        "min_ms": round(min(samples), 1),
        "max_ms": round(max(samples), 1),
    }


def _loadavg() -> str:
    try:
        return " / ".join(Path("/proc/loadavg").read_text().split()[:3])
    except OSError:
        return "unavailable"


def _machine() -> dict:
    import torch

    return {
        "platform": platform.platform(),
        "processor": platform.processor() or platform.machine(),
        "cpu_count": os.cpu_count(),
        "torch": torch.__version__,
        "torch_threads": torch.get_num_threads(),
        "python": platform.python_version(),
    }


def render(rows: list[tuple[str, dict]], load_ms: float, machine: dict, repeats: int, cap_repeats: int, load: tuple[str, str]) -> str:
    when = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = [
        "# NLI faithfulness latency (CPU)",
        "",
        f"Produced by `scripts/measure_nli_latency.py` on {when}. Model `{NLI_MODEL_ID}` at",
        f"`{NLI_MODEL_REVISION[:12]}`, premise unit `{PREMISE_UNIT}`, default cap",
        f"NLI_MAX_PAIRS={DEFAULT_MAX_PAIRS}. Each case ran once to warm up, then {repeats} times",
        f"({cap_repeats} for the synthetic cap case).",
        "",
        "| Case | Chunks | Claims | Premise windows | Pairs scored | Truncated | Median ms | Min ms | Max ms |",
        "| --- | ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: |",
    ]
    for name, r in rows:
        lines.append(
            f"| {name} | {r['chunks']} | {r['claims']} | {r['windows']} | {r['pairs']} | "
            f"{'yes' if r['truncated'] else 'no'} | {r['median_ms']} | {r['min_ms']} | {r['max_ms']} |"
        )
    lines += [
        "",
        f"Model load (first `get_nli_scorer()` call, weights already on disk): {round(load_ms)} ms.",
        "",
        "Machine: " + ", ".join(f"{k} `{v}`" for k, v in machine.items()) + ".",
        "",
        f"Load average (1 / 5 / 15 min) at start: `{load[0]}`; at end: `{load[1]}`. Other",
        "workloads shared these CPUs; a load average well above the CPU count means",
        "the times are inflated by contention.",
        "",
        "Notes:",
        "",
        "- The three examples are the files in `examples/traces/`. They are small (two",
        "  chunks each), so their numbers are close to the fixed cost of one batched call.",
        "- `correct_abstention` has no claims (its answer is a refusal), so nothing is",
        "  scored. In the pipeline the grounding judges are not called for abstentions,",
        "  and `retrieval_miss` stops at the gold-miss rule (R11) when gold ids are",
        "  given, so only `contradiction` reaches the faithfulness judge in practice.",
        "- `synthetic cap` is not a real trace: 20 claims against 100 one-sentence",
        "  chunks, which is exactly the default cap. It shows the worst case a single",
        "  answer can cost before truncation starts.",
        "- One developer machine, CPU only, single process. Treat these as orders of",
        "  magnitude, not service-level numbers.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--cap-repeats", type=int, default=2)
    parser.add_argument("--out", default=None, help="Write the markdown report here")
    args = parser.parse_args()

    load_start = _loadavg()
    started = time.perf_counter()
    scorer = get_nli_scorer()
    load_ms = (time.perf_counter() - started) * 1000

    rows: list[tuple[str, dict]] = []
    directory = _examples_dir()
    for name in EXAMPLES:
        trace = json.loads((directory / f"{name}.json").read_text(encoding="utf-8"))
        rows.append((name, _time_case(trace, args.repeats, scorer)))
        print(f"{name}: {rows[-1][1]}", file=sys.stderr, flush=True)
    rows.append(("synthetic cap", _time_case(_synthetic_cap_case(), args.cap_repeats, scorer)))

    text = render(rows, load_ms, _machine(), args.repeats, args.cap_repeats, (load_start, _loadavg()))
    print(text)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(f"wrote {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
