import { describe, expect, it } from "vitest";

// Keep helpers in sync with InvestigateView display semantics.
function formatGoldHit(retrieval: {
  gold_ids: string[];
  gold_hit: boolean | null;
}): string {
  if (!retrieval.gold_ids?.length) return "Not evaluated";
  if (retrieval.gold_hit == null) return "Not evaluated";
  return String(retrieval.gold_hit);
}

function formatLayer(layer: string | null | undefined): string {
  if (layer == null || layer === "") return "—";
  if (layer.toLowerCase() === "none") return "None";
  return layer;
}

function formatConfidence(confidence: string | null | undefined): string {
  if (!confidence) return "—";
  return confidence.charAt(0).toUpperCase() + confidence.slice(1).toLowerCase();
}

describe("Investigate display semantics", () => {
  it("distinguishes gold true/false from not evaluated", () => {
    expect(formatGoldHit({ gold_ids: [], gold_hit: false })).toBe(
      "Not evaluated",
    );
    expect(formatGoldHit({ gold_ids: [], gold_hit: null })).toBe(
      "Not evaluated",
    );
    expect(formatGoldHit({ gold_ids: ["c1"], gold_hit: true })).toBe("true");
    expect(formatGoldHit({ gold_ids: ["c1"], gold_hit: false })).toBe("false");
  });

  it("renders diagnosis layer/confidence explicitly", () => {
    expect(formatLayer("none")).toBe("None");
    expect(formatLayer("retrieval")).toBe("retrieval");
    expect(formatConfidence("high")).toBe("High");
    expect(formatConfidence(null)).toBe("—");
  });
});
