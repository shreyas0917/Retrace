/**
 * Human labels for every backend identifier the console shows.
 *
 * The backend values (failure codes, rule ids, recommendation codes, signal
 * and metric keys, suite ids) are the source of truth and are never changed
 * here. This module only maps them to language a reader can follow. Unknown
 * keys degrade to a readable fallback instead of throwing, so a new backend
 * code never breaks the UI. The failure-code list mirrors
 * backend/app/services/diagnosis/taxonomy.py (a test parses that file and
 * checks every code has an entry here).
 */

export type Severity = "ok" | "medium" | "high" | "unknown";

/** The four places a RAG answer can break, in pipeline order. */
export type StageId = "retrieval" | "context" | "answer" | "abstention";

export type FriendlyDiagnosis = {
  /** One-line plain-English conclusion. */
  title: string;
  /** A sentence explaining what happened, for someone new to RAG. */
  what: string;
  severity: Severity;
  /** Short human category used for grouping. */
  category: string;
};

type FailureEntry = FriendlyDiagnosis & {
  /** Stage the code localizes the failure to; null = infrastructure / no stage. */
  stage: StageId | null;
  /** Reserved in taxonomy 1.0: defined, but no rule emits it yet. */
  reserved?: boolean;
};

export const FAILURE_LABELS: Record<string, FailureEntry> = {
  OK_GROUNDED: {
    title: "The answer was correct and supported by the documents",
    what: "The system retrieved relevant documents and the answer stayed faithful to them.",
    severity: "ok",
    category: "Healthy",
    stage: null,
  },
  OK_CORRECT_ABSTENTION: {
    title: "The system correctly declined to answer",
    what: "There was not enough relevant information to answer, and the system said so instead of guessing.",
    severity: "ok",
    category: "Healthy",
    stage: "abstention",
  },
  RETRIEVAL_EMPTY: {
    title: "No documents were found for this question",
    what: "Search returned nothing, so the system had no information to work from.",
    severity: "high",
    category: "Retrieval",
    stage: "retrieval",
  },
  RETRIEVAL_MISS: {
    title: "The system retrieved the wrong information",
    what: "The document that answers this question exists, but search did not return it in the top results.",
    severity: "high",
    category: "Retrieval",
    stage: "retrieval",
  },
  RETRIEVAL_RANK_TOO_LOW: {
    title: "The right passage was ranked too low",
    what: "The passage that answers the question was found, but ranked below less useful ones.",
    severity: "medium",
    category: "Retrieval",
    stage: "retrieval",
    reserved: true,
  },
  RETRIEVAL_DISTRACTOR_DOMINANT: {
    title: "Mostly irrelevant passages were retrieved",
    what: "Most of the retrieved passages were off-topic, leaving little useful context to answer from.",
    severity: "medium",
    category: "Retrieval",
    stage: "retrieval",
  },
  RETRIEVAL_INSUFFICIENT_CONTEXT: {
    title: "The retrieved passages were not enough to answer",
    what: "Some related passages came back, but together they did not contain the answer.",
    severity: "medium",
    category: "Retrieval",
    stage: "context",
  },
  GROUNDING_UNSUPPORTED: {
    title: "The answer is not grounded in the evidence",
    what: "None of the claims in the answer could be traced back to the retrieved documents.",
    severity: "high",
    category: "Grounding",
    stage: "answer",
  },
  GROUNDING_PARTIAL: {
    title: "The answer is only partly supported",
    what: "Some of the answer is backed by the documents and some of it is not.",
    severity: "medium",
    category: "Grounding",
    stage: "answer",
  },
  GROUNDING_CONTRADICTORY_CONTEXT: {
    title: "The retrieved passages contradict each other",
    what: "Two or more retrieved passages disagree, so the context cannot settle the answer.",
    severity: "medium",
    category: "Grounding",
    stage: "context",
    reserved: true,
  },
  GROUNDING_CITATION_MISMATCH: {
    title: "The answer cites the wrong passage",
    what: "The answer attributes a statement to a passage that does not contain it.",
    severity: "medium",
    category: "Grounding",
    stage: "answer",
    reserved: true,
  },
  GENERATION_HALLUCINATION: {
    title: "The answer contains a claim the documents do not support",
    what: "The documents were adequate, but the answer added details that are not found in them.",
    severity: "high",
    category: "Generation",
    stage: "answer",
  },
  GENERATION_CONTRADICTION: {
    title: "The answer contradicts the retrieved documents",
    what: "The answer states something that conflicts with the evidence that was available.",
    severity: "high",
    category: "Generation",
    stage: "answer",
  },
  GENERATION_BAD_SYNTHESIS: {
    title: "The answer combined the evidence incorrectly",
    what: "The evidence was sufficient, but the answer drew the wrong conclusion from it.",
    severity: "high",
    category: "Generation",
    stage: "answer",
    reserved: true,
  },
  GENERATION_INSTRUCTION_FAIL: {
    title: "The answer broke the generation rules",
    what: "The answer ignored an instruction the system prompt requires it to follow.",
    severity: "medium",
    category: "Generation",
    stage: "answer",
    reserved: true,
  },
  ABSTENTION_FALSE_NEGATIVE: {
    title: "The system answered when it should have declined",
    what: "The evidence was insufficient, but the system produced an answer anyway instead of abstaining.",
    severity: "high",
    category: "Abstention",
    stage: "abstention",
  },
  ABSTENTION_FALSE_POSITIVE: {
    title: "The system declined when it could have answered",
    what: "Enough relevant information was available, but the system abstained instead of answering.",
    severity: "medium",
    category: "Abstention",
    stage: "abstention",
  },
  EVAL_MODEL_TIMEOUT: {
    title: "The request timed out",
    what: "The language model did not respond within the time limit, so no answer was produced.",
    severity: "high",
    category: "Infrastructure",
    stage: null,
  },
  EVAL_JUDGE_MALFORMED: {
    title: "A quality check returned an unreadable result",
    what: "One of the automated judges produced output the system could not parse, even after a retry.",
    severity: "medium",
    category: "Infrastructure",
    stage: null,
  },
  EVAL_MISSING_CONTEXT: {
    title: "There was no answer to assess",
    what: "The execution has no answer text (and did not abstain, time out or fail), so no judge could run.",
    severity: "medium",
    category: "Infrastructure",
    stage: null,
  },
  EVAL_INTERNAL_ERROR: {
    title: "An unexpected error occurred",
    what: "The pipeline hit an unexpected error, or no diagnosis rule matched the signals.",
    severity: "high",
    category: "Infrastructure",
    stage: null,
  },
  DIAGNOSIS_UNCERTAIN: {
    title: "The cause could not be determined confidently",
    what: "The automated judges disagreed or were inconclusive, so this case is flagged for manual review.",
    severity: "medium",
    category: "Uncertain",
    stage: null,
  },
};

