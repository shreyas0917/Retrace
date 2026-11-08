/**
 * Stage strip logic: which of the four pipeline stages a failure code breaks.
 *
 * Rules are first-match (backend/app/services/diagnosis/rules.py): R00-R02
 * infrastructure, R10-R12 retrieval, R14/R20/R21 context sufficiency and
 * abstention, R30-R34 the answer itself, R40 grounded, R90 uncertain, R99
 * fallback. Once a rule fires, later checks never run, so stages after the
 * one that broke are "not assessed", not "passed". Infrastructure codes
 * (EVAL_*) stop before any stage is judged, so every stage is unknown.
 */
import { FAILURE_LABELS, isInfraCode, type StageId } from "./labels";

export type StageState =
  | "passed"
  | "failed"
  | "warning"
  | "not_assessed"
  | "unknown";

export type StageResult = {
  id: StageId;
  label: string;
  question: string;
  state: StageState;
  note: string;
};

export const STAGES: Array<{ id: StageId; label: string; question: string }> = [
  {
    id: "retrieval",
    label: "Retrieval",
    question: "Were the right passages found?",
  },
  {
    id: "context",
    label: "Context",
    question: "Was the context enough to answer?",
  },
  {
    id: "answer",
    label: "Answer",
    question: "Is the answer supported by the context?",
  },
  {
    id: "abstention",
    label: "Abstention",
    question: "Did it answer, or decline, appropriately?",
  },
];

export const STAGE_STATE_LABELS: Record<StageState, string> = {
  passed: "Passed",
  failed: "Broke here",
  warning: "Insufficient",
  not_assessed: "Not assessed",
  unknown: "Unknown",
};

type Plan = Record<StageId, [StageState, string]>;

const NOT_ASSESSED_NOTE =
  "Not assessed: rules are first-match, so checks after the failing stage did not run.";

function build(plan: Plan): StageResult[] {
  return STAGES.map((s) => ({
    ...s,
    state: plan[s.id][0],
    note: plan[s.id][1],
  }));
}

function all(state: StageState, note: string): StageResult[] {
  return build({
    retrieval: [state, note],
    context: [state, note],
    answer: [state, note],
    abstention: [state, note],
  });
}

/** Per-stage verdicts for a diagnosis failure code (null = not diagnosed). */
export function stageStates(code: string | null | undefined): StageResult[] {
  if (!code) return all("unknown", "Not diagnosed yet.");
  if (isInfraCode(code)) {
    return all(
      "unknown",
      "Unknown: an infrastructure failure stopped the diagnosis before any stage was judged.",
    );
  }
  switch (code) {
    case "OK_GROUNDED":
      return build({
        retrieval: ["passed", "Relevant passages were retrieved."],
        context: ["passed", "The context was judged sufficient."],
        answer: ["passed", "The answer was faithful to the context."],
        abstention: ["passed", "It answered, as it should with enough context."],
      });
    case "OK_CORRECT_ABSTENTION":
      return build({
        retrieval: ["passed", "No retrieval rule fired."],
        context: ["warning", "The context was judged insufficient to answer."],
        answer: ["not_assessed", "No answer to check: the system declined."],
        abstention: ["passed", "It correctly declined to answer."],
      });
    case "ABSTENTION_FALSE_NEGATIVE":
      return build({
        retrieval: ["passed", "No retrieval rule fired."],
        context: ["warning", "The context was judged insufficient to answer."],
        answer: [
          "not_assessed",
          "Not assessed: the abstention rule matched before the answer checks.",
        ],
        abstention: ["failed", "It answered when it should have declined."],
      });
    case "ABSTENTION_FALSE_POSITIVE":
      return build({
        retrieval: ["passed", "No retrieval rule fired."],
        context: ["passed", "The context was judged sufficient."],
        answer: ["not_assessed", "No answer to check: the system declined."],
        abstention: ["failed", "It declined although it could have answered."],
      });
    case "DIAGNOSIS_UNCERTAIN":
      return build({
        retrieval: ["passed", "No retrieval rule fired."],
        context: ["unknown", "The judges disagreed, so this was not localized."],
        answer: ["unknown", "The judges disagreed, so this was not localized."],
        abstention: ["unknown", "The judges disagreed, so this was not localized."],
      });
    default:
      break;
  }

  const broken = FAILURE_LABELS[code]?.stage ?? null;
  if (!broken) {
    return all("unknown", "This failure code is not mapped to a stage.");
  }
  const brokenIndex = STAGES.findIndex((s) => s.id === broken);
  return STAGES.map((s, i) => {
    if (i < brokenIndex) {
      return { ...s, state: "passed", note: "No rule for this stage fired." };
    }
    if (i === brokenIndex) {
      return {
        ...s,
        state: "failed",
        note: FAILURE_LABELS[code]?.what || "The diagnosis localized the failure here.",
      };
    }
    return { ...s, state: "not_assessed", note: NOT_ASSESSED_NOTE };
  });
}
