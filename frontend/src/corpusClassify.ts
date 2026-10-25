/**
 * Classify corpora for Investigate UX.
 *
 * Backend exposes no visibility / kind field — only id, title, and version
 * stats. Classification uses identifiers that Retrace's own seed scripts and
 * pytest suite create.
 *
 * Investigate visibility is an allowlist of intentional product corpora
 * (currently the seeded `demo` corpus), NOT "everything that is not a fixture".
 * Internal correctness / eval / phase corpora stay in the API and DB.
 */

export type CorpusKind = "demo" | "live" | "fixture";

/** ID prefixes emitted by backend tests / validation / correctness scripts. */
const INTERNAL_ID_PREFIXES = [
  "test_",
  "gen_",
  "diag_",
  "iso_",
  "fail_",
  "empty_",
  "nr_",
  "c8_",
  "corr_", // investigation correctness suite
] as const;

/** Exact titles used by Retrace tests / phase / correctness scripts (lowercase). */
const INTERNAL_TITLES = new Set([
  "eval stub (offline fixtures)",
  "test corpus",
  "gen test",
  "diag",
  "phase8",
  "fail",
  "nr",
  "p8",
  "correctness",
]);

/** Stable product corpus id created by seed_demo_corpus / validate_phase9. */
const PRODUCT_DEMO_CORPUS_ID = "demo";

export function isFixtureCorpus(corpus: {
  id: string;
  title?: string | null;
}): boolean {
  return corpusKind(corpus) === "fixture";
}

export function isInternalCorpus(corpus: {
  id: string;
  title?: string | null;
}): boolean {
  const id = (corpus.id || "").toLowerCase();
  const title = (corpus.title || "").trim().toLowerCase();

  if (id === PRODUCT_DEMO_CORPUS_ID) return false;
  if (id === "eval_stub") return true;
  if (INTERNAL_ID_PREFIXES.some((p) => id.startsWith(p))) return true;
  if (title.startsWith("eval stub")) return true;
  if (INTERNAL_TITLES.has(title)) return true;
  return false;
}

export function corpusKind(corpus: {
  id: string;
  title?: string | null;
}): CorpusKind {
  const id = (corpus.id || "").toLowerCase();
  if (id === PRODUCT_DEMO_CORPUS_ID) return "demo";
  if (isInternalCorpus(corpus)) return "fixture";
  // Other API-created corpora: not fixtures, but not Investigate product surface.
  return "live";
}

/**
 * Product-facing Investigate selector.
 * Only intentional demo/product corpora — not arbitrary non-fixture rows.
 */
export function visibleInInvestigate(
  kindOrCorpus: CorpusKind | { id: string; title?: string | null },
): boolean {
  const kind =
    typeof kindOrCorpus === "string"
      ? kindOrCorpus
      : corpusKind(kindOrCorpus);
  return kind === "demo";
}

export type ReadyCorpusVersion = {
  id: string;
  corpusId: string;
  title: string;
  chunkCount: number;
  kind: CorpusKind;
  /** Compact option label for <select>. */
  label: string;
  /** Short hint under the control when this version is selected. */
  hint: string;
};

type CorpusInput = {
  id: string;
  title: string;
  versions?: Array<{ id: string; status: string; chunk_count: number }>;
};

function readyVersionsForCorpus(c: CorpusInput): Array<{
  id: string;
  chunk_count: number;
}> {
  return (c.versions || []).filter((v) => v.status === "READY");
}

/** Product label: "Demo Policies · 5 chunks" or "Demo Policies · v2 · 5 chunks". */
export function formatInvestigateOption(v: {
  title: string;
  chunkCount: number;
  versionIndex: number;
  versionCount: number;
}): string {
  if (v.versionCount <= 1) {
    return `${v.title} · ${v.chunkCount} chunks`;
  }
  return `${v.title} · v${v.versionIndex} · ${v.chunkCount} chunks`;
}

export function formatVersionHint(v: { chunkCount: number }): string {
  if (v.chunkCount === 0) {
    return "0 chunks — retrieval will have no context";
  }
  return "";
}

/**
 * All READY versions with classification (includes fixtures).
 * Used to resolve metadata for loaded executions; not for the Investigate dropdown.
 */
export function buildReadyVersions(corpora: CorpusInput[]): ReadyCorpusVersion[] {
  const rows: ReadyCorpusVersion[] = [];
  for (const c of corpora) {
    const kind = corpusKind(c);
    const title = c.title || c.id;
    const ready = readyVersionsForCorpus(c);
    // API returns newest first; assign vN…v1 so oldest is v1, newest is vN.
    const count = ready.length;
    ready.forEach((v, newestFirstIdx) => {
      const versionIndex = count - newestFirstIdx;
      const row: ReadyCorpusVersion = {
        id: v.id,
        corpusId: c.id,
        title,
        chunkCount: v.chunk_count,
        kind,
        label: formatInvestigateOption({
          title,
          chunkCount: v.chunk_count,
          versionIndex,
          versionCount: count,
        }),
        hint: formatVersionHint({ chunkCount: v.chunk_count }),
      };
      rows.push(row);
    });
  }
  rows.sort((a, b) => {
    const rank = (k: CorpusKind) =>
      k === "demo" ? 0 : k === "live" ? 1 : 2;
    if (a.kind !== b.kind) return rank(a.kind) - rank(b.kind);
    if (a.corpusId === b.corpusId) return 0;
    return a.title.localeCompare(b.title) || a.corpusId.localeCompare(b.corpusId);
  });
  return rows;
}

/** Investigate dropdown rows: intentional product demo only. */
export function buildInvestigateVersions(
  corpora: CorpusInput[],
): ReadyCorpusVersion[] {
  return buildReadyVersions(corpora).filter((r) => visibleInInvestigate(r.kind));
}

/** Prefer demo with chunks. Never select internal/fixture corpora. */
export function pickDefaultVersionId(rows: ReadyCorpusVersion[]): string {
  const visible = rows.filter((r) => visibleInInvestigate(r.kind));
  const demo = visible.find((r) => r.corpusId === "demo" && r.chunkCount > 0);
  if (demo) return demo.id;

  const withChunks = visible.find((r) => r.chunkCount > 0);
  if (withChunks) return withChunks.id;

  return visible[0]?.id || "";
}
