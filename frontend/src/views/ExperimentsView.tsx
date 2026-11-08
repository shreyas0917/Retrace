import { useEffect, useState } from "react";
import { apiGet } from "../api";
import { EmptyState, ErrorBanner, LoadingState, PageHeader, StatusBadge } from "../components/ui";
import {
  CaseTable,
  ComparisonTable,
  MetricTiles,
  PerClassF1,
  RunDetails,
  SuiteName,
  VerdictBanner,
} from "../components/EvalParts";
import { statusLabel } from "../labels";
import { gateVerdict } from "../format";
import type {
  CaseResult,
  Comparison,
  ExperimentDetail,
  ExperimentListItem,
  PerClassMetric,
  SelectiveMetrics,
} from "../types";

type Props = {
  apiKey: string;
  onOpenExecution: (executionId: string) => void;
};

function experimentTone(status: string): "ok" | "fail" | "warn" | "neutral" | "info" {
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
      const body = await apiGet<{ experiments: ExperimentListItem[] }>("/api/v1/experiments?limit=30", apiKey);
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
      const d = await apiGet<ExperimentDetail>(`/api/v1/experiments/${id}`, apiKey);
      setDetail(d);
      const res = await apiGet<{ results: CaseResult[] }>(`/api/v1/experiments/${id}/results`, apiKey);
      setResults(res.results || []);
      try {
        setComparison(await apiGet<Comparison>(`/api/v1/experiments/${id}/comparison`, apiKey));
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

  useEffect(() => {
    if (!detail) return;
    requestAnimationFrame(() => {
      document.getElementById("experiment-detail")?.scrollIntoView?.({ behavior: "smooth", block: "start" });
    });
  }, [detail?.experiment_id]);

  const metrics = (detail?.metrics || {}) as Record<string, unknown>;

  return (
    <div>
      <PageHeader
        title="Experiments"
        description="Past evaluation runs, each compared against the accepted baseline for its suite."
        actions={
          <button type="button" className="secondary" onClick={() => void refreshList()} disabled={loading}>
            Refresh
          </button>
        }
      />

      <ErrorBanner message={error} />

      <section className="report-card" aria-labelledby="history-title" style={{ marginBottom: "var(--space-4)" }}>
        <div className="report-card-head">
          <h2 className="report-card-title" id="history-title">
            Run history
          </h2>
        </div>
        {loading && list.length === 0 && <LoadingState label="Loading experiments…" />}
        {!loading && list.length === 0 && <EmptyState compact>No experiments yet.</EmptyState>}
        {list.length > 0 && (
          <div className="table-scroll experiment-history-scroll" role="region" aria-label="Run history" tabIndex={0}>
            <table className="data-table">
              <thead>
                <tr>
                  <th>Run</th>
                  <th>Suite</th>
                  <th>Status</th>
                  <th>Started</th>
                </tr>
              </thead>
              <tbody>
                {list.map((e) => (
                  <tr key={e.experiment_id} className={e.experiment_id === selectedId ? "row-active" : undefined}>
                    <td>
                      <button
                        type="button"
                        className="linkish"
                        aria-current={e.experiment_id === selectedId ? "true" : undefined}
                        onClick={() => void openExperiment(e.experiment_id)}
                      >
                        {e.name || e.experiment_id.slice(0, 8)}
                      </button>
                      <code className="muted block-code" title={e.experiment_id}>
                        {e.experiment_id.slice(0, 8)}
                      </code>
                    </td>
                    <td>
                      <SuiteName id={e.suite_id} version={e.suite_version} />
                    </td>
                    <td>
                      <StatusBadge status={e.status} label={statusLabel(e.status)} tone={experimentTone(e.status)} />
                    </td>
                    <td className="muted small nowrap">
                      {e.created_at ? new Date(e.created_at).toLocaleString() : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {!detail && !loading && <EmptyState compact>Select a run to inspect it.</EmptyState>}
      {loading && selectedId && <LoadingState label="Loading experiment…" />}

      {detail && (
        <div className="eval-stack" id="experiment-detail">
          <VerdictBanner
            verdict={gateVerdict({ status: detail.status, comparison: comparison?.comparison ?? null })}
            context={<SuiteName id={detail.suite_id} version={detail.suite_version} />}
          />
          {detail.metrics ? (
            <>
              <MetricTiles summary={metrics} />
              <PerClassF1
                perClass={metrics.per_class as Record<string, PerClassMetric> | undefined}
                selective={metrics.selective as SelectiveMetrics | undefined}
              />
            </>
          ) : (
            <EmptyState compact>No metrics stored.</EmptyState>
          )}
          <CaseTable cases={results} onOpenExecution={onOpenExecution} />
          <ComparisonTable comparison={comparison} />
          <RunDetails
            rows={[
              ["Experiment ID", <code key="e">{detail.experiment_id}</code>],
              ["Name", detail.name || "—"],
              ["Suite", <SuiteName key="s" id={detail.suite_id} version={detail.suite_version} />],
              ["Suite hash", <code key="h">{detail.suite_hash || "—"}</code>],
              [
                "Baseline ID",
                comparison?.baseline?.baseline_id ? <code key="b">{String(comparison.baseline.baseline_id)}</code> : "None",
              ],
              ["Git commit", detail.git_commit ? <code key="g">{detail.git_commit}</code> : "—"],
              ["Status", statusLabel(detail.status)],
              ["Started", detail.created_at || "—"],
              ["Completed", detail.completed_at || "—"],
            ]}
            raw={detail}
          />
        </div>
      )}
    </div>
  );
}
