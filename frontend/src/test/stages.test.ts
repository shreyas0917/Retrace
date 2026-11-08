import { describe, expect, it } from "vitest";
import { KNOWN_FAILURE_CODES } from "../labels";
import { stageStates, type StageState } from "../stages";

function states(code: string | null): StageState[] {
  return stageStates(code).map((s) => s.state);
}

describe("stage strip logic", () => {
  it("orders the four stages", () => {
    expect(stageStates("OK_GROUNDED").map((s) => s.label)).toEqual([
      "Retrieval",
      "Context",
      "Answer",
      "Abstention",
    ]);
  });

  it("passes every stage for a grounded answer", () => {
    expect(states("OK_GROUNDED")).toEqual(["passed", "passed", "passed", "passed"]);
  });

  it("marks the broken stage and leaves later stages not assessed", () => {
    expect(states("RETRIEVAL_MISS")).toEqual(["failed", "not_assessed", "not_assessed", "not_assessed"]);
    expect(states("RETRIEVAL_EMPTY")).toEqual(["failed", "not_assessed", "not_assessed", "not_assessed"]);
    expect(states("GENERATION_CONTRADICTION")).toEqual(["passed", "passed", "failed", "not_assessed"]);
    expect(states("GROUNDING_PARTIAL")).toEqual(["passed", "passed", "failed", "not_assessed"]);
    expect(states("RETRIEVAL_INSUFFICIENT_CONTEXT")).toEqual([
      "passed",
      "failed",
      "not_assessed",
      "not_assessed",
    ]);
  });

  it("follows first-match order for abstention rules (answer checks never ran)", () => {
    expect(states("ABSTENTION_FALSE_NEGATIVE")).toEqual(["passed", "warning", "not_assessed", "failed"]);
    expect(states("ABSTENTION_FALSE_POSITIVE")).toEqual(["passed", "passed", "not_assessed", "failed"]);
    expect(states("OK_CORRECT_ABSTENTION")).toEqual(["passed", "warning", "not_assessed", "passed"]);
  });

  it("makes every stage unknown for infrastructure failures", () => {
    for (const code of [
      "EVAL_MODEL_TIMEOUT",
      "EVAL_INTERNAL_ERROR",
      "EVAL_JUDGE_MALFORMED",
      "EVAL_MISSING_CONTEXT",
    ]) {
      expect(states(code)).toEqual(["unknown", "unknown", "unknown", "unknown"]);
    }
  });

  it("treats uncertain, missing and unmapped codes as unknown", () => {
    expect(states("DIAGNOSIS_UNCERTAIN")).toEqual(["passed", "unknown", "unknown", "unknown"]);
    expect(states(null)).toEqual(["unknown", "unknown", "unknown", "unknown"]);
    expect(states("SOMETHING_NEW")).toEqual(["unknown", "unknown", "unknown", "unknown"]);
  });

  it("never marks more than one stage failed, and nothing passes after a failure", () => {
    for (const code of KNOWN_FAILURE_CODES) {
      const s = states(code);
      expect(s.filter((x) => x === "failed").length).toBeLessThanOrEqual(1);
      const i = s.indexOf("failed");
      if (i >= 0) expect(s.slice(i + 1).includes("passed")).toBe(false);
    }
  });
});
