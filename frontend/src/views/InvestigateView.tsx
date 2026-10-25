import { useEffect, useMemo, useState, type ReactNode } from "react";
import { apiGet, apiGetText, apiPost } from "../api";
import {
  EmptyState,
  ErrorBanner,
  LoadingState,
  MetaTable,
  PageHeader,
  RawToggle,
  Section,
  StatusBadge,
} from "../components/ui";
import { MarkdownAnswer } from "../components/MarkdownAnswer";
import {
  buildInvestigateVersions,
  buildReadyVersions,
  pickDefaultVersionId,
} from "../corpusClassify";
import type { CorpusDetail, Investigation } from "../types";

type Props = {
  apiKey: string;
  executionId: string;
  onExecutionIdChange: (id: string) => void;
  highlightRef?: string | null;
};

function evidenceTone(
  status: string,
): "ok" | "fail" | "warn" | "neutral" {
  const s = status.toLowerCase();
  if (s === "missing") return "fail";
  if (s === "expected" || s === "relevant") return "ok";
  if (s === "distractor") return "warn";
  return "neutral";
}

function formatOptionalBool(
  value: boolean | null | undefined,
  whenNull = "Not evaluated",
): string {
  if (value == null) return whenNull;
  return String(value);
}

function formatGoldHit(retrieval: {
  gold_ids: string[];
  gold_hit: boolean | null;
}): string {
  if (!retrieval.gold_ids?.length) return "Not evaluated";
  return formatOptionalBool(retrieval.gold_hit);
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

function formatSignalValue(key: string, value: unknown): string {
  if (value === null || value === undefined) {
    if (key === "gold_hit" || key === "context_sufficient") {
      return "Not evaluated";
    }
    return "—";
  }
  return JSON.stringify(value);
}

function formatMs(ms: number | null | undefined): string {
  if (ms == null) return "—";
  return `${ms} ms`;
}

export function InvestigateView({
  apiKey,
  executionId,
  onExecutionIdChange,
  highlightRef,
}: Props) {
  const [corpora, setCorpora] = useState<CorpusDetail[]>([]);
  const [versionId, setVersionId] = useState("");
  const [query, setQuery] = useState(
    "How much PTO do full-time employees accrue per month?",
  );
  const [topK, setTopK] = useState(5);
  const [loadId, setLoadId] = useState(executionId);
  const [busy, setBusy] = useState(false);
  const [loadingInv, setLoadingInv] = useState(false);
  const [error, setError] = useState("");
  const [inv, setInv] = useState<Investigation | null>(null);
  const [runbookText, setRunbookText] = useState("");
  const [activeEvidence, setActiveEvidence] = useState<string | null>(null);

  // Product selector: Live/Demo only (fixtures stay in API/DB for eval workflows).
  const investigateVersions = useMemo(
    () => buildInvestigateVersions(corpora),
    [corpora],
  );

  // Full catalog for resolving titles on loaded executions (incl. historical fixtures).
  const allReadyVersions = useMemo(
    () => buildReadyVersions(corpora),
    [corpora],
  );

  const selectedVersion = useMemo(
    () => investigateVersions.find((v) => v.id === versionId) || null,
    [investigateVersions, versionId],
  );

  const executionCorpus = useMemo(() => {
    if (!inv) return null;
    const cv = inv.execution.corpus_version_id;
    return allReadyVersions.find((v) => v.id === cv) || null;
  }, [inv, allReadyVersions]);

  async function refreshCorpora() {
    setError("");
    try {
      const list = await apiGet<Array<{ id: string }> | { corpora: Array<{ id: string }> }>(
        "/api/v1/corpora",
        apiKey,
      );
      const items = Array.isArray(list) ? list : list.corpora || [];
      const details: CorpusDetail[] = [];
      for (const c of items) {
        const d = await apiGet<CorpusDetail>(`/api/v1/corpora/${c.id}`, apiKey);
        details.push(d);
      }
      setCorpora(details);
      const rows = buildInvestigateVersions(details);
      setVersionId((prev) => {
        if (prev && rows.some((r) => r.id === prev)) return prev;
        return pickDefaultVersionId(rows);
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load corpora");
    }
  }

  async function loadInvestigation(id: string) {
    if (!id.trim()) {
      setInv(null);
      return;
    }
    setLoadingInv(true);
    setError("");
    setRunbookText("");
    try {
      const body = await apiGet<Investigation>(
        `/api/v1/investigations/${id.trim()}`,
        apiKey,
      );
      setInv(body);
      onExecutionIdChange(id.trim());
    } catch (err) {
      setInv(null);
      setError(
        err instanceof Error ? err.message : "Unable to load investigation",
      );
    } finally {
      setLoadingInv(false);
    }
  }

  useEffect(() => {
    void refreshCorpora();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiKey]);

  useEffect(() => {
    setLoadId(executionId);
    if (executionId) void loadInvestigation(executionId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [executionId, apiKey]);

  useEffect(() => {
    if (highlightRef) setActiveEvidence(highlightRef);
  }, [highlightRef]);

  async function runGenerateAndDiagnose() {
    if (!versionId) {
      setError("Select a READY corpus version.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const gen = await apiPost<{ execution_id: string }>(
        "/api/v1/generate",
        apiKey,
        { corpus_version_id: versionId, query, top_k: topK },
      );
      await apiPost("/api/v1/diagnose", apiKey, {
        execution_id: gen.execution_id,
      });
      onExecutionIdChange(gen.execution_id);
      await loadInvestigation(gen.execution_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Generate/diagnose failed");
    } finally {
      setBusy(false);
    }
  }

  async function openRunbook(slug: string) {
    setError("");
    try {
      const text = await apiGetText(`/api/v1/runbooks/${slug}`);
      setRunbookText(text);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load runbook");
    }
  }

  function jumpToEvidence(ref: string) {
    setActiveEvidence(ref);
    if (ref.startsWith("chunk:")) {
      document.getElementById(`chunk-${ref.slice(6)}`)?.scrollIntoView({
        behavior: "smooth",
        block: "center",
      });
    } else if (ref.startsWith("judge:")) {
      document.getElementById("judges-section")?.scrollIntoView({
        behavior: "smooth",
        block: "start",
      });
    } else if (ref.startsWith("execution:")) {
      document.getElementById("execution-section")?.scrollIntoView({
        behavior: "smooth",
        block: "start",
      });
    } else if (ref.startsWith("retrieval")) {
      document.getElementById("retrieval-section")?.scrollIntoView({
        behavior: "smooth",
        block: "start",
      });
    }
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
          No live or demo corpora available.
        </p>
      ) : selectedVersion?.hint ? (
        <p className="corpus-select-hint muted small">{selectedVersion.hint}</p>
      ) : null}
    </div>
  );

  const controls = (
    <div className="form">
      {corpusSelect}
      <button
        type="button"
        className="secondary"
        onClick={() => void refreshCorpora()}
        disabled={busy}
      >
        Refresh corpora
      </button>
      <label>
        Query
        <textarea
          rows={3}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </label>
      <label className="narrow">
        top_k
        <input
          type="number"
          min={1}
          max={50}
          value={topK}
          onChange={(e) => setTopK(Number(e.target.value) || 5)}
        />
      </label>
      <button
        type="button"
        disabled={busy}
        onClick={() => void runGenerateAndDiagnose()}
      >
        {busy ? "Running…" : "Generate + diagnose"}
      </button>
      <label>
        Load execution ID
        <div className="inline">
          <input
            value={loadId}
            onChange={(e) => setLoadId(e.target.value)}
            placeholder="execution_id"
            className="mono"
          />
          <button
            type="button"
            className="secondary"
            disabled={loadingInv || !loadId.trim()}
            onClick={() => {
              onExecutionIdChange(loadId.trim());
              void loadInvestigation(loadId);
            }}
          >
            Load
          </button>
        </div>
      </label>
    </div>
  );

  return (
    <div>
      <PageHeader
        eyebrow="Investigate"
        title="Investigate"
        description="Trace and diagnose a RAG execution."
      />
      <ErrorBanner message={error} />

      {!inv && !loadingInv && (
        <div className="investigate-idle">
          <aside className="panel tight" aria-label="Investigation controls">
            <h2>Execution controls</h2>
            <p className="muted small">
              Query → retrieval → generation → judges → diagnosis
            </p>
            {controls}
          </aside>
          <EmptyState
            compact
            hint="Generate + diagnose, or load an execution ID."
          >
            No execution selected.
          </EmptyState>
        </div>
      )}

      {loadingInv && <LoadingState label="Loading investigation…" />}

      {inv && (
        <div className="investigate-loaded">
          <div className="control-bar compact" aria-label="Investigation controls">
            <div className="control-corpus">{corpusSelect}</div>
            <label style={{ flex: "1 1 220px", minWidth: 180 }}>
              Query
              <textarea
                rows={2}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </label>
            <label className="narrow">
              top_k
              <input
                type="number"
                min={1}
                max={50}
                value={topK}
                onChange={(e) => setTopK(Number(e.target.value) || 5)}
              />
            </label>
            <button
              type="button"
              disabled={busy}
              onClick={() => void runGenerateAndDiagnose()}
            >
              {busy ? "Running…" : "Generate + diagnose"}
            </button>
            <label style={{ flex: "1 1 200px", minWidth: 160 }}>
              Execution ID
              <div className="inline">
                <input
                  value={loadId}
                  onChange={(e) => setLoadId(e.target.value)}
                  placeholder="execution_id"
                  className="mono"
                />
                <button
                  type="button"
                  className="secondary"
                  disabled={loadingInv || !loadId.trim()}
                  onClick={() => {
                    onExecutionIdChange(loadId.trim());
                    void loadInvestigation(loadId);
                  }}
                >
                  Load
                </button>
              </div>
            </label>
          </div>

          {inv.diagnosis ? (
            <div
              className={
                inv.diagnosis.failure_code.startsWith("OK_")
                  ? "diagnosis-hero ok"
                  : "diagnosis-hero fail"
              }
            >
              <div className="diagnosis-hero-top">
                <div>
                  <div className="label">Diagnosis</div>
                  <div className="failure-code">
                    {inv.diagnosis.failure_code}
                  </div>
                </div>
                <div>
                  <div className="label">Rule</div>
                  <div className="rule-id">{inv.diagnosis.rule_id}</div>
                </div>
              </div>
              <div className="diagnosis-meta diagnosis-meta-grid">
                <div className="meta-item">
                  <span className="meta-k">Layer</span>
                  <span className="meta-v">
                    {formatLayer(inv.diagnosis.layer)}
                  </span>
                </div>
                <div className="meta-item">
                  <span className="meta-k">Confidence</span>
                  <span className="meta-v">
                    {formatConfidence(inv.diagnosis.confidence)}
                  </span>
                </div>
              </div>
              {(inv.failure?.description || inv.rule?.summary) && (
                <p className="diagnosis-summary">
                  {inv.failure?.description || inv.rule?.summary}
                </p>
              )}
            </div>
          ) : (
            <EmptyState compact>
              No diagnosis yet for this execution. Run diagnose first.
            </EmptyState>
          )}

          <div className="panel tight">
            <Section title="Execution" id="execution-section">
              <div className="meta-grid">
                <div className="meta-item">
                  <span className="meta-k">Query</span>
                  <span className="meta-v">{inv.execution.query}</span>
                </div>
                <div className="meta-item">
                  <span className="meta-k">Execution ID</span>
                  <span className="meta-v mono" title={inv.execution.execution_id}>
                    {inv.execution.execution_id}
                  </span>
                </div>
                <div className="meta-item">
                  <span className="meta-k">Corpus version</span>
                  <span className="meta-v mono" title={inv.execution.corpus_version_id}>
                    {inv.execution.corpus_version_id}
                  </span>
                  {executionCorpus ? (
                    <span className="meta-sub muted small">
                      {executionCorpus.title}
                      {" · "}
                      {executionCorpus.chunkCount} chunks
                    </span>
                  ) : null}
                </div>
                <div className="meta-item">
                  <span className="meta-k">Top K</span>
                  <span className="meta-v">{inv.execution.top_k}</span>
                </div>
                <div className="meta-item">
                  <span className="meta-k">Model</span>
                  <span className="meta-v">{inv.execution.generation.model || "—"}</span>
                </div>
                <div className="meta-item">
                  <span className="meta-k">Temperature</span>
                  <span className="meta-v">
                    {inv.execution.generation.temperature == null
                      ? "—"
                      : String(inv.execution.generation.temperature)}
                  </span>
                </div>
                <div className="meta-item">
                  <span className="meta-k">Status</span>
                  <span className="meta-v">
                    <StatusBadge status={inv.execution.status} />
                  </span>
                </div>
                <div className="meta-item">
                  <span className="meta-k">Generate total</span>
                  <span className="meta-v">
                    {formatMs(
                      inv.execution.latency_ms.generate_total ??
                        inv.execution.latency_ms.total,
                    )}
                  </span>
                  <span className="meta-sub muted small">
                    Retrieval + generation wall-clock
                  </span>
                </div>
                <div className="meta-item">
                  <span className="meta-k">Diagnosis</span>
                  <span className="meta-v">
                    {formatMs(inv.execution.latency_ms.diagnosis)}
                  </span>
                  <span className="meta-sub muted small">
                    Diagnose request wall-clock (judges sequential)
                  </span>
                </div>
              </div>
            </Section>

            <Section title="Trace">
              <p className="note muted small" style={{ marginBottom: 10 }}>
                Generate and diagnose are separate requests. Judge durations are
                individual LLM calls inside diagnose; they are not part of
                Generate total.
              </p>
              <ul className="timeline">
                {inv.timeline.map((t) => (
                  <li key={`${t.operation}-${t.id}`} className="timeline-item">
                    <span className="timeline-dot" aria-hidden="true" />
                    <div className="timeline-body">
                      <div className="timeline-op">
                        {t.operation}
                        {t.phase ? (
                          <span className="timeline-phase muted">{t.phase}</span>
                        ) : null}
                      </div>
                      <div className="timeline-meta">
                        <span>
                          status <code>{t.status}</code>
                        </span>
                        {t.duration_ms != null ? (
                          <span>{t.duration_ms} ms</span>
                        ) : null}
                        {t.id ? (
                          <code className="clip-id" title={t.id}>
                            {t.id}
                          </code>
                        ) : null}
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            </Section>

            <Section title="Retrieval evidence" id="retrieval-section">
              <div className="meta-grid" style={{ marginBottom: 12 }}>
                <div className="meta-item">
                  <span className="meta-k">n_retrieved</span>
                  <span className="meta-v">{inv.retrieval.n_retrieved}</span>
                </div>
                <div className="meta-item">
                  <span className="meta-k">gold_hit</span>
                  <span className="meta-v">
                    {formatGoldHit(inv.retrieval)}
                  </span>
                </div>
                <div className="meta-item">
                  <span className="meta-k">context_sufficient</span>
                  <span className="meta-v">
                    {formatOptionalBool(inv.retrieval.context_sufficient)}
                  </span>
                </div>
                <div className="meta-item">
                  <span className="meta-k">irrelevant_frac</span>
                  <span className="meta-v">
                    {inv.retrieval.irrelevant_frac == null
                      ? "—"
                      : String(inv.retrieval.irrelevant_frac)}
                  </span>
                </div>
              </div>
              {inv.retrieval.chunks.length === 0 ? (
                <EmptyState compact>No retrieved chunks.</EmptyState>
              ) : (
                <div className="table-scroll">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Rank</th>
                        <th>Document</th>
                        <th>Chunk</th>
                        <th className="num">Similarity</th>
                        <th>Status</th>
                        <th>Text</th>
                      </tr>
                    </thead>
                    <tbody>
                      {inv.retrieval.chunks.map((c) => {
                        const ref = c.chunk_id ? `chunk:${c.chunk_id}` : "";
                        const active = activeEvidence === ref;
                        return (
                          <tr
                            key={`${c.chunk_id}-${c.rank}-${c.evidence_status}`}
                            id={c.chunk_id ? `chunk-${c.chunk_id}` : undefined}
                            className={active ? "row-active" : undefined}
                          >
                            <td className="num">{c.rank ?? "—"}</td>
                            <td>{c.source_name || c.document_id || "—"}</td>
                            <td>
                              <code>{c.chunk_id || "—"}</code>
                            </td>
                            <td className="num">
                              {c.score == null
                                ? "—"
                                : Number(c.score).toFixed(4)}
                            </td>
                            <td>
                              <StatusBadge
                                status={c.evidence_status}
                                tone={evidenceTone(c.evidence_status)}
                              />
                            </td>
                            <td>
                              {c.text ? (
                                c.text.length > 80 ? (
                                  <details className="chunk-details">
                                    <summary>{`${c.text.slice(0, 80)}…`}</summary>
                                    <pre className="answer">{c.text}</pre>
                                  </details>
                                ) : (
                                  <span className="clip">{c.text}</span>
                                )
                              ) : (
                                <span className="muted">—</span>
                              )}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </Section>

            <Section title="Generation">
              <div className="meta-grid" style={{ marginBottom: 12 }}>
                <div className="meta-item">
                  <span className="meta-k">Abstention</span>
                  <span className="meta-v">
                    {inv.execution.abstained ? "yes" : "no"}
                    {inv.execution.abstention_kind
                      ? ` · ${inv.execution.abstention_kind}`
                      : ""}
                  </span>
                </div>
                <div className="meta-item">
                  <span className="meta-k">Prompt version</span>
                  <span className="meta-v mono">
                    {inv.execution.generation.prompt_version || "—"}
                  </span>
                </div>
                <div className="meta-item">
                  <span className="meta-k">Latency</span>
                  <span className="meta-v">
                    {inv.execution.generation.latency_ms != null
                      ? `${inv.execution.generation.latency_ms} ms`
                      : "—"}
                  </span>
                </div>
              </div>
              <h4 className="subhead">Generated answer</h4>
              <MarkdownAnswer text={inv.execution.answer || ""} />
            </Section>

            <Section title="Judges" id="judges-section">
              {inv.judges.length === 0 ? (
                <EmptyState compact>
                  No judges ran (short-circuit diagnosis or not yet diagnosed).
                </EmptyState>
              ) : (
                <div className="judge-grid">
                  {inv.judges.map((j) => (
                    <div key={j.judge_type} className="judge-card">
                      <div className="inline spread">
                        <strong>{j.judge_type}</strong>
                        <StatusBadge
                          status={j.status}
                          tone={j.schema_ok ? "ok" : "fail"}
                        />
                      </div>
                      <MetaTable
                        rows={[
                          ...(j.model
                            ? ([["model", j.model]] as Array<[string, string]>)
                            : []),
                          [
                            "latency",
                            j.latency_ms != null ? `${j.latency_ms} ms` : "—",
                          ],
                          ...Object.entries(j.result).map(
                            ([k, v]) =>
                              [
                                k,
                                <code key={k}>{JSON.stringify(v)}</code>,
                              ] as [string, ReactNode],
                          ),
                        ]}
                      />
                      <RawToggle label="Raw judge output" data={j.output} />
                    </div>
                  ))}
                </div>
              )}
            </Section>

            <Section title="Rule details">
              {inv.rule ? (
                <>
                  <p className="note">{inv.why.note}</p>
                  <MetaTable
                    rows={[
                      ["Rule ID", <code key="rid">{inv.rule.rule_id}</code>],
                      [
                        "Failure code",
                        <code key="res">{inv.rule.result}</code>,
                      ],
                      ["Layer", formatLayer(inv.rule.layer)],
                      [
                        "Conditions",
                        <ul key="cond" className="plain-list">
                          {inv.rule.conditions.map((c) => (
                            <li key={c}>
                              <code>{c}</code>
                            </li>
                          ))}
                        </ul>,
                      ],
                      ["Summary", inv.rule.summary],
                    ]}
                  />
                  <h4 className="subhead">Signals used</h4>
                  <MetaTable
                    rows={Object.entries(inv.why.signals_used).map(([k, v]) => [
                      k,
                      <code key={k}>{formatSignalValue(k, v)}</code>,
                    ])}
                  />
                  {inv.failure?.runbook && (
                    <div className="inline" style={{ marginTop: 12 }}>
                      <button
                        type="button"
                        className="secondary"
                        onClick={() => void openRunbook(inv.failure!.runbook!)}
                      >
                        Runbook: {inv.failure.runbook}
                      </button>
                    </div>
                  )}
                </>
              ) : (
                <EmptyState compact>No rule attached (diagnose first).</EmptyState>
              )}
            </Section>

            <Section title="Evidence references">
              {inv.evidence.length === 0 ? (
                <EmptyState compact>No evidence references stored.</EmptyState>
              ) : (
                <ul className="plain-list evidence-list">
                  {inv.evidence.map((e) => (
                    <li key={`${e.evidence_type}-${e.ref}`}>
                      <button
                        type="button"
                        className="linkish"
                        onClick={() => e.ref && jumpToEvidence(e.ref)}
                      >
                        <code>{e.ref}</code>
                      </button>
                      <span className="muted"> · {e.evidence_type}</span>
                    </li>
                  ))}
                </ul>
              )}
            </Section>

            {runbookText && (
              <Section title="Runbook">
                <pre className="runbook">{runbookText}</pre>
              </Section>
            )}

            <RawToggle label="View raw execution JSON" data={inv} />
          </div>
        </div>
      )}
    </div>
  );
}
