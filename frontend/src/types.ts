export type NavId = "investigate" | "evaluations" | "experiments" | "operations";

export type CorpusVersion = {
  id: string;
  corpus_id: string;
  status: string;
  chunk_count: number;
  document_count: number;
};

export type CorpusDetail = {
  id: string;
  title: string;
  versions: CorpusVersion[];
};

export type Investigation = {
  execution: {
    execution_id: string;
    request_id: string;
    corpus_version_id: string;
    retrieval_trace_id: string | null;
    query: string;
    status: string;
    error_code: string | null;
    error_message: string | null;
    abstained: boolean;
    abstention_kind: string | null;
    answer: string | null;
    top_k: number;
    generation: {
      model: string | null;
      temperature: number | null;
      prompt_version: string | null;
      latency_ms: number | null;
      prompt_tokens: number | null;
      completion_tokens: number | null;
      total_tokens: number | null;
    };
    latency_ms: {
      retrieval: number | null;
      generation: number | null;
      /** Generate (RAG) request wall-clock; excludes diagnose/judges. */
      total: number | null;
      generate_total?: number | null;
      /** Diagnose request wall-clock (sequential judges included). */
      diagnosis?: number | null;
    };
  };
  diagnosis: {
    diagnosis_id: string;
    failure_code: string;
    rule_id: string;
    layer: string;
    confidence: string | null;
    secondary_codes: string[];
    recommendation_code: string | null;
    evidence_refs: string[];
    taxonomy_version: string;
    /** v1.0: numeric rule score, calibrated probability, deferral flag, explanation. */
    diagnosis_score?: number | null;
    calibrated_confidence?: number | null;
    calibration_version?: string | null;
    uncertain?: boolean;
    review_recommended?: boolean;
    explanation?: string | null;
  } | null;
  rule: {
    rule_id: string;
    result: string;
    layer: string;
    conditions: string[];
    summary: string;
  } | null;
  failure: {
    code: string;
    description: string | null;
    layer: string | null;
    runbook: string | null;
  } | null;
  retrieval: {
    chunks: Array<{
      chunk_id: string | null;
      document_id: string | null;
      source_name: string | null;
      rank: number | null;
      score: number | null;
      text: string | null;
      relevance: Record<string, unknown> | null;
      evidence_status: string;
      is_gold_expected: boolean;
    }>;
    gold_ids: string[];
    gold_hit: boolean | null;
    gold_recall_at_k: number | null;
    n_retrieved: number;
    context_sufficient: boolean | null;
    irrelevant_frac: number | null;
  };
  judges: Array<{
    judge_type: string;
    status: string;
    schema_ok: boolean;
    model: string;
    prompt_version: string;
    latency_ms: number | null;
    attempts: number;
    result: Record<string, unknown>;
    output: Record<string, unknown>;
  }>;
  evidence: Array<{
    evidence_type: string;
    ref: string | null;
    payload: Record<string, unknown> | null;
  }>;
  timeline: Array<{
    operation: string;
    status: string;
    duration_ms: number | null;
    id: string | null;
    phase?: string | null;
  }>;
  why: {
    engine: string;
    note: string;
    signals_used: Record<string, unknown>;
    rule: Investigation["rule"];
    explanation?: string | null;
    calibrated_confidence?: number | null;
    calibration_version?: string | null;
    uncertain?: boolean;
  };
};

/** Per-class precision/recall/F1 row stored in experiment metrics (v1.0). */
export type PerClassMetric = {
  support: number;
  predicted: number;
  tp: number;
  fp: number;
  fn: number;
  precision: number;
  recall: number;
  f1: number;
};

export type SelectiveMetrics = {
  coverage: number | null;
  selective_accuracy: number | null;
  deferred: number;
  deferred_accuracy: number | null;
  uncertain_rate: number | null;
};

export type ExperimentListItem = {
  experiment_id: string;
  name: string | null;
  suite_id: string | null;
  suite_version: string | null;
  suite_hash: string | null;
  status: string;
  created_at: string | null;
  completed_at: string | null;
};

export type ExperimentDetail = {
  experiment_id: string;
  name: string | null;
  suite_id: string | null;
  suite_version: string | null;
  suite_hash: string | null;
  status: string;
  pipeline: Record<string, unknown> | null;
  git_commit: string | null;
  artifact_uri: string | null;
  metrics: Record<string, unknown> | null;
  confusion_matrix: Record<string, unknown> | null;
  created_at: string | null;
  completed_at: string | null;
};

export type CaseResult = {
  case_id: string;
  query: string | null;
  expected_failure_code: string | null;
  expected_rule_id: string | null;
  predicted_failure_code: string | null;
  predicted_rule_id: string | null;
  diagnosis_confidence: string | null;
  evidence_valid: boolean | null;
  passed: boolean | null;
  execution_id: string | null;
  diagnosis_id: string | null;
  latency_ms: number | null;
  error: string | null;
};

export type Comparison = {
  experiment_id: string;
  baseline: Record<string, unknown> | null;
  comparison: {
    passed: boolean;
    violations: unknown[];
    rows: Array<{
      metric: string;
      baseline: number | null;
      current: number | null;
      delta: number | null;
      status?: string;
      [key: string]: unknown;
    }>;
    error_rate?: number | null;
    has_baseline: boolean;
  };
};

export type OpsSummary = {
  ready: boolean;
  readiness_status: string;
  dependencies: Record<string, unknown>;
  metrics: {
    durable: boolean;
    derived: Record<string, number | null>;
    http_latency: Record<string, number | null> | null;
    counters_sample: Record<string, number>;
  };
  signals: {
    alert_count: number;
    signals: Array<{
      signal: string;
      actual: number | null;
      threshold: number;
      status: string;
      description?: string;
    }>;
    metrics_note?: string;
  };
  runbooks_dir?: string;
};

export type EvalRunResult = {
  experiment_id: string;
  suite_id: string;
  suite_version: string;
  suite_hash: string;
  status: string;
  exit_code: number;
  summary: Record<string, unknown>;
  comparison: Record<string, unknown>;
  baseline: Record<string, unknown> | null;
  no_baseline?: boolean;
};

/** Postgres-backed telemetry window (GET /api/v1/metrics/durable, ops summary). */
export type DurableWindow = {
  available: boolean;
  reason?: string | null;
  source?: string;
  window_minutes?: number | null;
  event_count?: number;
  http_latency?: {
    count?: number;
    p50_ms?: number | null;
    p95_ms?: number | null;
    p99_ms?: number | null;
    max_ms?: number | null;
  };
  requests_total?: number;
  requests_5xx?: number;
  request_error_rate?: number | null;
  generation_attempts?: number;
  generation_timeout_rate?: number | null;
  llm_retries?: number;
  llm_failures?: number;
  tokens?: { prompt?: number; completion?: number; total?: number } | null;
  cost_usd?: number | null;
};

export type OpsSummaryV1 = OpsSummary & {
  metrics: OpsSummary["metrics"] & {
    source?: string;
    durable_available?: boolean;
    durable_window?: DurableWindow;
  };
};
