import { useMemo, useState, type ReactNode } from "react";
import { Bar, EmptyState, RawToggle, StatusBadge, Tip } from "./ui";
import {
  failureTitle,
  friendlyDiagnosis,
  metricLabel,
  statusLabel,
  suiteLabel,
} from "../labels";
import {
  caseFailed,
  decimal,
  exitMeaning,
  filterCases,
  formatDelta,
  formatMetricValue,
  isNum,
  pct,
  type Verdict,
} from "../format";
import type { CaseResult, Comparison, PerClassMetric, SelectiveMetrics } from "../types";

export const F1_CALLOUT = 0.9;

export function VerdictBanner({
  verdict,
  context,
}: {
  verdict: Verdict;
  context?: ReactNode;
}) {
  const tone =
    verdict.kind === "pass" ? "ok" : verdict.kind === "regression" ? "warn" : verdict.kind === "error" ? "fail" : "neutral";
  return (
    <section className={`gate-banner gate-${tone}`} aria-label="Evaluation verdict" role="status">
      <div className="gate-main">
        <p className="diagnosis-kicker">Verdict</p>
        <h2 className="gate-title">{verdict.title}</h2>
        <p className="gate-detail">{verdict.detail}</p>
        {context ? <div className="gate-context">{context}</div> : null}
      </div>
      <div className="gate-exit">
        <span className="gate-exit-k">Exit code</span>
        <span className="gate-exit-v tnum">{verdict.exitCode ?? "—"}</span>
        {verdict.exitCode != null ? (
          <span className="gate-exit-sub">
            {exitMeaning(verdict.exitCode)}
            {verdict.derived ? " (derived from the stored comparison)" : ""}
          </span>
        ) : null}
      </div>
    </section>
  );
}

const TILE_KEYS = [
  "total_cases",
  "failure_code_accuracy",
  "rule_accuracy",
  "evidence_accuracy",
  "strict_accuracy",
  "macro_f1",
] as const;

