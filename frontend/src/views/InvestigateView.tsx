import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { apiGet, apiPost } from "../api";
import { EmptyState, ErrorBanner, LoadingState, PageHeader } from "../components/ui";
import { InvestigationReport } from "../components/InvestigationReport";
import { ImportTrace } from "../components/ImportTrace";
import {
  buildInvestigateVersions,
  buildReadyVersions,
  isFixtureCorpus,
  pickDefaultVersionId,
} from "../corpusClassify";
import type { CorpusDetail, Investigation } from "../types";

type Tab = "run" | "import";

type Props = {
  apiKey: string;
  executionId: string;
  onExecutionIdChange: (id: string) => void;
  /** Open on the "Import a trace" tab. */
  initialTab?: Tab;
};

const TABS: Array<{ id: Tab; label: string }> = [
  { id: "run", label: "Run or load" },
  { id: "import", label: "Import a trace" },
];

export const EXAMPLE_QUERIES = [
  "How much PTO do full-time employees accrue per month?",
  "How do I submit an expense for reimbursement?",
  "Who approves a remote work request?",
  "What should I do in the first hour of a security incident?",
];

const HOW_IT_WORKS: Array<{ title: string; body: string }> = [
  {
    title: "Retrieve",
    body: "Find the passages in the corpus most similar to the question.",
  },
  {
    title: "Generate",
    body: "The model answers using only those passages, or declines.",
  },
  {
    title: "Judge",
    body: "Relevance, faithfulness and contradiction judges score the context and the answer.",
  },
  {
    title: "Diagnose",
    body: "Ordered rules turn the signals into a failure code, the rule that fired and a next step.",
  },
];

