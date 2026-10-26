# Retrieval ablation: chunking x retriever on the demo corpus

Generated 2026-10-25T20:31:28+00:00 by `retrace retrieval-eval` (elapsed 4580.39s). Numbers below are measured, not estimated; re-run the command to refresh them.

## Dataset

- Corpus: `/data/corpus/demo`, 13 markdown documents (benefits_overview, data_retention, employee_handbook, expense_reimbursement, incident_response, it_acceptable_use, onboarding_checklist, performance_reviews, procurement_policy, refund_policy, remote_work_policy, security_policy, travel_policy).
- Qrels: `/app/datasets/retrieval/demo_qrels_v1.jsonl` (`sha256:12cd0c1eb09bb60be4d154983af32924a7c6a9dddf287d5e963a315b542c2d8a`): 87 queries, 82 answerable + 5 unanswerable (abstention cases, excluded from recall means).
- Difficulty mix (answerable): easy: 30, hard: 18, medium: 34.
- Tags: access: 1, air: 1, appeals: 1, approvals: 2, backups: 1, benefits: 10, booking: 1, communication: 2, compensation: 1, deadline: 2, devices: 1, eap: 1, email: 2, ethics: 1, expenses: 8, feedback: 1, forms: 4, goals: 1, governance: 1, ground: 1, handbook: 3, hard_negative: 15, hard_negative_target: 1, health: 2, incident: 9, it: 9, leave: 2, lodging: 1, meals: 1, mfa: 1, mileage: 1, money: 3, multi_doc: 9, offboarding: 1, on_call: 1, onboarding: 6, paraphrase: 18, passwords: 3, payment: 3, performance: 7, pip: 1, postmortem: 1, privacy: 2, probation: 1, procurement: 8, pto: 3, refund: 4, remote_work: 9, retention: 9, retirement: 2, roles: 1, secrets: 1, security: 6, severity: 1, sla: 1, stipend: 1, thresholds: 2, training: 1, travel: 8, unanswerable: 5.
- Relevance definition: chunk relevant iff document_id matches and normalized chunk text contains normalized must_contain (case/whitespace-insensitive); must_contain <= 32 chars.

## Method

- **dense**: exact brute-force cosine over L2-normalized embeddings (numpy); equivalent to Chroma HNSW cosine on the same vectors up to ANN approximation.
- **bm25**: Okapi BM25 k1=1.5 b=0.75, lowercase alphanumeric tokens.
- **hybrid_rrf**: reciprocal rank fusion of dense and BM25 rankings, k=60.
- **latency**: per-query scoring time including query embedding; excludes index build.
- Chunking configs (chunk_size/overlap, characters): 256/32, 512/64, 1024/128; production is 512/64. Chunk counts: 256/32 -> 150, 512/64 -> 77, 1024/128 -> 43.
- Embedding models:
  - `sentence-transformers/all-MiniLM-L6-v2`: ok (project embedder (Settings-locked))
  - `BAAI/bge-small-en-v1.5`: ok (sentence-transformers direct load)
  - `sentence-transformers/all-mpnet-base-v2`: ok (sentence-transformers direct load)

## Results (all answerable queries)