export function MetricTiles({ summary }: { summary: Record<string, unknown> }) {
  return (
    <div className="tile-row" role="list" aria-label="Headline metrics">
      {TILE_KEYS.map((k) => {
        const m = metricLabel(k);
        const v = summary[k] ?? (k === "total_cases" ? summary.n : undefined);
        const text = k === "total_cases" ? (isNum(v) ? String(v) : "—") : formatMetricValue(k, v);
        return (
          <div className="tile" role="listitem" key={k}>
            <span className="tile-k">
              {m.label} <Tip text={m.help} />
            </span>
            <span className="tile-v tnum">{text}</span>
            {k === "total_cases" && isNum(summary.correct) && isNum(summary.incorrect) ? (
              <span className="tile-sub">
                {summary.correct} correct · {summary.incorrect} incorrect
              </span>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

export function PerClassF1({
  perClass,
  selective,
}: {
  perClass?: Record<string, PerClassMetric> | null;
  selective?: SelectiveMetrics | null;
}) {
  const rows = Object.entries(perClass || {}).sort(
    ([a, ma], [b, mb]) => (ma.f1 ?? 0) - (mb.f1 ?? 0) || a.localeCompare(b),
  );
  const weak = rows.filter(([, m]) => isNum(m.f1) && m.f1 < F1_CALLOUT);
  return (
    <section className="report-card" aria-labelledby="perclass-title">
      <div className="report-card-head">
        <div>
          <h2 className="report-card-title" id="perclass-title">
            F1 by failure class
          </h2>
          <p className="section-desc">Weakest first. F1 balances precision and recall for each expected label.</p>
        </div>
      </div>
      {rows.length === 0 ? (
        <EmptyState compact>No per-class metrics stored for this experiment (runs before v1.0).</EmptyState>
      ) : (
        <>
          <ul className="f1-list">
            {rows.map(([label, m]) => {
              const low = isNum(m.f1) && m.f1 < F1_CALLOUT;
              return (
                <li key={label} className={low ? "f1-row low" : "f1-row"}>
                  <span className="f1-name">
                    <span>{friendlyDiagnosis(label).title}</span>
                    <code className="muted">{label}</code>
                  </span>
                  <Bar
                    value={m.f1}
                    tone={low ? "warn" : "ok"}
                    label={`${label} F1 ${decimal(m.f1)}`}
                    marker={F1_CALLOUT}
                  />
                  <span className="f1-v tnum">{decimal(m.f1)}</span>
                  <span className="f1-meta muted small tnum">
                    P {decimal(m.precision, 2)} · R {decimal(m.recall, 2)} · n={m.support}
                  </span>
                </li>
              );
            })}
          </ul>
          {weak.length ? (
            <p className="callout" role="note">
              <strong>
                {weak.length} class{weak.length > 1 ? "es" : ""} below {F1_CALLOUT} F1:
              </strong>{" "}
              {weak.map(([l]) => failureTitle(l)).join("; ")}. Open the failing cases below to see why.
            </p>
          ) : (
            <p className="muted small">Every class is at or above {F1_CALLOUT} F1.</p>
          )}
        </>
      )}
      {selective ? (
        <p className="muted small selective-line">
          Coverage {pct(selective.coverage, 0)} · selective accuracy {pct(selective.selective_accuracy, 0)} on
          answered cases · {selective.deferred} deferred as uncertain
          {selective.deferred_accuracy != null
            ? ` (${pct(selective.deferred_accuracy, 0)} of those would have been right)`
            : ""}
          .
        </p>
      ) : null}
    </section>
  );
}

export function ComparisonTable({ comparison }: { comparison: Comparison | null }) {
  return (
    <section className="report-card" aria-labelledby="cmp-title">
      <div className="report-card-head">
        <div>
          <h2 className="report-card-title" id="cmp-title">
            Against the baseline
          </h2>
          <p className="section-desc">Accuracy changes in percentage points (pp); F1 changes as decimals.</p>
        </div>
      </div>
      {!comparison ? (
        <EmptyState compact>No comparison available.</EmptyState>
      ) : !comparison.comparison.has_baseline ? (
        <EmptyState compact hint="Promote a run with the CLI (retrace baseline promote) to compare against it.">
          No accepted baseline for this suite and version.
        </EmptyState>
      ) : (
        <div className="table-scroll" role="region" aria-label="Baseline comparison" tabIndex={0}>
          <table className="data-table cmp-table">
            <thead>
              <tr>
                <th>Metric</th>
                <th className="num">Baseline</th>
                <th className="num">This run</th>
                <th className="num">Change</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {(comparison.comparison.rows || []).map((row) => {
                const d = row.delta;
                const dir = isNum(d) && Math.abs(d) > 1e-12 ? (d > 0 ? "up" : "down") : "flat";
                return (
                  <tr key={row.metric}>
                    <td>
                      <span className="cmp-metric">{metricLabel(row.metric).label}</span>
                      <code className="muted">{row.metric}</code>
                    </td>
                    <td className="num">{formatMetricValue(row.metric, row.baseline)}</td>
                    <td className="num">{formatMetricValue(row.metric, row.current)}</td>
                    <td className={`num delta-${dir}`}>{formatDelta(row.metric, d)}</td>
                    <td>
                      {row.status ? <StatusBadge status={String(row.status)} label={statusLabel(String(row.status))} tone={row.status === "FAIL" ? "fail" : row.status === "IMPROVED" ? "ok" : "neutral"} /> : "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {comparison?.comparison.violations?.length ? (
        <ul className="violations">
          {comparison.comparison.violations.map((v, i) => (
            <li key={i}>
              <code>{String(v)}</code>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

function CodeCell({ code }: { code: string | null }) {
  if (!code) return <span className="muted">—</span>;
  return (
    <span className="code-cell">
      <span>{failureTitle(code)}</span>
      <code className="muted">{code}</code>
    </span>
  );
}

export function CaseTable({
  cases,
  onOpenExecution,
}: {
  cases: CaseResult[];
  onOpenExecution: (id: string) => void;
}) {
  const [query, setQuery] = useState("");
  const [onlyFailures, setOnlyFailures] = useState(false);
  const shown = useMemo(() => filterCases(cases, query, onlyFailures), [cases, query, onlyFailures]);
  const failures = cases.filter(caseFailed).length;
  return (
    <section className="report-card" aria-labelledby="cases-title">
      <div className="report-card-head">
        <div>
          <h2 className="report-card-title" id="cases-title">
            Cases
          </h2>
          <p className="section-desc">
            Failures first. {failures} of {cases.length} case{cases.length === 1 ? "" : "s"} failed.
          </p>
        </div>
      </div>
      {cases.length === 0 ? (
        <EmptyState compact>No case results.</EmptyState>
      ) : (
        <>
          <div className="case-filters">
            <label className="case-search">
              Search cases
              <input
                type="search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Case id, question, failure code or title"
              />
            </label>
            <label className="check">
              <input type="checkbox" checked={onlyFailures} onChange={(e) => setOnlyFailures(e.target.checked)} />
              Failures only
            </label>
            <span className="muted small" aria-live="polite">
              {shown.length} shown
            </span>
          </div>
          <div className="table-scroll" role="region" aria-label="Case results" tabIndex={0}>
            <table className="data-table case-table">
              <thead>
                <tr>
                  <th>Result</th>
                  <th>Case</th>
                  <th>Expected</th>
                  <th>Predicted</th>
                  <th>Rule</th>
                  <th>
                    <span className="sr-only">Investigate</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {shown.map((c) => {
                  const failed = caseFailed(c);
                  return (
                    <tr key={c.case_id} className={failed ? "case-failed" : undefined}>
                      <td>
                        <StatusBadge status={failed ? "FAIL" : "PASS"} label={failed ? "Fail" : "Pass"} tone={failed ? "fail" : "ok"} />
                      </td>
                      <td>
                        <code>{c.case_id}</code>
                        {c.query ? <span className="case-query muted small">{c.query}</span> : null}
                        {c.error ? <span className="case-query error-text small">{c.error}</span> : null}
                      </td>
                      <td>
                        <CodeCell code={c.expected_failure_code} />
                      </td>
                      <td>
                        <CodeCell code={c.predicted_failure_code} />
                      </td>
                      <td className="nowrap">
                        <code>{c.predicted_rule_id || "—"}</code>
                        {c.expected_rule_id && c.expected_rule_id !== c.predicted_rule_id ? (
                          <span className="muted small"> (expected {c.expected_rule_id})</span>
                        ) : null}
                      </td>
                      <td className="nowrap">
                        {c.execution_id ? (
                          <button
                            type="button"
                            className="linkish"
                            onClick={() => onOpenExecution(c.execution_id!)}
                            aria-label={`Investigate case ${c.case_id}`}
                          >
                            Investigate →
                          </button>
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
          {shown.length === 0 ? <p className="muted small">No case matches this search.</p> : null}
        </>
      )}
    </section>
  );
}

export function RunDetails({
  rows,
  raw,
}: {
  rows: Array<[string, ReactNode]>;
  raw?: unknown;
}) {
  return (
    <details className="disclosure">
      <summary>Run details</summary>
      <div className="disclosure-body">
        <dl className="details-grid">
          {rows.map(([k, v]) => (
            <div className="details-item" key={k}>
              <dt>{k}</dt>
              <dd>{v}</dd>
            </div>
          ))}
        </dl>
        {raw !== undefined ? <RawToggle label="Raw run JSON" data={raw} /> : null}
      </div>
    </details>
  );
}

export function SuiteName({ id, version }: { id: string | null | undefined; version?: string | null }) {
  return (
    <span className="suite-name">
      {suiteLabel(id)} <code className="muted">{id || "—"}</code>
      {version ? <span className="muted"> v{version}</span> : null}
    </span>
  );
}
