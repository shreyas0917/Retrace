import { useState } from "react";
import { apiGet, apiPost } from "../api";
import { EmptyState, ErrorBanner, LoadingState, PageHeader } from "../components/ui";
import {
  CaseTable,
  ComparisonTable,
  MetricTiles,
  PerClassF1,
  RunDetails,
  SuiteName,
  VerdictBanner,
} from "../components/EvalParts";
import { SUITE_LABELS } from "../labels";
import { gateVerdict, pct } from "../format";
import type {
  CaseResult,
  Comparison,
  EvalRunResult,
  ExperimentDetail,
  PerClassMetric,
  SelectiveMetrics,
} from "../types";

type Props = {
  apiKey: string;
  onOpenExecution: (executionId: string) => void;
};

/** Suites offered in the picker. Selecting one never starts a run. */
export const SUITE_OPTIONS = ["planted_v1", "heldout_v1", "calib_v1", "gold_v1", "live_v1"];

export function EvaluationsView({ apiKey, onOpenExecution }: Props) {
  const [suiteId, setSuiteId] = useState("planted_v1");
  const [suiteVersion, setSuiteVersion] = useState("1.0.0");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [run, setRun] = useState<EvalRunResult | null>(null);
  const [detail, setDetail] = useState<ExperimentDetail | null>(null);
  const [results, setResults] = useState<CaseResult[]>([]);
  const [comparison, setComparison] = useState<Comparison | null>(null);
  const [baseline, setBaseline] = useState<Record<string, unknown> | null>(null);

  async function runEval() {
    setBusy(true);
    setError("");
    setRun(null);
    setDetail(null);
    setResults([]);
    setComparison(null);
    setBaseline(null);
    try {
      const body = await apiPost<EvalRunResult>("/api/v1/experiments", apiKey, {
        suite_id: suiteId,
        suite_version: suiteVersion,
      });
      setRun(body);
      await loadExperiment(body.experiment_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Evaluation failed");
    } finally {
      setBusy(false);
    }
  }

  async function loadExperiment(experimentId: string) {
    try {
      const d = await apiGet<ExperimentDetail>(`/api/v1/experiments/${experimentId}`, apiKey);
      setDetail(d);
      const res = await apiGet<{ results: CaseResult[] }>(
        `/api/v1/experiments/${experimentId}/results`,
        apiKey,
      );
      setResults(res.results || []);
      try {
        setComparison(
          await apiGet<Comparison>(`/api/v1/experiments/${experimentId}/comparison`, apiKey),
        );
      } catch {
        setComparison(null);
      }
      if (d.suite_id && d.suite_version) {
        const b = await apiGet<{ baseline: Record<string, unknown> | null }>(
          `/api/v1/baselines/active?suite_id=${encodeURIComponent(d.suite_id)}&suite_version=${encodeURIComponent(d.suite_version)}`,
          apiKey,
        );
        setBaseline(b.baseline);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load experiment");
    }
  }

  const summary = (run?.summary || detail?.metrics || {}) as Record<string, unknown>;
  const verdict = gateVerdict({
    exitCode: run?.exit_code,
    status: run?.status || detail?.status,
    comparison: comparison?.comparison ?? null,
  });
  const selective = summary.selective as SelectiveMetrics | undefined;
  const suiteHelp = SUITE_LABELS[suiteId]?.help;

  return (
    <div>
      <PageHeader
        title="Evaluations"
        description="Run a reproducible suite and see whether the diagnosis engine still passes its gate."
      />

      <form
        className="control-bar"
        aria-label="Run an evaluation"
        onSubmit={(e) => {
          e.preventDefault();
          void runEval();
        }}
      >
        <label>
          Suite
          <select value={suiteId} onChange={(e) => setSuiteId(e.target.value)}>
            {SUITE_OPTIONS.map((id) => (
              <option key={id} value={id}>
                {SUITE_LABELS[id]?.label || id} ({id})
              </option>
            ))}
          </select>
        </label>
        <label className="narrow-wide">
          Version
          <input value={suiteVersion} onChange={(e) => setSuiteVersion(e.target.value)} />
        </label>
        <button type="submit" disabled={busy}>
          {busy ? "Running…" : "Run evaluation"}
        </button>
        {suiteHelp ? (
          <p className="control-hint muted small">
            {suiteHelp} Choosing a suite does not start it; press Run evaluation.
          </p>
        ) : null}
      </form>

      <ErrorBanner message={error} />
      {busy && <LoadingState label="Running evaluation…" />}

      {!busy && !run && !detail && (
        <EmptyState hint="Pick a suite and press Run evaluation. Past runs are listed under Experiments.">
          No evaluation loaded. Run a suite to begin.
        </EmptyState>
      )}

      {(run || detail) && (
        <div className="eval-stack">
          <VerdictBanner
            verdict={verdict}
            context={
              <>
                <SuiteName id={run?.suite_id || detail?.suite_id} version={run?.suite_version || detail?.suite_version} />
                {selective?.uncertain_rate != null ? (
                  <span className="muted small"> · {pct(selective.uncertain_rate)} deferred as uncertain</span>
                ) : null}
                <span className="muted small">
                  {" "}
                  · baseline {baseline ? "accepted" : "none"}
                </span>
              </>
            }
          />
          <MetricTiles summary={summary} />
          <PerClassF1
            perClass={summary.per_class as Record<string, PerClassMetric> | undefined}
            selective={selective}
          />
          <CaseTable cases={results} onOpenExecution={onOpenExecution} />
          <ComparisonTable comparison={comparison} />
          <RunDetails
            rows={[
              ["Experiment ID", <code key="e">{run?.experiment_id || detail?.experiment_id}</code>],
              ["Suite", <SuiteName key="s" id={run?.suite_id || detail?.suite_id} version={run?.suite_version || detail?.suite_version} />],
              ["Suite hash", <code key="h">{run?.suite_hash || detail?.suite_hash || "—"}</code>],
              ["Baseline ID", baseline ? <code key="b">{String(baseline.baseline_id)}</code> : "None"],
              [
                "Baseline source experiment",
                baseline?.experiment_id ? <code key="be">{String(baseline.experiment_id)}</code> : "—",
              ],
              ["Git commit", detail?.git_commit ? <code key="g">{detail.git_commit}</code> : "—"],
              ["Started", detail?.created_at || "—"],
              ["Completed", detail?.completed_at || "—"],
            ]}
            raw={{ run, detail }}
          />
        </div>
      )}
    </div>
  );
}