export function InvestigateView({
  apiKey,
  executionId,
  onExecutionIdChange,
  initialTab = "run",
}: Props) {
  const [tab, setTab] = useState<Tab>(initialTab);
  const [corpora, setCorpora] = useState<CorpusDetail[]>([]);
  const [versionId, setVersionId] = useState("");
  const [query, setQuery] = useState(EXAMPLE_QUERIES[0]);
  const [topK, setTopK] = useState(5);
  const [currentId, setCurrentId] = useState(executionId);
  const [loadId, setLoadId] = useState(executionId);
  const [busy, setBusy] = useState(false);
  const [loadingInv, setLoadingInv] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState<string[]>([]);
  const [inv, setInv] = useState<Investigation | null>(null);
  const queryRef = useRef<HTMLTextAreaElement | null>(null);
  const tabRefs = useRef<Record<Tab, HTMLButtonElement | null>>({ run: null, import: null });

  const investigateVersions = useMemo(() => buildInvestigateVersions(corpora), [corpora]);
  const allReadyVersions = useMemo(() => buildReadyVersions(corpora), [corpora]);
  const selectedVersion = useMemo(
    () => investigateVersions.find((v) => v.id === versionId) || null,
    [investigateVersions, versionId],
  );
  const executionCorpus = useMemo(() => {
    if (!inv?.execution.corpus_version_id) return null;
    return allReadyVersions.find((v) => v.id === inv.execution.corpus_version_id) || null;
  }, [inv, allReadyVersions]);

  async function refreshCorpora() {
    try {
      const list = await apiGet<Array<{ id: string }> | { corpora: Array<{ id: string }> }>(
        "/api/v1/corpora",
        apiKey,
      );
      const items = Array.isArray(list) ? list : list?.corpora || [];
      // Only product corpora are selectable here; backend test fixtures are
      // skipped so a long-lived database does not cause a request burst.
      const relevant = items.filter((c) => !isFixtureCorpus({ id: c.id })).slice(0, 60);
      const details: CorpusDetail[] = [];
      for (const c of relevant) {
        try {
          details.push(await apiGet<CorpusDetail>(`/api/v1/corpora/${c.id}`, apiKey));
        } catch {
          /* skip a corpus that failed to load; others still populate */
        }
      }
      setCorpora(details);
      const rows = buildInvestigateVersions(details);
      setVersionId((prev) =>
        prev && rows.some((r) => r.id === prev) ? prev : pickDefaultVersionId(rows),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load corpora");
    }
  }

  async function loadInvestigation(id: string) {
    const clean = id.trim();
    if (!clean) {
      setInv(null);
      return;
    }
    setLoadingInv(true);
    setError("");
    try {
      const body = await apiGet<Investigation>(
        `/api/v1/investigations/${encodeURIComponent(clean)}`,
        apiKey,
      );
      setInv(body);
    } catch (err) {
      setInv(null);
      setError(err instanceof Error ? err.message : "Unable to load investigation");
    } finally {
      setLoadingInv(false);
    }
  }

  /** Open an execution: update local state, tell the app (URL), load it. */
  function openExecution(id: string) {
    const clean = id.trim();
    if (!clean) return;
    setTab("run");
    setLoadId(clean);
    if (clean === currentId) {
      void loadInvestigation(clean);
    } else {
      setCurrentId(clean);
    }
    onExecutionIdChange(clean);
  }

  useEffect(() => {
    void refreshCorpora();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiKey]);

  // The app (deep link, "Investigate →" links, back button) can change it.
  useEffect(() => {
    setCurrentId(executionId);
    setLoadId(executionId);
  }, [executionId]);

  useEffect(() => {
    if (currentId) void loadInvestigation(currentId);
    else setInv(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentId, apiKey]);

  async function runGenerateAndDiagnose() {
    if (!versionId) {
      setError("Select a ready corpus version first.");
      return;
    }
    if (!query.trim()) {
      setError("Type a question first.");
      return;
    }
    setBusy(true);
    setError("");
    setNotice([]);
    try {
      const gen = await apiPost<{ execution_id: string }>("/api/v1/generate", apiKey, {
        corpus_version_id: versionId,
        query,
        top_k: topK,
      });
      await apiPost("/api/v1/diagnose", apiKey, { execution_id: gen.execution_id });
      openExecution(gen.execution_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Generate and diagnose failed");
    } finally {
      setBusy(false);
    }
  }

  function onTabKey(e: KeyboardEvent<HTMLButtonElement>) {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    e.preventDefault();
    const i = TABS.findIndex((t) => t.id === tab);
    const step = e.key === "ArrowRight" ? 1 : TABS.length - 1;
    const next = TABS[(i + step) % TABS.length].id;
    setTab(next);
    tabRefs.current[next]?.focus();
  }

  const corpusSelect = (
    <div className="corpus-select">
      <label>
        Corpus
        <select
          value={versionId}
          onChange={(e) => setVersionId(e.target.value)}
          disabled={investigateVersions.length === 0}
        >
          {investigateVersions.length === 0 ? (
            <option value="">No live or demo corpora available</option>
          ) : (
            <>
              <option value="">Select…</option>
              {investigateVersions.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.label}
                </option>
              ))}
            </>
          )}
        </select>
      </label>
      {investigateVersions.length === 0 ? (
        <p className="corpus-select-hint muted small">
          Seed the demo corpus, or import a trace from your own app instead.
        </p>
      ) : selectedVersion?.hint ? (
        <p className="corpus-select-hint muted small">{selectedVersion.hint}</p>
      ) : null}
    </div>
  );

  const generateForm = (
    <form
      className="form"
      aria-label="Ask a question"
      onSubmit={(e) => {
        e.preventDefault();
        void runGenerateAndDiagnose();
      }}
    >
      {corpusSelect}
      <label>
        Question
        <textarea
          ref={queryRef}
          rows={3}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </label>
      <div className="inline form-actions">
        <label className="narrow">
          Passages
          <input
            type="number"
            min={1}
            max={50}
            value={topK}
            aria-label="Passages to retrieve (top k)"
            onChange={(e) => setTopK(Number(e.target.value) || 5)}
          />
        </label>
        <button type="submit" disabled={busy}>
          {busy ? "Running…" : "Generate + diagnose"}
        </button>
        <button
          type="button"
          className="secondary"
          onClick={() => void refreshCorpora()}
          disabled={busy}
        >
          Refresh corpora
        </button>
      </div>
    </form>
  );

  const loadForm = (
    <form
      className="load-form"
      aria-label="Load an execution"
      onSubmit={(e) => {
        e.preventDefault();
        openExecution(loadId);
      }}
    >
      <label htmlFor="load-execution-id">Execution ID</label>
      <span className="inline load-row">
        <input
          id="load-execution-id"
          value={loadId}
          onChange={(e) => setLoadId(e.target.value)}
          placeholder="Paste an execution ID"
          className="mono"
        />
        <button type="submit" className="secondary" disabled={loadingInv || !loadId.trim()}>
          Load
        </button>
      </span>
    </form>
  );

  return (
    <div className="investigate">
      <PageHeader
        title="Investigate"
        description="Trace one AI answer from question to diagnosis, with the evidence behind it."
      />

      <div className="tabs" role="tablist" aria-label="Investigate mode">
        {TABS.map((t) => (
          <button
            key={t.id}
            ref={(el) => {
              tabRefs.current[t.id] = el;
            }}
            type="button"
            role="tab"
            id={`tab-${t.id}`}
            aria-selected={tab === t.id}
            aria-controls={`panel-${t.id}`}
            tabIndex={tab === t.id ? 0 : -1}
            className={tab === t.id ? "tab active" : "tab"}
            onClick={() => setTab(t.id)}
            onKeyDown={onTabKey}
          >
            {t.label}
          </button>
        ))}
      </div>

      <ErrorBanner message={error} />
      {notice.length ? (
        <div className="note" role="status">
          <strong>Imported with warnings:</strong>
          <ul className="plain-list">
            {notice.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {tab === "import" ? (
        <div role="tabpanel" id="panel-import" aria-labelledby="tab-import" className="panel">
          <ImportTrace
            apiKey={apiKey}
            onImported={(id, warnings) => {
              setNotice(warnings);
              openExecution(id);
            }}
          />
        </div>
      ) : (
        <div role="tabpanel" id="panel-run" aria-labelledby="tab-run">
          {!inv && !loadingInv && (
            <div className="investigate-idle">
              <aside className="panel" aria-label="Investigation controls">
                <h2>Ask a question</h2>
                {generateForm}
                <div className="divider" />
                <h2>Or open an existing execution</h2>
                {loadForm}
              </aside>
              <div className="stack">
                <EmptyState hint="Ask a question, paste an execution ID, or import a trace from your own RAG app.">
                  No execution selected.
                </EmptyState>
                <section className="panel" aria-labelledby="examples-title">
                  <h2 id="examples-title">Example questions</h2>
                  <ul className="example-list">
                    {EXAMPLE_QUERIES.map((q) => (
                      <li key={q}>
                        <button
                          type="button"
                          className="example-chip"
                          onClick={() => {
                            setQuery(q);
                            queryRef.current?.focus();
                          }}
                        >
                          {q}
                        </button>
                      </li>
                    ))}
                  </ul>
                </section>
                <section className="panel" aria-labelledby="how-title">
                  <h2 id="how-title">How it works</h2>
                  <ol className="how-steps">
                    {HOW_IT_WORKS.map((s, i) => (
                      <li key={s.title}>
                        <span className="how-num" aria-hidden="true">
                          {i + 1}
                        </span>
                        <span>
                          <strong>{s.title}.</strong>
                          <span className="muted"> {s.body}</span>
                        </span>
                      </li>
                    ))}
                  </ol>
                </section>
              </div>
            </div>
          )}

          {loadingInv && <LoadingState label="Loading investigation…" />}

          {inv && !loadingInv && (
            <div className="investigate-loaded">
              <div className="control-bar compact" aria-label="Investigation controls">
                <div className="control-load">{loadForm}</div>
                <details className="new-query">
                  <summary>Ask a new question</summary>
                  <div className="new-query-body">{generateForm}</div>
                </details>
              </div>
              <InvestigationReport
                inv={inv}
                corpusLabel={
                  executionCorpus
                    ? `${executionCorpus.title} · ${executionCorpus.chunkCount} chunks`
                    : null
                }
              />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
