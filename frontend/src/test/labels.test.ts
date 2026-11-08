import { describe, expect, it } from "vitest";
import {
  FAILURE_LABELS,
  METRIC_LABELS,
  OPS_SIGNAL_LABELS,
  RECOMMENDATION_LABELS,
  SIGNAL_LABELS,
  SUITE_LABELS,
  humanize,
  recommendationLabel,
  statusLabel,
} from "../labels";
import exampleText from "../examples/contradictionTrace.json?raw";
import originalExample from "../../../examples/traces/contradiction.json?raw";
import taxonomyPy from "../../../backend/app/services/diagnosis/taxonomy.py?raw";
import ruleCatalogPy from "../../../backend/app/services/diagnosis/rule_catalog.py?raw";
import investigationPy from "../../../backend/app/services/investigation.py?raw";
import regressionPy from "../../../backend/app/services/eval/regression.py?raw";

const BACKEND_FILES: Record<string, string> = {
  "services/diagnosis/taxonomy.py": taxonomyPy,
  "services/diagnosis/rule_catalog.py": ruleCatalogPy,
  "services/investigation.py": investigationPy,
  "services/eval/regression.py": regressionPy,
};
const read = (rel: string) => BACKEND_FILES[rel];

function sliceBlock(src: string, start: string): string {
  const i = src.indexOf(start);
  expect(i).toBeGreaterThanOrEqual(0);
  const end = src.indexOf("\n}\n", i);
  return src.slice(i, end);
}

describe("labels mirror the backend", () => {
  const taxonomy = read("services/diagnosis/taxonomy.py");

  it("has a label for every failure code in taxonomy.py", () => {
    const block = sliceBlock(taxonomy, "FAILURE_CODES: dict[str, FailureCode] = {");
    const codes = Array.from(block.matchAll(/^\s+"([A-Z_]+)": FailureCode\(/gm), (m: RegExpMatchArray) => m[1]);
    expect(codes.length).toBeGreaterThanOrEqual(20);
    const missing = codes.filter((c) => !FAILURE_LABELS[c]);
    expect(missing).toEqual([]);
    for (const c of codes) {
      expect(FAILURE_LABELS[c].title).not.toMatch(/_/);
      expect(FAILURE_LABELS[c].what.length).toBeGreaterThan(10);
    }
  });

  it("has a label for every recommendation code", () => {
    const block = sliceBlock(taxonomy, "RECOMMENDATIONS: dict[str, str] = {");
    const recs = new Set(Array.from(block.matchAll(/:\s*"([A-Z_]+)",/g), (m: RegExpMatchArray) => m[1]));
    recs.add("FIX_PIPELINE"); // recommendation_for() default
    const missing = [...recs].filter((r) => !RECOMMENDATION_LABELS[r]);
    expect(missing).toEqual([]);
  });

  it("labels every ops signal that has a runbook", () => {
    const catalog = read("services/diagnosis/rule_catalog.py");
    const block = sliceBlock(catalog, "RUNBOOK_BY_SIGNAL: dict[str, str] = {");
    const signals = Array.from(block.matchAll(/^\s+"([a-z0-9_]+)":/gm), (m: RegExpMatchArray) => m[1]);
    expect(signals.length).toBeGreaterThan(0);
    expect(signals.filter((s) => !OPS_SIGNAL_LABELS[s])).toEqual([]);
  });

  it("labels every signal the investigation exposes in signals_used", () => {
    const inv = read("services/investigation.py");
    const i = inv.indexOf('"signals_used": {');
    const block = inv.slice(i, inv.indexOf(")", inv.indexOf("for k in (", i)));
    const keys = Array.from(block.matchAll(/"([a-z_]+)",/g), (m: RegExpMatchArray) => m[1]);
    expect(keys.length).toBeGreaterThan(5);
    expect(keys.filter((k) => !SIGNAL_LABELS[k])).toEqual([]);
  });

  it("labels the comparison metrics and every console suite", () => {
    const reg = read("services/eval/regression.py");
    for (const key of ["failure_code_accuracy", "rule_accuracy", "evidence_accuracy"]) {
      expect(reg).toContain(`"${key}"`);
      expect(METRIC_LABELS[key]).toBeTruthy();
    }
    // Suites offered by the console picker (contents are never read here).
    for (const id of ["planted_v1", "heldout_v1", "calib_v1", "gold_v1", "live_v1"]) {
      expect(SUITE_LABELS[id]).toBeTruthy();
    }
  });

  it("keeps the bundled example equal to examples/traces/contradiction.json", () => {
    expect(JSON.parse(exampleText)).toEqual(JSON.parse(originalExample));
  });
});

describe("label fallbacks", () => {
  it("humanizes unknown keys instead of showing snake_case", () => {
    expect(humanize("judge_timeout_rate")).toBe("Judge timeout rate");
    expect(statusLabel("INSUFFICIENT_DATA")).toBe("Not enough data");
    expect(statusLabel("SOMETHING_ODD")).toBe("Something odd");
    expect(recommendationLabel("NEW_THING").title).toBe("New Thing");
    expect(recommendationLabel(null).title).toBe("No recommendation");
  });
});