| config | retriever | chunks | n | Hit@1 | R@1 | R@3 | R@5 | R@10 | MRR | nDCG@5 | nDCG@10 | lat ms |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 256/32 | bm25 | 150 | 82 | 0.732 | 0.669 | 0.801 | 0.868 | 0.898 | 0.797 | 0.801 | 0.812 | 5.771 |
| 256/32 | dense (all-MiniLM-L6-v2) | 150 | 82 | 0.744 | 0.689 | 0.864 | 0.929 | 0.972 | 0.838 | 0.846 | 0.863 | 839.963 |
| 256/32 | hybrid_rrf (all-MiniLM-L6-v2) | 150 | 82 | 0.829 | 0.754 | 0.850 | 0.904 | 0.939 | 0.869 | 0.858 | 0.871 | 662.313 |
| 256/32 | dense (bge-small-en-v1.5) | 150 | 82 | 0.780 | 0.711 | 0.935 | 0.947 | 0.963 | 0.870 | 0.875 | 0.882 | 1047.755 |
| 256/32 | hybrid_rrf (bge-small-en-v1.5) | 150 | 82 | 0.793 | 0.724 | 0.874 | 0.896 | 0.951 | 0.854 | 0.848 | 0.867 | 1252.681 |
| 256/32 | dense (all-mpnet-base-v2) | 150 | 82 | 0.744 | 0.689 | 0.906 | 0.949 | 0.968 | 0.850 | 0.859 | 0.865 | 2378.937 |
| 256/32 | hybrid_rrf (all-mpnet-base-v2) | 150 | 82 | 0.817 | 0.748 | 0.852 | 0.911 | 0.939 | 0.864 | 0.858 | 0.868 | 2318.924 |
| 512/64 | bm25 | 77 | 82 | 0.756 | 0.689 | 0.860 | 0.890 | 0.902 | 0.816 | 0.825 | 0.830 | 2.081 |
| 512/64 | dense (all-MiniLM-L6-v2) **[production]** | 77 | 82 | 0.744 | 0.681 | 0.904 | 0.947 | 0.970 | 0.849 | 0.860 | 0.869 | 427.102 |
| 512/64 | hybrid_rrf (all-MiniLM-L6-v2) | 77 | 82 | 0.744 | 0.683 | 0.872 | 0.919 | 0.959 | 0.828 | 0.838 | 0.852 | 454.828 |
| 512/64 | dense (bge-small-en-v1.5) | 77 | 82 | 0.817 | 0.748 | 0.947 | 0.972 | 0.984 | 0.889 | 0.901 | 0.905 | 721.073 |
| 512/64 | hybrid_rrf (bge-small-en-v1.5) | 77 | 82 | 0.805 | 0.738 | 0.908 | 0.925 | 0.959 | 0.867 | 0.870 | 0.883 | 871.078 |
| 512/64 | dense (all-mpnet-base-v2) | 77 | 82 | 0.695 | 0.632 | 0.856 | 0.929 | 0.990 | 0.805 | 0.815 | 0.838 | 2580.580 |
| 512/64 | hybrid_rrf (all-mpnet-base-v2) | 77 | 82 | 0.756 | 0.689 | 0.878 | 0.931 | 0.978 | 0.842 | 0.848 | 0.865 | 2359.118 |
| 1024/128 | bm25 | 43 | 82 | 0.854 | 0.774 | 0.896 | 0.925 | 0.949 | 0.893 | 0.889 | 0.899 | 1.068 |
| 1024/128 | dense (all-MiniLM-L6-v2) | 43 | 82 | 0.829 | 0.748 | 0.929 | 0.959 | 0.970 | 0.895 | 0.893 | 0.898 | 848.536 |
| 1024/128 | hybrid_rrf (all-MiniLM-L6-v2) | 43 | 82 | 0.854 | 0.774 | 0.919 | 0.941 | 0.972 | 0.909 | 0.903 | 0.914 | 871.980 |
| 1024/128 | dense (bge-small-en-v1.5) | 43 | 82 | 0.854 | 0.760 | 0.911 | 0.978 | 0.994 | 0.914 | 0.910 | 0.916 | 1588.366 |
| 1024/128 | hybrid_rrf (bge-small-en-v1.5) | 43 | 82 | 0.866 | 0.787 | 0.931 | 0.953 | 0.996 | 0.919 | 0.914 | 0.928 | 1359.440 |
| 1024/128 | dense (all-mpnet-base-v2) | 43 | 82 | 0.732 | 0.650 | 0.947 | 0.965 | 0.982 | 0.846 | 0.862 | 0.869 | 2710.198 |
| 1024/128 | hybrid_rrf (all-mpnet-base-v2) | 43 | 82 | 0.842 | 0.762 | 0.900 | 0.949 | 0.996 | 0.899 | 0.896 | 0.914 | 2984.152 |