/** Every failure code the console knows about, in taxonomy order. */
export const KNOWN_FAILURE_CODES = Object.keys(FAILURE_LABELS);

/** snake_case / SCREAMING_CASE → "Title Case Words". */
export function titleCaseCode(code: string): string {
  return code
    .toLowerCase()
    .split(/[_\s]+/)
    .filter(Boolean)
    .map((w) => w[0].toUpperCase() + w.slice(1))
    .join(" ");
}

/** snake_case → "Sentence case words", the generic fallback label. */
export function humanize(key: string | null | undefined): string {
  if (!key) return "—";
  const words = key
    .replace(/[._:]+/g, " ")
    .replace(/_/g, " ")
    .trim()
    .toLowerCase();
  return words ? words[0].toUpperCase() + words.slice(1) : "—";
}

export function friendlyDiagnosis(
  code: string | null | undefined,
): FriendlyDiagnosis {
  if (!code) {
    return {
      title: "No diagnosis yet",
      what: "This execution has not been diagnosed.",
      severity: "unknown",
      category: "Unknown",
    };
  }
  const known = FAILURE_LABELS[code];
  if (known) {
    const { title, what, severity, category } = known;
    return { title, what, severity, category };
  }
  const isOk = code.startsWith("OK_");
  return {
    title: titleCaseCode(code),
    what: isOk
      ? "The execution completed without a detected problem."
      : "This diagnosis code is not yet described in plain language. See the technical details below.",
    severity: isOk ? "ok" : "unknown",
    category: code.split("_")[0] || "Other",
  };
}

export function failureTitle(code: string | null | undefined): string {
  return friendlyDiagnosis(code).title;
}

export function severityOf(code: string | null | undefined): Severity {
  return friendlyDiagnosis(code).severity;
}

export function isHealthy(code: string | null | undefined): boolean {
  return severityOf(code) === "ok";
}

export function isInfraCode(code: string | null | undefined): boolean {
  return !!code && code.startsWith("EVAL_");
}

