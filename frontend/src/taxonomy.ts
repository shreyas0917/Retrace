/**
 * Plain-English layer over the backend failure taxonomy.
 *
 * The backend values (failure_code, layer) are the source of truth and are
 * never changed here — this module only maps each code to language a
 * non-technical reader can follow. Unknown codes degrade to a readable
 * fallback rather than throwing, so a new backend code never breaks the UI.
 */

export type Severity = "ok" | "medium" | "high" | "unknown";

export type FriendlyDiagnosis = {
  /** One-line plain-English conclusion. */
  title: string;
  /** A sentence explaining what happened, for someone new to RAG. */
  what: string;
  severity: Severity;
  /** Short human category used for grouping on the overview. */
  category: string;
};

const MAP: Record<string, FriendlyDiagnosis> = {
  OK_GROUNDED: {
    title: "The answer was correct and supported by the documents",
    what: "The system retrieved relevant documents and the answer stayed faithful to them.",
    severity: "ok",
    category: "Healthy",
  },
  OK_CORRECT_ABSTENTION: {
    title: "The system correctly declined to answer",
    what: "There was not enough relevant information to answer, and the system said so instead of guessing.",
    severity: "ok",
    category: "Healthy",
  },
  RETRIEVAL_EMPTY: {
    title: "No documents were found for this question",
    what: "Search returned nothing, so the system had no information to work from.",
    severity: "high",
    category: "Retrieval",
  },
  RETRIEVAL_MISS: {
    title: "The system retrieved the wrong information",
    what: "The document that answers this question exists, but search did not return it in the top results.",
    severity: "high",
    category: "Retrieval",
  },
  RETRIEVAL_DISTRACTOR_DOMINANT: {
    title: "Mostly irrelevant passages were retrieved",
    what: "Most of the retrieved passages were off-topic, leaving little useful context to answer from.",
    severity: "medium",
    category: "Retrieval",
  },
  RETRIEVAL_INSUFFICIENT_CONTEXT: {
    title: "The retrieved passages were not enough to answer",
    what: "Some related passages came back, but together they did not contain the answer.",
    severity: "medium",
    category: "Retrieval",
  },
  GENERATION_HALLUCINATION: {
    title: "The answer contains a claim the documents do not support",
    what: "The documents were adequate, but the answer added details that are not found in them.",
    severity: "high",
    category: "Generation",
  },
  GENERATION_CONTRADICTION: {
    title: "The answer contradicts the retrieved documents",
    what: "The answer states something that conflicts with the evidence that was available.",
    severity: "high",
    category: "Generation",
  },
  GROUNDING_UNSUPPORTED: {
    title: "The answer is not grounded in the evidence",
    what: "None of the claims in the answer could be traced back to the retrieved documents.",
    severity: "high",
    category: "Grounding",
  },
  GROUNDING_PARTIAL: {
    title: "The answer is only partly supported",
    what: "Some of the answer is backed by the documents and some of it is not.",
    severity: "medium",
    category: "Grounding",
  },
  ABSTENTION_FALSE_NEGATIVE: {
    title: "The system answered when it should have declined",
    what: "The evidence was insufficient, but the system produced an answer anyway instead of abstaining.",
    severity: "high",
    category: "Abstention",
  },
  ABSTENTION_FALSE_POSITIVE: {
    title: "The system declined when it could have answered",
    what: "Enough relevant information was available, but the system abstained instead of answering.",
    severity: "medium",
    category: "Abstention",
  },
  EVAL_MODEL_TIMEOUT: {
    title: "The request timed out",
    what: "The language model did not respond within the time limit, so no answer was produced.",
    severity: "high",
    category: "Infrastructure",
  },
  EVAL_JUDGE_MALFORMED: {
    title: "A quality check returned an unreadable result",
    what: "One of the automated judges produced output the system could not parse, even after a retry.",
    severity: "medium",
    category: "Infrastructure",
  },
  EVAL_MISSING_CONTEXT: {
    title: "Required context was missing",
    what: "Information the diagnosis needed was not available for this execution.",
    severity: "medium",
    category: "Infrastructure",
  },
  EVAL_INTERNAL_ERROR: {
    title: "An unexpected error occurred",
    what: "The pipeline hit an unexpected error while processing this execution.",
    severity: "high",
    category: "Infrastructure",
  },
  DIAGNOSIS_UNCERTAIN: {
    title: "The cause could not be determined confidently",
    what: "The automated judges disagreed or were inconclusive, so this case is flagged for manual review.",
    severity: "medium",
    category: "Uncertain",
  },
};

function titleCaseCode(code: string): string {
  return code
    .toLowerCase()
    .split("_")
    .map((w) => (w ? w[0].toUpperCase() + w.slice(1) : w))
    .join(" ");
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
  const known = MAP[code];
  if (known) return known;
  // Unknown code: derive a neutral, readable fallback from its shape.
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

export function severityOf(code: string | null | undefined): Severity {
  return friendlyDiagnosis(code).severity;
}

export function isHealthy(code: string | null | undefined): boolean {
  return severityOf(code) === "ok";
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
