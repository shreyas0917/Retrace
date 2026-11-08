import { describe, expect, it } from "vitest";
import {
  friendlyDiagnosis,
  isHealthy,
  severityLabel,
  severityOf,
} from "../labels";

describe("friendly taxonomy", () => {
  it("maps known failure codes to plain English with severity", () => {
    const miss = friendlyDiagnosis("RETRIEVAL_MISS");
    expect(miss.title).toMatch(/wrong information/i);
    expect(miss.severity).toBe("high");
    expect(miss.category).toBe("Retrieval");
  });

  it("treats OK codes as healthy", () => {
    expect(severityOf("OK_GROUNDED")).toBe("ok");
    expect(isHealthy("OK_CORRECT_ABSTENTION")).toBe(true);
    expect(isHealthy("GENERATION_HALLUCINATION")).toBe(false);
  });

  it("degrades unknown codes to a readable fallback, not a throw", () => {
    const unknown = friendlyDiagnosis("SOME_NEW_BACKEND_CODE");
    expect(unknown.title).toBe("Some New Backend Code");
    expect(unknown.severity).toBe("unknown");
    const unknownOk = friendlyDiagnosis("OK_SOMETHING_NEW");
    expect(unknownOk.severity).toBe("ok");
  });

  it("handles null/empty as no diagnosis", () => {
    expect(friendlyDiagnosis(null).severity).toBe("unknown");
    expect(friendlyDiagnosis("").title).toMatch(/no diagnosis/i);
  });

  it("labels severities for humans", () => {
    expect(severityLabel("ok")).toBe("Healthy");
    expect(severityLabel("high")).toBe("Needs attention");
    expect(severityLabel("medium")).toBe("Worth a look");
  });
});