/** Label for a severity, used in chips and summaries. */
export function severityLabel(sev: Severity): string {
  switch (sev) {
    case "ok":
      return "Healthy";
    case "high":
      return "Needs attention";
    case "medium":
      return "Worth a look";
    default:
      return "Unknown";
  }
}

// --- Recommendations (taxonomy.py RECOMMENDATIONS values) -------------------

export const RECOMMENDATION_LABELS: Record<
  string,
  { title: string; action: string }
> = {
  CHECK_INDEX: {
    title: "Check the index",
    action:
      "Search returned nothing. Confirm the corpus was ingested and indexed, that the query reaches the right collection, and that the embedding model matches the one used at ingest.",
  },
  TUNE_RETRIEVAL: {
    title: "Tune retrieval",
    action:
      "The right passage exists but was not returned. Try a larger top-k, hybrid or keyword search, query rewriting, or re-chunking the source document.",
  },
  ADD_RERANK_OR_FILTER: {
    title: "Add a re-ranker or filter",
    action:
      "Off-topic passages crowded out useful ones. Add a re-ranking step or a metadata filter so only relevant passages reach the model.",
  },
  INCREASE_K_OR_CHUNK: {
    title: "Retrieve more, or chunk differently",
    action:
      "The passages were related but incomplete. Retrieve more passages or use larger or overlapping chunks so the full answer fits in context.",
  },
  TIGHTEN_GENERATOR: {
    title: "Tighten the generator",
    action:
      "The model went beyond, or against, its evidence. Strengthen the prompt to answer only from the passages, lower the temperature, or add a post-generation check.",
  },
  REQUIRE_CITATIONS: {
    title: "Require citations",
    action:
      "Part of the answer was unsupported. Require the model to cite a passage for each claim and drop claims it cannot cite.",
  },
  ENFORCE_ABSTAIN: {
    title: "Enforce abstention",
    action:
      "The model answered without enough evidence. Make the prompt require declining when the passages do not contain the answer, and test that path.",
  },
  RELAX_ABSTAIN_OR_RETRIEVAL: {
    title: "Relax abstention, or check retrieval",
    action:
      "The model declined although the evidence was there. Loosen the abstention instruction, or check whether the right passage reached the prompt.",
  },
  FIX_PIPELINE: {
    title: "Fix the pipeline",
    action:
      "This is an infrastructure problem, not an answer-quality one. Check timeouts, judge output parsing and the logs for this request, then re-run it.",
  },
  MANUAL_REVIEW: {
    title: "Review by hand",
    action:
      "The judges disagreed, so the engine did not localize the failure. Read the answer against the evidence below and label it yourself.",
  },
  NONE: {
    title: "Nothing to fix",
    action:
      "This answer behaved correctly. You can keep it as a positive reference case.",
  },
};

export function recommendationLabel(code: string | null | undefined): {
  title: string;
  action: string;
} {
  if (!code) {
    return {
      title: "No recommendation",
      action: "The diagnosis did not include a recommendation.",
    };
  }
  return (
    RECOMMENDATION_LABELS[code] || {
      title: titleCaseCode(code),
      action: "See the runbook and the evidence below.",
    }
  );
}

// --- Diagnosis signals (investigation.why.signals_used) ---------------------

export const SIGNAL_LABELS: Record<string, { label: string; help: string }> = {
  n_retrieved: {
    label: "Passages retrieved",
    help: "How many chunks the retriever returned for this query.",
  },
  gold_hit: {
    label: "Expected passage retrieved",
    help: "Whether at least one gold (known-correct) chunk was in the retrieved set. Only evaluated when gold chunk ids were supplied.",
  },
  gold_recall_at_k: {
    label: "Gold recall at k",
    help: "Share of gold chunks that appear in the top-k results.",
  },
  context_sufficient: {
    label: "Context sufficient",
    help: "The relevance judge's verdict on whether the retrieved passages together contain enough to answer.",
  },
  answer_is_abstention: {
    label: "Answer is an abstention",
    help: "Whether the system declined to answer (explicitly or by a refusal phrase).",
  },
  answer_contradicts_context: {
    label: "Answer contradicts context",
    help: "The contradiction judge's verdict on whether the answer conflicts with the passages.",
  },
  faithfulness_score: {
    label: "Faithfulness score",
    help: "Share of answer claims supported by the passages (0 to 1), from the faithfulness judge.",
  },
  unsupported_claim_count: {
    label: "Unsupported claims",
    help: "Answer claims the faithfulness judge could not find in the passages.",
  },
  supported_claim_count: {
    label: "Supported claims",
    help: "Answer claims the faithfulness judge found in the passages.",
  },
  irrelevant_frac: {
    label: "Irrelevant share",
    help: "Share of retrieved passages the relevance judge marked as irrelevant (0 to 1).",
  },
  stage_error: {
    label: "Stage error",
    help: "An error recorded by the generate stage, such as a timeout. Empty when the stage succeeded.",
  },
  judge_schema_ok: {
    label: "Judge output valid",
    help: "Whether every judge returned output that matched its schema.",
  },
  missing_answer: {
    label: "Answer missing",
    help: "No answer text was recorded for this execution.",
  },
};

