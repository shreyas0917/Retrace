import { describe, expect, it } from "vitest";
import {
  buildInvestigateVersions,
  buildReadyVersions,
  corpusKind,
  isFixtureCorpus,
  pickDefaultVersionId,
  visibleInInvestigate,
} from "../corpusClassify";

const MIXED = [
  {
    id: "eval_stub",
    title: "Eval Stub (offline fixtures)",
    versions: [{ id: "stubver", status: "READY", chunk_count: 0 }],
  },
  {
    id: "demo",
    title: "Demo Policies",
    versions: [
      { id: "newdemo", status: "READY", chunk_count: 5 },
      { id: "olddemo", status: "READY", chunk_count: 5 },
    ],
  },
  {
    id: "corr_ed632f02",
    title: "Correctness",
    versions: [{ id: "corrver", status: "READY", chunk_count: 0 }],
  },
  {
    id: "gen_1",
    title: "Gen Test",
    versions: [{ id: "genver", status: "READY", chunk_count: 2 }],
  },
  {
    id: "diag_xyz",
    title: "Diag",
    versions: [{ id: "diagver", status: "READY", chunk_count: 0 }],
  },
  {
    id: "test_abc",
    title: "Test Corpus",
    versions: [{ id: "testver", status: "READY", chunk_count: 2 }],
  },
  {
    id: "c8_phase",
    title: "phase8",
    versions: [{ id: "p8ver", status: "READY", chunk_count: 0 }],
  },
  {
    id: "iso_a_1",
    title: "A",
    versions: [{ id: "aver", status: "READY", chunk_count: 1 }],
  },
  {
    id: "customer_policies",
    title: "Acme Policies",
    versions: [{ id: "acmever", status: "READY", chunk_count: 3 }],
  },
];

describe("corpusClassify", () => {
  it("classifies demo vs internal correctness/fixtures", () => {
    expect(corpusKind({ id: "demo", title: "Demo Policies" })).toBe("demo");
    expect(isFixtureCorpus({ id: "demo", title: "Demo Policies" })).toBe(false);
    expect(
      isFixtureCorpus({
        id: "eval_stub",
        title: "Eval Stub (offline fixtures)",
      }),
    ).toBe(true);
    expect(
      isFixtureCorpus({ id: "corr_ed632f02", title: "Correctness" }),
    ).toBe(true);
    expect(corpusKind({ id: "corr_x", title: "Correctness" })).toBe("fixture");
    expect(isFixtureCorpus({ id: "gen_abc123", title: "Gen Test" })).toBe(true);
    expect(isFixtureCorpus({ id: "diag_xyz", title: "Diag" })).toBe(true);
    // Non-demo, non-internal API corpus is "live" but not Investigate-visible.
    expect(
      corpusKind({ id: "customer_policies", title: "Acme Policies" }),
    ).toBe("live");
    expect(visibleInInvestigate("demo")).toBe(true);
    expect(visibleInInvestigate("live")).toBe(false);
    expect(visibleInInvestigate("fixture")).toBe(false);
  });

  it("Investigate selector shows only Demo Policies, never Correctness/fixtures", () => {
    const rows = buildInvestigateVersions(MIXED);
    const ids = rows.map((r) => r.corpusId);
    const titles = rows.map((r) => r.title);

    expect(ids).toEqual(["demo", "demo"]);
    expect(titles).toEqual(["Demo Policies", "Demo Policies"]);

    expect(rows.some((r) => r.title === "Correctness")).toBe(false);
    expect(rows.some((r) => r.title.includes("Diag"))).toBe(false);
    expect(rows.some((r) => r.title.includes("Gen Test"))).toBe(false);
    expect(rows.some((r) => r.title.includes("Test Corpus"))).toBe(false);
    expect(rows.some((r) => r.title.includes("phase8"))).toBe(false);
    expect(rows.some((r) => r.title.includes("Eval Stub"))).toBe(false);
    expect(rows.some((r) => r.title === "A")).toBe(false);
    expect(rows.some((r) => r.title === "Acme Policies")).toBe(false);
    expect(rows.every((r) => r.kind === "demo")).toBe(true);

    expect(rows[0].label).toMatch(/^Demo Policies · v2 · 5 chunks$/);
    expect(rows[1].label).toMatch(/^Demo Policies · v1 · 5 chunks$/);
  });

  it("defaults to demo and never falls back to Correctness/fixtures", () => {
    const rows = buildInvestigateVersions(MIXED);
    expect(pickDefaultVersionId(rows)).toBe("newdemo");

    const internalOnly = buildInvestigateVersions([
      {
        id: "corr_1",
        title: "Correctness",
        versions: [{ id: "c1", status: "READY", chunk_count: 0 }],
      },
      {
        id: "eval_stub",
        title: "Eval Stub (offline fixtures)",
        versions: [{ id: "stubver", status: "READY", chunk_count: 0 }],
      },
    ]);
    expect(internalOnly).toHaveLength(0);
    expect(pickDefaultVersionId(internalOnly)).toBe("");
  });

  it("full ready catalog still includes Correctness/fixtures for non-Investigate use", () => {
    const all = buildReadyVersions(MIXED);
    expect(all.some((r) => r.kind === "fixture")).toBe(true);
    expect(all.some((r) => r.corpusId === "eval_stub")).toBe(true);
    expect(all.some((r) => r.title === "Correctness")).toBe(true);
    expect(all.some((r) => r.corpusId === "customer_policies")).toBe(true);
    // Filtering Investigate must not mutate the full catalog.
    expect(all.length).toBeGreaterThan(buildInvestigateVersions(MIXED).length);
  });
});