## Per-difficulty breakdown (MRR / R@5 / nDCG@10)

| config | retriever | easy (n) | hard (n) | medium (n) |
|---|---|---|---|---|
| 256/32 | bm25 | 0.880 / 1.000 / 0.911 (30) | 0.861 / 0.815 / 0.816 (18) | 0.690 / 0.779 / 0.722 (34) |
| 256/32 | dense (all-MiniLM-L6-v2) | 0.825 / 0.950 / 0.864 (30) | 0.838 / 0.926 / 0.837 (18) | 0.850 / 0.912 / 0.875 (34) |
| 256/32 | hybrid_rrf (all-MiniLM-L6-v2) | 0.918 / 1.000 / 0.931 (30) | 0.909 / 0.870 / 0.879 (18) | 0.805 / 0.838 / 0.812 (34) |
| 256/32 | dense (bge-small-en-v1.5) | 0.829 / 0.983 / 0.866 (30) | 0.852 / 0.926 / 0.845 (18) | 0.917 / 0.926 / 0.914 (34) |
| 256/32 | hybrid_rrf (bge-small-en-v1.5) | 0.889 / 1.000 / 0.915 (30) | 0.849 / 0.833 / 0.851 (18) | 0.825 / 0.838 / 0.833 (34) |
| 256/32 | dense (all-mpnet-base-v2) | 0.842 / 0.950 / 0.871 (30) | 0.852 / 0.935 / 0.847 (18) | 0.855 / 0.956 / 0.870 (34) |
| 256/32 | hybrid_rrf (all-mpnet-base-v2) | 0.903 / 1.000 / 0.927 (30) | 0.881 / 0.898 / 0.861 (18) | 0.821 / 0.838 / 0.821 (34) |
| 512/64 | bm25 | 0.944 / 1.000 / 0.959 (30) | 0.907 / 0.889 / 0.878 (18) | 0.654 / 0.794 / 0.692 (34) |
| 512/64 | dense (all-MiniLM-L6-v2) **[production]** | 0.864 / 1.000 / 0.901 (30) | 0.917 / 0.889 / 0.887 (18) | 0.799 / 0.931 / 0.833 (34) |
| 512/64 | hybrid_rrf (all-MiniLM-L6-v2) | 0.944 / 1.000 / 0.956 (30) | 0.903 / 0.944 / 0.886 (18) | 0.686 / 0.833 / 0.742 (34) |
| 512/64 | dense (bge-small-en-v1.5) | 0.907 / 1.000 / 0.932 (30) | 0.907 / 0.944 / 0.887 (18) | 0.864 / 0.961 / 0.890 (34) |
| 512/64 | hybrid_rrf (bge-small-en-v1.5) | 0.967 / 1.000 / 0.973 (30) | 0.931 / 0.944 / 0.915 (18) | 0.746 / 0.848 / 0.787 (34) |
| 512/64 | dense (all-mpnet-base-v2) | 0.815 / 0.950 / 0.857 (30) | 0.798 / 0.917 / 0.808 (18) | 0.801 / 0.917 / 0.836 (34) |
| 512/64 | hybrid_rrf (all-mpnet-base-v2) | 0.911 / 1.000 / 0.929 (30) | 0.931 / 0.972 / 0.904 (18) | 0.734 / 0.848 / 0.787 (34) |
| 1024/128 | bm25 | 0.983 / 1.000 / 0.988 (30) | 0.972 / 0.972 / 0.947 (18) | 0.772 / 0.833 / 0.795 (34) |
| 1024/128 | dense (all-MiniLM-L6-v2) | 0.922 / 0.983 / 0.929 (30) | 0.917 / 0.944 / 0.887 (18) | 0.860 / 0.946 / 0.876 (34) |
| 1024/128 | hybrid_rrf (all-MiniLM-L6-v2) | 0.983 / 0.983 / 0.982 (30) | 1.000 / 0.972 / 0.960 (18) | 0.796 / 0.887 / 0.830 (34) |
| 1024/128 | dense (bge-small-en-v1.5) | 0.967 / 0.983 / 0.963 (30) | 0.917 / 0.944 / 0.887 (18) | 0.867 / 0.990 / 0.891 (34) |
| 1024/128 | hybrid_rrf (bge-small-en-v1.5) | 1.000 / 1.000 / 0.995 (30) | 1.000 / 0.972 / 0.969 (18) | 0.806 / 0.902 / 0.848 (34) |
| 1024/128 | dense (all-mpnet-base-v2) | 0.862 / 0.983 / 0.884 (30) | 0.880 / 0.944 / 0.875 (18) | 0.813 / 0.961 / 0.852 (34) |
| 1024/128 | hybrid_rrf (all-mpnet-base-v2) | 0.958 / 0.983 / 0.963 (30) | 1.000 / 0.972 / 0.976 (18) | 0.792 / 0.907 / 0.837 (34) |

