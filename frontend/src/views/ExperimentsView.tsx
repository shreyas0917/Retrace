import { useEffect, useState } from "react";
import { apiGet } from "../api";
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
import type {
  CaseResult,
  Comparison,
  ExperimentDetail,
  ExperimentListItem,
  PerClassMetric,
  SelectiveMetrics,
} from "../types";
import { PerClassSection } from "../components/PerClassSection";

type Props = {
  apiKey: string;
  onOpenExecution: (executionId: string) => void;
};

function experimentTone(
  status: string,
): "ok" | "fail" | "warn" | "neutral" | "info" {
  const u = status.toUpperCase();
  if (u === "COMPLETED" || u === "PASSED" || u === "PASS") return "ok";
  if (u === "RUNNING" || u === "PENDING") return "info";
  if (u === "REGRESSION") return "warn";
  if (u === "FAILED" || u === "FAIL" || u === "ERROR") return "fail";
  return "neutral";
}

export function ExperimentsView({ apiKey, onOpenExecution }: Props) {
  const [list, setList] = useState<ExperimentListItem[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [detail, setDetail] = useState<ExperimentDetail | null>(null);
  const [results, setResults] = useState<CaseResult[]>([]);
  const [comparison, setComparison] = useState<Comparison | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function refreshList() {
    setError("");
    setLoading(true);
    try {
      const body = await apiGet<{ experiments: ExperimentListItem[] }>(
        "/api/v1/experiments?limit=30",
        apiKey,
      );
      setList(body.experiments || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to list experiments");
    } finally {
      setLoading(false);
    }
  }

  async function openExperiment(id: string) {
    setSelectedId(id);
    setError("");
    setLoading(true);
    try {
      const d = await apiGet<ExperimentDetail>(
        `/api/v1/experiments/${id}`,
        apiKey,
      );
      setDetail(d);
      const res = await apiGet<{ results: CaseResult[] }>(
        `/api/v1/experiments/${id}/results`,
        apiKey,
      );
      setResults(res.results || []);
      try {
        const cmp = await apiGet<Comparison>(
          `/api/v1/experiments/${id}/comparison`,
          apiKey,
        );
        setComparison(cmp);
      } catch {
        setComparison(null);
      }
    } catch (err) {
      setDetail(null);
      setResults([]);
      setError(err instanceof Error ? err.message : "Unable to load experiment");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void refreshList();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiKey]);

  // Detail renders below a long history table; scroll it into view so a
  // row click is visibly connected to the inspection panel.
  useEffect(() => {
    if (!detail) return;
    requestAnimationFrame(() => {
      document.getElementById("experiment-detail")?.scrollIntoView({
        behavior: "smooth",
        block: "start",
      });
    });
  }, [detail?.experiment_id]);

  return (
    <div>
      <PageHeader
        eyebrow="Experiments"
        title="Experiments"
        description="Compare experiment results against accepted baselines."
        actions={
          <button
            type="button"
            className="secondary"
            onClick={() => void refreshList()}
            disabled={loading}
          >
            Refresh
          </button>
        }
      />

      <ErrorBanner message={error} />

      <div className="panel tight" style={{ marginBottom: 16 }}>
        <Section title="Experiment history">
          {loading && list.length === 0 && (
            <LoadingState label="Loading experiments…" />
          )}
          {!loading && list.length === 0 && (
            <EmptyState>No experiments yet.</EmptyState>
          )}
          {list.length > 0 && (
            <div className="table-scroll experiment-history-scroll">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Experiment</th>
                    <th>Suite</th>
                    <th>Status</th>
                    <th>Created</th>
                  </tr>
                </thead>
                <tbody>
                  {list.map((e) => (
                    <tr
                      key={e.experiment_id}
                      className={
                        e.experiment_id === selectedId ? "row-active" : undefined
                      }
                      style={{ cursor: "pointer" }}
                      onClick={() => void openExperiment(e.experiment_id)}
                    >
                      <td>
                        <code
                          className="mono"
                          title={e.experiment_id}
                        >
                          {e.experiment_id.slice(0, 8)}
                        </code>
                      </td>
                      <td>
                        <span className="mono">{e.suite_id}</span>
                        {e.suite_version ? (
                          <span className="muted"> @ {e.suite_version}</span>
                        ) : null}
                      </td>
                      <td>
                        <StatusBadge
                          status={e.status}
                          tone={experimentTone(e.status)}
                        />
                      </td>
                      <td className="muted small" style={{ whiteSpace: "nowrap" }}>
                        {e.created_at
                          ? new Date(e.created_at).toLocaleString()
                          : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Section>
      </div>

      {!detail && !loading && (
        <EmptyState compact>Select an experiment to inspect.</EmptyState>
      )}
      {loading && selectedId && (
        <LoadingState label="Loading experiment…" />
      )}

      {detail && (
        <div className="panel tight" id="experiment-detail">
          <Section title="Overview">
            <div className="meta-grid">
              <div className="meta-item">
                <span className="meta-k">Experiment ID</span>
                <span className="meta-v mono">{detail.experiment_id}</span>
              </div>
              <div className="meta-item">
                <span className="meta-k">Name</span>
                <span className="meta-v">{detail.name || "—"}</span>
              </div>
              <div className="meta-item">
                <span className="meta-k">Suite</span>
                <span className="meta-v">
                  {detail.suite_id} @ {detail.suite_version}
                </span>
              </div>
              <div className="meta-item">
                <span className="meta-k">Status</span>
                <span className="meta-v">
                  <StatusBadge
                    status={detail.status}
                    tone={experimentTone(detail.status)}
                  />
                </span>
              </div>
              <div className="meta-item">
                <span className="meta-k">Created</span>
                <span className="meta-v">{detail.created_at || "—"}</span>
              </div>
              <div className="meta-item">
                <span className="meta-k">Completed</span>
                <span className="meta-v">{detail.completed_at || "—"}</span>
              </div>
              <div className="meta-item">
                <span className="meta-k">Suite hash</span>
                <span className="meta-v mono">{detail.suite_hash || "—"}</span>
              </div>
              <div className="meta-item">
                <span className="meta-k">Git commit</span>
                <span className="meta-v mono">{detail.git_commit || "—"}</span>
              </div>
            </div>
            <RawToggle label="Pipeline / metrics raw" data={detail} />
          </Section>

          <Section title="Metrics">
            {!detail.metrics ? (
              <EmptyState>No metrics stored.</EmptyState>
            ) : (
              <MetaTable
                rows={Object.entries(detail.metrics)
                  .filter(
                    ([k]) =>
                      !["confusion_matrix", "per_class", "selective"].includes(k),
                  )
                  .map(([k, v]) => [
                    k,
                    <code key={k}>{JSON.stringify(v)}</code>,
                  ])}
              />
            )}
          </Section>

          {detail.metrics && (
            <PerClassSection
              perClass={
                detail.metrics.per_class as
                  | Record<string, PerClassMetric>
                  | undefined
              }
              selective={detail.metrics.selective as SelectiveMetrics | undefined}
            />
          )}

          <Section title="Baseline comparison">
            {!comparison ? (
              <EmptyState>No comparison for this experiment.</EmptyState>
            ) : (
              <>
                <div className="inline" style={{ marginBottom: 8 }}>
                  <StatusBadge
                    status={
                      comparison.comparison.has_baseline
                        ? comparison.comparison.passed
                          ? "PASS"
                          : "REGRESSION"
                        : "NO_BASELINE"
                    }
                    tone={
                      !comparison.comparison.has_baseline
                        ? "warn"
                        : comparison.comparison.passed
                          ? "ok"
                          : "warn"
                    }
                  />
                </div>
                <div className="table-scroll">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Metric</th>
                        <th>Baseline</th>
                        <th>Current</th>
                        <th>Delta</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(comparison.comparison.rows || []).map((row) => (
                        <tr key={row.metric}>
                          <td>
                            <code>{row.metric}</code>
                          </td>
                          <td>
                            {row.baseline == null ? "—" : String(row.baseline)}
                          </td>
                          <td>
                            {row.current == null ? "—" : String(row.current)}
                          </td>
                          <td>
                            {row.delta == null ? "—" : String(row.delta)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </Section>

          <Section title="Case results">
            {results.length === 0 ? (
              <EmptyState>No case results.</EmptyState>
            ) : (
              <div className="table-scroll">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Case</th>
                      <th>Predicted</th>
                      <th>Rule</th>
                      <th>Status</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {results.map((c) => (
                      <tr key={c.case_id}>
                        <td>
                          <code>{c.case_id}</code>
                        </td>
                        <td>
                          <code>{c.predicted_failure_code || "—"}</code>
                        </td>
                        <td>
                          <code>{c.predicted_rule_id || "—"}</code>
                        </td>
                        <td>
                          <StatusBadge
                            status={c.passed ? "PASS" : "FAIL"}
                            tone={c.passed ? "ok" : "fail"}
                          />
                        </td>
                        <td>
                          {c.execution_id ? (
                            <button
                              type="button"
                              className="secondary"
                              onClick={() => onOpenExecution(c.execution_id!)}
                            >
                              Investigate
                            </button>
                          ) : (
                            "—"
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Section>
        </div>
      )}
    </div>
  );
}