export function signalLabel(key: string): { label: string; help: string } {
  return SIGNAL_LABELS[key] || { label: humanize(key), help: key };
}

// --- Evaluation metrics ------------------------------------------------------

export const METRIC_LABELS: Record<string, { label: string; help: string }> = {
  failure_code_accuracy: {
    label: "Failure-code accuracy",
    help: "Share of cases where the predicted failure code equals the expected one.",
  },
  rule_accuracy: {
    label: "Rule accuracy",
    help: "Share of cases where the rule that fired equals the expected rule.",
  },
  evidence_accuracy: {
    label: "Evidence accuracy",
    help: "Share of cases whose evidence references are valid (they point at the right chunks).",
  },
  strict_accuracy: {
    label: "Strict accuracy",
    help: "Share of cases where code, rule and evidence are all correct.",
  },
  macro_f1: {
    label: "Macro-F1",
    help: "Unweighted mean of per-class F1: every failure class counts equally, however rare.",
  },
  micro_f1: {
    label: "Micro-F1",
    help: "F1 over all predictions pooled together.",
  },
  weighted_f1: {
    label: "Weighted F1",
    help: "Per-class F1 averaged by class support.",
  },
  total_cases: { label: "Cases", help: "Number of cases in the suite run." },
  correct: { label: "Correct", help: "Cases whose failure code matched." },
  incorrect: { label: "Incorrect", help: "Cases whose failure code did not match." },
  coverage: {
    label: "Coverage",
    help: "Share of cases the engine answered confidently instead of deferring as uncertain.",
  },
  selective_accuracy: {
    label: "Selective accuracy",
    help: "Accuracy on the cases the engine did not defer.",
  },
  uncertain_rate: {
    label: "Deferred as uncertain",
    help: "Share of cases the engine flagged for manual review.",
  },
  deferred: { label: "Deferred cases", help: "Cases flagged for manual review." },
  error_rate: {
    label: "Error rate",
    help: "Share of cases that did not match (incorrect / total).",
  },
};

export function metricLabel(key: string): { label: string; help: string } {
  return METRIC_LABELS[key] || { label: humanize(key), help: key };
}

// --- Suites ------------------------------------------------------------------

export const SUITE_LABELS: Record<string, { label: string; help: string }> = {
  planted_v1: {
    label: "Planted scenarios",
    help: "Hand-planted failure scenarios with recorded judge outputs; fast and fully reproducible.",
  },
  heldout_v1: {
    label: "Held-out benchmark",
    help: "Held-out cases not used to tune rules or thresholds.",
  },
  calib_v1: {
    label: "Calibration set",
    help: "Cases used to fit the confidence calibration.",
  },
  gold_v1: {
    label: "Gold set",
    help: "Hand-labelled gold cases.",
  },
  live_v1: {
    label: "Live recorded runs",
    help: "Recorded real pipeline runs, labelled by hand. Not run from the console automatically.",
  },
};

export function suiteLabel(id: string | null | undefined): string {
  if (!id) return "—";
  return SUITE_LABELS[id]?.label || humanize(id);
}

// --- Operations signals -----------------------------------------------------

export const OPS_SIGNAL_LABELS: Record<
  string,
  { label: string; help: string; unit: "rate" | "ms" }
