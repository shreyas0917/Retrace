import { describe, expect, it } from "vitest";
import {
  filterCases,
  formatDelta,
  formatMetricValue,
  gateVerdict,
  isF1Metric,
  sortFailuresFirst,
} from "../format";
import { makeCase } from "./fixtures";

describe("comparison formatting", () => {
  it("shows accuracy deltas as signed percentage points", () => {
    expect(formatDelta("failure_code_accuracy", -0.0834)).toBe("−8.3 pp");
    expect(formatDelta("evidence_accuracy", 0.0834)).toBe("+8.3 pp");
    expect(formatDelta("rule_accuracy", 0)).toBe("±0.0 pp");
    expect(formatDelta("rule_accuracy", 0.00001)).toBe("±0.0 pp");
    expect(formatDelta("rule_accuracy", null)).toBe("—");
  });

  it("shows F1 deltas as signed decimals", () => {
    expect(isF1Metric("macro_f1")).toBe(true);
    expect(isF1Metric("failure_code_accuracy")).toBe(false);
    expect(formatDelta("macro_f1", 0.012)).toBe("+0.012");
    expect(formatDelta("weighted_f1", -0.02)).toBe("−0.020");
    expect(formatDelta("macro_f1", 0)).toBe("±0.000");
  });

  it("formats values as percent or decimal", () => {
    expect(formatMetricValue("failure_code_accuracy", 0.8333)).toBe("83.3%");
    expect(formatMetricValue("macro_f1", 0.8333)).toBe("0.833");
    expect(formatMetricValue("macro_f1", undefined)).toBe("—");
  });
});

describe("gate verdict", () => {
  it("uses the run's exit code", () => {
    expect(gateVerdict({ exitCode: 0 }).kind).toBe("pass");
    expect(gateVerdict({ exitCode: 1 }).kind).toBe("regression");
    expect(gateVerdict({ exitCode: 2 }).kind).toBe("error");
    expect(gateVerdict({ exitCode: 1 }).derived).toBe(false);
  });

  it("derives the exit code from a stored comparison", () => {
    const failed = gateVerdict({ comparison: { passed: false, has_baseline: true } });
    expect(failed).toMatchObject({ kind: "regression", exitCode: 1, derived: true });
    const passed = gateVerdict({ comparison: { passed: true, has_baseline: false } });
    expect(passed).toMatchObject({ kind: "no_baseline", exitCode: 0 });
    expect(gateVerdict({ status: "FAILED" })).toMatchObject({ kind: "error", exitCode: 2 });
    expect(gateVerdict({}).kind).toBe("unknown");
  });
});

describe("case filter", () => {
  const cases = [
    makeCase("b_pass", true),
    makeCase("a_pass", true),
    makeCase("z_fail", false),
    makeCase("err", true, { error: "judge timeout" }),
  ];

  it("puts failures (and errored cases) first", () => {
    expect(sortFailuresFirst(cases).map((c) => c.case_id)).toEqual(["err", "z_fail", "a_pass", "b_pass"]);
  });

  it("searches ids, codes, plain-English titles and errors", () => {
    expect(filterCases(cases, "z_fail").map((c) => c.case_id)).toEqual(["z_fail"]);
    expect(filterCases(cases, "ok_grounded").map((c) => c.case_id)).toEqual(["z_fail"]);
    expect(filterCases(cases, "correct and supported").map((c) => c.case_id)).toEqual(["z_fail"]);
    expect(filterCases(cases, "timeout").map((c) => c.case_id)).toEqual(["err"]);
    expect(filterCases(cases, "  ").length).toBe(4);
    expect(filterCases(cases, "nothing-matches")).toEqual([]);
  });

  it("can keep failures only", () => {
    expect(filterCases(cases, "", true).map((c) => c.case_id)).toEqual(["err", "z_fail"]);
    expect(filterCases(cases, "pass", true)).toEqual([]);
  });
});
