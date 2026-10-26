import { useState } from "react";
import { apiGet, apiPost } from "../api";
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
  EvalRunResult,
  ExperimentDetail,
  PerClassMetric,
  SelectiveMetrics,
} from "../types";
import { PerClassSection } from "../components/PerClassSection";

type Props = {
  apiKey: string;
  onOpenExecution: (executionId: string) => void;
};

function gateTone(
  status: string,
  exitCode?: number,
): "ok" | "fail" | "warn" | "neutral" {
  if (exitCode === 0 || status === "PASS" || status === "passed") return "ok";
  if (exitCode === 1 || status === "REGRESSION" || status === "failed")
    return "warn";
  if (exitCode === 2 || status === "ERROR") return "fail";
  return "neutral";
}

function pct(value: unknown): string {
  if (value == null) return "—";
  return `${Math.round(Number(value) * 100)}%`;
}

export function EvaluationsView({ apiKey, onOpenExecution }: Props) {
  const [suiteId, setSuiteId] = useState("planted_v1");
  const [suiteVersion, setSuiteVersion] = useState("1.0.0");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [run, setRun] = useState<EvalRunResult | null>(null);
  const [detail, setDetail] = useState<ExperimentDetail | null>(null);
  const [results, setResults] = useState<CaseResult[]>([]);
  const [comparison, setComparison] = useState<Comparison | null>(null);
  const [baseline, setBaseline] = useState<Record<string, unknown> | null>(
    null,
  );

  async function runEval() {
    setBusy(true);
    setError("");
    setRun(null);
    setDetail(null);
    setResults([]);
    setComparison(null);
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
    setError("");
    try {
      const d = await apiGet<ExperimentDetail>(
        `/api/v1/experiments/${experimentId}`,
        apiKey,
      );
      setDetail(d);
      const res = await apiGet<{ results: CaseResult[] }>(
        `/api/v1/experiments/${experimentId}/results`,
        apiKey,
      );
      setResults(res.results || []);
      try {
        const cmp = await apiGet<Comparison>(
          `/api/v1/experiments/${experimentId}/comparison`,
          apiKey,
        );
        setComparison(cmp);
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

  const summary = (run?.summary || detail?.metrics || {}) as Record<
    string,
    unknown
  >;
  const exitCode = run?.exit_code;
  const statusLabel =
    exitCode === 0
      ? "PASS"
      : exitCode === 1
        ? "REGRESSION"
        : exitCode === 2
          ? "ERROR"
          : run?.status || detail?.status || "—";

  return (
    <div>
      <PageHeader
        eyebrow="Evaluations"
        title="Evaluations"
        description="Run a reproducible suite and determine whether the system passes."
      />

      <div className="control-bar">
        <label>
          Suite
          <select value={suiteId} onChange={(e) => setSuiteId(e.target.value)}>
            <option value="planted_v1">planted_v1 (12 planted scenarios)</option>
            <option value="heldout_v1">heldout_v1 (160 held-out cases)</option>
            <option value="calib_v1">calib_v1 (80 calibration cases)</option>
            <option value="gold_v1">gold_v1</option>
          </select>
        </label>
        <label>
          Version
          <input
            value={suiteVersion}
            onChange={(e) => setSuiteVersion(e.target.value)}
          />
        </label>
        <button type="button" disabled={busy} onClick={() => void runEval()}>
          {busy ? "Running…" : "Run evaluation"}
        </button>
      </div>

      <ErrorBanner message={error} />
      {busy && <LoadingState label="Running evaluation…" />}

      {!busy && !run && !detail && (
        <EmptyState compact>
          No evaluation loaded. Run a suite to begin.
        </EmptyState>
      )}

      {(run || detail) && (
        <>
          <div className="metric-strip">
            <div className="metric-cell">
              <div className="metric-label">Status</div>
              <div className="metric-value" style={{ fontSize: 14 }}>
                <StatusBadge
                  status={String(statusLabel)}
                  tone={gateTone(String(statusLabel), exitCode)}
                />
              </div>
            </div>
            <div className="metric-cell">
              <div className="metric-label">Cases</div>
              <div className="metric-value">
                {String(summary.total_cases ?? summary.n ?? "—")}
              </div>
            </div>
            <div className="metric-cell">
              <div className="metric-label">Failure-code accuracy</div>
              <div className="metric-value">
                {pct(summary.failure_code_accuracy)}
              </div>
            </div>
            <div className="metric-cell">
              <div className="metric-label">Rule accuracy</div>
              <div className="metric-value">{pct(summary.rule_accuracy)}</div>
            </div>
            <div className="metric-cell">
              <div className="metric-label">Evidence accuracy</div>
              <div className="metric-value">{pct(summary.evidence_accuracy)}</div>
            </div>
            <div className="metric-cell">
              <div className="metric-label">Strict accuracy</div>
              <div className="metric-value">{pct(summary.strict_accuracy)}</div>
            </div>
            <div className="metric-cell">
              <div className="metric-label">Macro-F1</div>
              <div className="metric-value">
                {summary.macro_f1 == null
                  ? "—"
                  : Number(summary.macro_f1).toFixed(3)}
              </div>
            </div>
            <div className="metric-cell">
              <div className="metric-label">Deferred (uncertain)</div>
              <div className="metric-value">
                {pct(
                  (summary.selective as SelectiveMetrics | undefined)
                    ?.uncertain_rate,
                )}
              </div>
            </div>
            <div className="metric-cell">
              <div className="metric-label">Baseline</div>
              <div className="metric-value" style={{ fontSize: 14 }}>
                {baseline ? (
                  <StatusBadge status="Accepted" tone="ok" />
                ) : (
                  <StatusBadge status="None" tone="neutral" />
                )}
              </div>
            </div>
          </div>

          <div className="panel tight">
            <Section title="Run summary">
              <MetaTable
                rows={[
                  [
                    "experiment_id",
                    <code key="e">
                      {run?.experiment_id || detail?.experiment_id}
                    </code>,
                  ],
                  [
                    "suite",
                    `${run?.suite_id || detail?.suite_id} @ ${run?.suite_version || detail?.suite_version}`,
                  ],
                  [
                    "suite_hash",
                    <code key="h">
                      {(run?.suite_hash || detail?.suite_hash || "").slice(0, 16)}
                      …
                    </code>,
                  ],
                  ["correct", String(summary.correct ?? "—")],
                  ["incorrect", String(summary.incorrect ?? "—")],
                  [
                    "failure_code_accuracy",
                    String(summary.failure_code_accuracy ?? "—"),
                  ],
                  ["rule_accuracy", String(summary.rule_accuracy ?? "—")],
                  [
                    "evidence_accuracy",
                    String(summary.evidence_accuracy ?? "—"),
                  ],
                  ...(exitCode != null
                    ? ([["exit_code", String(exitCode)]] as Array<
                        [string, string]
                      >)
                    : []),
                ]}
              />
            </Section>

            <PerClassSection
              perClass={
                summary.per_class as Record<string, PerClassMetric> | undefined
              }
              selective={summary.selective as SelectiveMetrics | undefined}
            />

            <Section title="Active baseline">
              {!baseline ? (
                <EmptyState>
                  No accepted baseline for this suite/version.
                </EmptyState>
              ) : (
                <MetaTable
                  rows={[
                    [
                      "baseline_id",
                      <code key="b">{String(baseline.baseline_id)}</code>,
                    ],
                    [
                      "source experiment",
                      <code key="se">{String(baseline.experiment_id)}</code>,
                    ],
                    [
                      "suite",
                      `${baseline.suite_id} @ ${baseline.suite_version}`,
                    ],
                    [
                      "suite_hash",
                      <code key="sh">{String(baseline.suite_hash || "—")}</code>,
                    ],
                    ["created_at", String(baseline.created_at || "—")],
                  ]}
                />
              )}
              <p className="muted small">
                Baseline promotion remains an explicit backend/CLI operation.
              </p>
            </Section>

            <Section title="Regression comparison">
              {!comparison ? (
                <EmptyState>No comparison available.</EmptyState>
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
                          <th>Status</th>
                        </tr>
                      </thead>
                      <tbody>
                        {(comparison.comparison.rows || []).map((row) => (
                          <tr key={row.metric}>
                            <td>
                              <code>{row.metric}</code>
                            </td>
                            <td>
                              {row.baseline == null
                                ? "—"
                                : String(row.baseline)}
                            </td>
                            <td>
                              {row.current == null
                                ? "—"
                                : String(row.current)}
                            </td>
                            <td>
                              {row.delta == null ? "—" : String(row.delta)}
                            </td>
                            <td>
                              {row.status ? (
                                <StatusBadge status={String(row.status)} />
                              ) : (
                                "—"
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <RawToggle data={comparison} />
                </>
              )}
            </Section>

            <Section title="Evaluation results">
              {results.length === 0 ? (
                <EmptyState>No case results.</EmptyState>
              ) : (
                <div className="table-scroll">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Case</th>
                        <th>Expected</th>
                        <th>Actual</th>
                        <th>Rule</th>
                        <th>Evidence</th>
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
                            <code>{c.expected_failure_code || "—"}</code>
                          </td>
                          <td>
                            <code>{c.predicted_failure_code || "—"}</code>
                          </td>
                          <td>
                            <code>{c.predicted_rule_id || "—"}</code>
                          </td>
                          <td>
                            {c.evidence_valid == null
                              ? "—"
                              : c.evidence_valid
                                ? "valid"
                                : "invalid"}
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
        </>
      )}
    </div>
  );
}
