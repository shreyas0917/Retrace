# NLI faithfulness latency (CPU)

Produced by `scripts/measure_nli_latency.py` on 2026-11-08. Model `cross-encoder/nli-deberta-v3-small` at
`fa2804872c3b`, premise unit `sentence_and_adjacent_pair`, default cap
NLI_MAX_PAIRS=2000. Each case ran once to warm up, then 5 times
(2 for the synthetic cap case).

| Case | Chunks | Claims | Premise windows | Pairs scored | Truncated | Median ms | Min ms | Max ms |
| --- | ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: |
| contradiction | 2 | 1 | 6 | 6 | no | 379.0 | 327.5 | 419.3 |
| retrieval_miss | 2 | 1 | 6 | 6 | no | 405.3 | 365.2 | 415.2 |
| correct_abstention | 2 | 0 | 0 | 0 | no | 0.2 | 0.2 | 0.2 |
| synthetic cap | 100 | 20 | 100 | 2000 | no | 64578.8 | 59633.9 | 69523.7 |

Model load (first `get_nli_scorer()` call, weights already on disk): 5735 ms.

Machine: platform `Linux-6.18.54.1-microsoft-standard-WSL2-x86_64-with-glibc2.41`, processor `x86_64`, cpu_count `8`, torch `2.14.1+cpu`, torch_threads `4`, python `3.11.18`.

Load average (1 / 5 / 15 min) at start: `9.28 / 7.17 / 8.11`; at end: `8.35 / 7.43 / 8.00`. Other
workloads shared these CPUs; a load average well above the CPU count means
the times are inflated by contention.

Notes:

- The three examples are the files in `examples/traces/`. They are small (two
  chunks each), so their numbers are close to the fixed cost of one batched call.
- `correct_abstention` has no claims (its answer is a refusal), so nothing is
  scored. In the pipeline the grounding judges are not called for abstentions,
  and `retrieval_miss` stops at the gold-miss rule (R11) when gold ids are
  given, so only `contradiction` reaches the faithfulness judge in practice.
- `synthetic cap` is not a real trace: 20 claims against 100 one-sentence
  chunks, which is exactly the default cap. It shows the worst case a single
  answer can cost before truncation starts.
- One developer machine, CPU only, single process. Treat these as orders of
  magnitude, not service-level numbers.