## Worst queries (production config, dense MiniLM)

| query_id | difficulty | first relevant rank | query | relevant chunks | retrieved top-5 |
|---|---|---|---|---|---|
| rq_043 | medium | n/a | How much notice is needed before taking vacation days? | employee_handbook:c000 | benefits_overview:c003, travel_policy:c001, travel_policy:c000, remote_work_policy:c000, onboarding_checklist:c003 |
| rq_035 | medium | 6 | My laptop was stolen on the train. What do I do and how quickly? | it_acceptable_use:c003, remote_work_policy:c006 | onboarding_checklist:c006, onboarding_checklist:c000, onboarding_checklist:c001, it_acceptable_use:c002, travel_policy:c005 |
| rq_020 | easy | 4 | Which form is used to request a data retention exception? | data_retention:c004 | data_retention:c002, data_retention:c003, data_retention:c000, data_retention:c004, procurement_policy:c006 |
| rq_055 | medium | 4 | How soon after approval are expenses reimbursed? | expense_reimbursement:c005 | expense_reimbursement:c006, expense_reimbursement:c001, expense_reimbursement:c000, expense_reimbursement:c005, expense_reimbursement:c002 |
| rq_062 | medium | 4 | What rental car class should employees book? | travel_policy:c003 | travel_policy:c004, expense_reimbursement:c004, travel_policy:c001, travel_policy:c003, travel_policy:c000 |

## Abstention cases (unanswerable queries, production config)

These queries have no relevant chunk anywhere in the corpus. A retriever always returns something; the question is whether its top-1 score separates them from answerable queries.

- **bm25**: answerable top-1 score mean 13.606 (min 4.545); unanswerable top-1 mean 6.667.
  - rq_083: "What is the company's policy on bringing pets to the office?" -> it_acceptable_use:c004 (7.210)
  - rq_084: "How many stock options do new engineers receive?" -> incident_response:c006 (7.104)
  - rq_085: "What is the dress code for client meetings?" -> expense_reimbursement:c003 (5.291)
  - rq_086: "Which airline is the company's preferred carrier?" -> expense_reimbursement:c001 (5.981)
  - rq_087: "What is the maximum attachment size for company email?" -> it_acceptable_use:c004 (7.747)
- **dense::sentence-transformers/all-MiniLM-L6-v2**: answerable top-1 score mean 0.580 (min 0.300); unanswerable top-1 mean 0.369.
  - rq_083: "What is the company's policy on bringing pets to the office?" -> remote_work_policy:c002 (0.365)
  - rq_084: "How many stock options do new engineers receive?" -> incident_response:c006 (0.512)
  - rq_085: "What is the dress code for client meetings?" -> procurement_policy:c002 (0.314)
  - rq_086: "Which airline is the company's preferred carrier?" -> travel_policy:c002 (0.344)
  - rq_087: "What is the maximum attachment size for company email?" -> data_retention:c001 (0.310)