> = {
  request_error_rate: {
    label: "Request error rate",
    help: "Share of HTTP requests answered with a 5xx error.",
    unit: "rate",
  },
  p95_latency_ms: {
    label: "p95 latency",
    help: "95% of HTTP requests were faster than this.",
    unit: "ms",
  },
  generation_timeout_rate: {
    label: "Generation timeout rate",
    help: "Share of generation attempts that timed out.",
    unit: "rate",
  },
  retrieval_miss_rate: {
    label: "Retrieval miss rate",
    help: "Share of diagnoses where the expected passage was not retrieved.",
    unit: "rate",
  },
  retrieval_empty_rate: {
    label: "Empty retrieval rate",
    help: "Share of retrievals that returned no passages.",
    unit: "rate",
  },
  judge_timeout_rate: {
    label: "Judge timeout rate",
    help: "Share of judge calls that timed out.",
    unit: "rate",
  },
  judge_malformed_rate: {
    label: "Malformed judge output rate",
    help: "Share of judge calls whose output failed its schema after retry.",
    unit: "rate",
  },
};

export function opsSignalLabel(key: string): {
  label: string;
  help: string;
  unit: "rate" | "ms";
} {
  return (
    OPS_SIGNAL_LABELS[key] || {
      label: humanize(key),
      help: key,
      unit: key.endsWith("_ms") ? "ms" : "rate",
    }
  );
}

// --- Statuses and small vocabularies ----------------------------------------

export const STATUS_LABELS: Record<string, string> = {
  OK: "OK",
  ALERT: "Alert",
  INSUFFICIENT_DATA: "Not enough data",
  PASS: "Pass",
  FAIL: "Fail",
  IMPROVED: "Improved",
  UNCHANGED: "Unchanged",
  "N/A": "Not available",
  REGRESSION: "Regression",
  ERROR: "Error",
  NO_BASELINE: "No baseline",
  COMPLETED: "Completed",
  FAILED: "Failed",
  RUNNING: "Running",
  PENDING: "Pending",
  ABSTAINED: "Abstained",
  TIMEOUT: "Timed out",
  READY: "Ready",
  NOT_READY: "Not ready",
};

export function statusLabel(status: string | null | undefined): string {
  if (!status) return "—";
  return STATUS_LABELS[status] || STATUS_LABELS[status.toUpperCase()] || humanize(status);
}

export const JUDGE_LABELS: Record<string, { label: string; help: string }> = {
  relevance: {
    label: "Context relevance",
    help: "Marks each retrieved passage relevant or not and decides whether the context is sufficient to answer.",
  },
  faithfulness: {
    label: "Faithfulness",
    help: "Splits the answer into claims and checks each one against the passages.",
  },
  contradiction: {
    label: "Contradiction",
    help: "Checks whether the answer conflicts with the passages.",
  },
};

export function judgeLabel(type: string): string {
  return JUDGE_LABELS[type]?.label || humanize(type);
}

export const EVIDENCE_STATUS_HELP: Record<string, string> = {
  expected: "A gold (known-correct) passage that was retrieved.",
  relevant: "The relevance judge marked this passage relevant.",
  distractor: "The relevance judge marked this passage irrelevant.",
  missing: "A gold passage that the retriever did not return.",
  retrieved: "Retrieved, but not judged relevant or irrelevant.",
};

export const LAYER_LABELS: Record<string, string> = {
  retrieval: "Retrieval",
  grounding: "Grounding",
  generation: "Generation",
  abstention: "Abstention",
  infra: "Infrastructure",
  none: "None",
  uncertain: "Uncertain",
};

export function layerLabel(layer: string | null | undefined): string {
  if (!layer) return "—";
  return LAYER_LABELS[layer.toLowerCase()] || humanize(layer);
}

export const ABSTENTION_KIND_LABELS: Record<string, string> = {
  CORRECT_ABSTENTION: "Correct abstention",
  FALSE_NEGATIVE_ABSTENTION: "Should have abstained",
  FALSE_POSITIVE_ABSTENTION: "Abstained unnecessarily",
  ABSTAINED: "Abstained",
};

export function abstentionDetectedByLabel(value: string | null | undefined): string {
  if (!value) return "—";
  if (value === "explicit") return "Sent explicitly in the trace";
  if (value === "sentinel") return "Answer was the INSUFFICIENT_CONTEXT sentinel";
  if (value === "none") return "No abstention detected";
  if (value.startsWith("refusal_phrase:")) {
    return `Refusal phrase “${value.slice("refusal_phrase:".length)}”`;
  }
  return humanize(value);
}

export function timelineLabel(operation: string): string {
  if (operation.startsWith("judge:")) {
    return `${judgeLabel(operation.slice(6))} judge`;
  }
  return humanize(operation);
}