- **hybrid_rrf::sentence-transformers/all-MiniLM-L6-v2**: answerable top-1 score mean n/a (min n/a); unanswerable top-1 mean n/a.
  - rq_083: "What is the company's policy on bringing pets to the office?" -> it_acceptable_use:c004 (n/a)
  - rq_084: "How many stock options do new engineers receive?" -> incident_response:c006 (n/a)
  - rq_085: "What is the dress code for client meetings?" -> procurement_policy:c002 (n/a)
  - rq_086: "Which airline is the company's preferred carrier?" -> travel_policy:c004 (n/a)
  - rq_087: "What is the maximum attachment size for company email?" -> it_acceptable_use:c004 (n/a)
- **dense::BAAI/bge-small-en-v1.5**: answerable top-1 score mean 0.770 (min 0.630); unanswerable top-1 mean 0.639.
  - rq_083: "What is the company's policy on bringing pets to the office?" -> expense_reimbursement:c000 (0.623)
  - rq_084: "How many stock options do new engineers receive?" -> incident_response:c006 (0.669)
  - rq_085: "What is the dress code for client meetings?" -> procurement_policy:c005 (0.641)
  - rq_086: "Which airline is the company's preferred carrier?" -> travel_policy:c002 (0.622)
  - rq_087: "What is the maximum attachment size for company email?" -> it_acceptable_use:c002 (0.642)
- **hybrid_rrf::BAAI/bge-small-en-v1.5**: answerable top-1 score mean n/a (min n/a); unanswerable top-1 mean n/a.
  - rq_083: "What is the company's policy on bringing pets to the office?" -> it_acceptable_use:c004 (n/a)
  - rq_084: "How many stock options do new engineers receive?" -> incident_response:c006 (n/a)
  - rq_085: "What is the dress code for client meetings?" -> procurement_policy:c002 (n/a)
  - rq_086: "Which airline is the company's preferred carrier?" -> travel_policy:c004 (n/a)
  - rq_087: "What is the maximum attachment size for company email?" -> it_acceptable_use:c004 (n/a)
- **dense::sentence-transformers/all-mpnet-base-v2**: answerable top-1 score mean 0.574 (min 0.336); unanswerable top-1 mean 0.387.
  - rq_083: "What is the company's policy on bringing pets to the office?" -> it_acceptable_use:c004 (0.373)
  - rq_084: "How many stock options do new engineers receive?" -> incident_response:c006 (0.493)
  - rq_085: "What is the dress code for client meetings?" -> expense_reimbursement:c003 (0.275)
  - rq_086: "Which airline is the company's preferred carrier?" -> travel_policy:c002 (0.396)
  - rq_087: "What is the maximum attachment size for company email?" -> it_acceptable_use:c005 (0.396)
- **hybrid_rrf::sentence-transformers/all-mpnet-base-v2**: answerable top-1 score mean n/a (min n/a); unanswerable top-1 mean n/a.
  - rq_083: "What is the company's policy on bringing pets to the office?" -> it_acceptable_use:c004 (n/a)
  - rq_084: "How many stock options do new engineers receive?" -> incident_response:c006 (n/a)
  - rq_085: "What is the dress code for client meetings?" -> expense_reimbursement:c003 (n/a)
  - rq_086: "Which airline is the company's preferred carrier?" -> procurement_policy:c003 (n/a)
  - rq_087: "What is the maximum attachment size for company email?" -> it_acceptable_use:c005 (n/a)

## Interpretation

<!-- interpretation:start -->
**What the numbers show**

- The production configuration (512/64 chunks, dense MiniLM) reaches Hit@1 0.744, Recall@5 0.947, MRR 0.849 and nDCG@10 0.869 on 82 answerable queries. Roughly three quarters of queries put a relevant chunk first and 95% have one in the top 5; the default `top_k=5` is therefore adequate for this corpus, and the remaining misses are rank-1 misses rather than total misses.
- Dense retrieval beats BM25 where it should: BM25 is as good or better on *easy* queries that reuse the document's wording (MRR 0.944 vs 0.864 at 512/64) and clearly worse on *medium* paraphrased queries (0.654 vs 0.799). The hard-negative queries that share numbers across policies ("10 business days", "$300", "7 years") are handled similarly by both.
- Hybrid RRF is not a free win. At 512/64 it is slightly *worse* than dense alone (MRR 0.828 vs 0.849) because BM25's paraphrase failures drag medium queries down; at 256/32 and 1024/128 it gives a small gain (+3 and +1.4 MRR points). With a reranker or a weighted fusion this might change; plain RRF with k=60 does not justify the extra index here.
- Embedding model matters more than fusion: `BAAI/bge-small-en-v1.5` (same 384-dim size class as MiniLM) improves the production configuration to Hit@1 0.817, Recall@5 0.972, MRR 0.889, nDCG@10 0.905, a consistent gain across all three chunk sizes and all difficulty levels. `all-mpnet-base-v2` (768-dim, slower) is *worse* than MiniLM on this corpus (MRR 0.805 at 512/64). The best cell in the grid is 1024/128 with bge-small (dense MRR 0.914, hybrid 0.919, nDCG@10 0.928).
- Larger chunks score higher for every retriever (1024/128 dense MiniLM: MRR 0.895 vs 0.849). Part of that is real (a section is rarely split), part is an artifact of the metric: with 43 chunks instead of 77 each hit is easier and the relevant span is more likely to sit inside one chunk. Larger chunks also cost more prompt tokens per retrieved item, which this table does not measure.
- The worst production queries are vocabulary mismatches: "notice before taking vacation days" never reaches the PTO chunk (the corpus says "PTO", never "vacation"), and "laptop stolen on the train" surfaces onboarding chunks ahead of the IT acceptable-use chunk. These are the cases a query-rewrite step or a better embedding model would fix; BM25 cannot.
- Abstention: a top-1 cosine threshold does not separate unanswerable queries cleanly. Unanswerable queries score 0.31-0.51 at rank 1 with MiniLM while answerable queries range 0.30-0.9x (mean 0.58); "How many stock options do new engineers receive?" scores 0.512 against the on-call stipend chunk, above the weakest answerable queries. The relevance judge, not the retriever score, has to carry abstention decisions; see `judge_validation.md`.

**What they do not show**

- The corpus is 13 short, clean, synthetic-but-realistic policy documents and the 87 queries were written by the same author who wrote the documents. Absolute numbers will be lower on real, noisy corpora with longer documents and user-written queries; the *relative* ordering (dense > BM25 on paraphrase, bge-small > MiniLM > mpnet here, hybrid marginal) is the transferable finding, and even that should be re-checked on the target corpus.
- With 82 answerable queries, a difference of 2-3 MRR points is a handful of queries changing rank and is within noise. Differences of 5+ points that hold across all three chunk sizes (bge-small vs MiniLM, dense vs BM25 on medium queries) are the ones to act on.
- Relevance is substring-based, so a chunk that paraphrases the answer without the labeled substring counts as a miss for every retriever equally.
- Latency is per-query scoring time measured inside the dev container on a 4-core laptop CPU, after one warm-up call; it is only meaningful relative to the other rows of the same run. The run recorded above overlapped with other CPU-heavy jobs (an Ollama judge run and the test suite), which inflates the dense numbers; on an idle machine the same code measures MiniLM dense at roughly 35-50 ms per query and BM25 at under 2 ms.

**Decision for v1.0**: keep 512/64 + MiniLM as the PRD-locked production default (the Settings lock exists for reproducibility of stored corpus versions), record this table as the baseline, and treat "switch the embedding model to bge-small-en-v1.5 behind a new corpus version" as the first retrieval improvement to evaluate on a real corpus. Do not enable hybrid RRF without a reranking step.
<!-- interpretation:end -->
