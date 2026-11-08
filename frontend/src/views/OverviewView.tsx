import { useEffect, useMemo, useState } from "react";
import { apiGet } from "../api";
import {
  EmptyState,
  ErrorBanner,
  InfoDot,
  LoadingState,
  StatusBadge,
} from "../components/ui";
import { Stagger, StaggerItem } from "../components/motion";
import { IconArrowRight } from "../components/icons";
import { friendlyDiagnosis, type Severity } from "../taxonomy";
import type {
  DurableMetrics,
  ExperimentListItem,
  NavId,
  OpsSummaryV1,
} from "../types";

type Props = {
  apiKey: string;
  onNavigate: (nav: NavId) => void;
};

type HealthLevel = "ok" | "medium" | "high" | "unknown";

function pct(value: number | null | undefined, digits = 1): string {
  if (value == null || Number.isNaN(value)) return "—";
  return `${(value * 100).toFixed(digits)}%`;
}

function compactNumber(value: number | null | undefined): string {
  if (value == null) return "—";
  if (value < 1000) return String(value);
  if (value < 1_000_000) return `${(value / 1000).toFixed(value < 10000 ? 1 : 0)}k`;
  return `${(value / 1_000_000).toFixed(1)}M`;
}

function diagnosisCounts(counters: Record<string, number> | undefined) {
  const out: Array<{ code: string; count: number }> = [];
  if (!counters) return out;
  for (const [key, value] of Object.entries(counters)) {
    if (key.startsWith("diagnosis.code.") && value > 0) {
      out.push({ code: key.slice("diagnosis.code.".length), count: value });
    }
  }
  return out.sort((a, b) => b.count - a.count);
}

export function OverviewView({ apiKey, onNavigate }: Props) {
  const [ops, setOps] = useState<OpsSummaryV1 | null>(null);
  const [durable, setDurable] = useState<DurableMetrics | null>(null);
  const [experiments, setExperiments] = useState<ExperimentListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError("");
      try {
        const [opsBody, expBody] = await Promise.all([
          apiGet<OpsSummaryV1>("/api/v1/ops/summary", apiKey),
          apiGet<{ experiments: ExperimentListItem[] }>(
            "/api/v1/experiments?limit=6",
            apiKey,
          ).catch(() => ({ experiments: [] })),
        ]);
        // Durable counters power the failure breakdown; tolerate absence.
        const durableBody = await apiGet<DurableMetrics>(
          "/api/v1/metrics/durable?window_minutes=10080",
          apiKey,
        ).catch(() => null);
        if (cancelled) return;
        setOps(opsBody);
        setDurable(durableBody);
        setExperiments(expBody.experiments || []);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Unable to load overview");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [apiKey]);

  const codeCounts = useMemo(
    () => diagnosisCounts(durable?.counters),
    [durable],
  );

  const totals = useMemo(() => {
    const total = codeCounts.reduce((s, c) => s + c.count, 0);
    const healthy = codeCounts
      .filter((c) => friendlyDiagnosis(c.code).severity === "ok")
      .reduce((s, c) => s + c.count, 0);
    const needsAttention = codeCounts
      .filter((c) => friendlyDiagnosis(c.code).severity === "high")
      .reduce((s, c) => s + c.count, 0);
    return { total, healthy, needsAttention };
  }, [codeCounts]);

  const alerts =
    ops?.signals.signals.filter(
      (s) => s.status !== "OK" && s.status !== "INSUFFICIENT_DATA",
    ) ?? [];

  const health: { level: HealthLevel; headline: string; sub: string } =
    useMemo(() => {
      if (!ops) {
        return {
          level: "unknown",
          headline: "Checking system health…",
          sub: "Reading readiness and recent activity.",
        };
      }
      if (!ops.ready) {
        return {
          level: "high",
          headline: "A required service is not ready",
          sub: "One of the systems Retrace depends on (database or vector store) is unavailable. New executions may fail until it recovers.",
        };
      }
      if (alerts.length > 0) {
        return {
          level: "medium",
          headline: `${alerts.length} operational signal${alerts.length > 1 ? "s" : ""} need attention`,
          sub: "The service is running, but one or more monitored rates crossed its threshold. Review the signals below.",
        };
      }
      return {
        level: "ok",
        headline: "Your RAG system is healthy",
        sub: "All dependencies are ready and no operational signals are firing. This reflects service health, not the accuracy of any single answer — open an investigation to judge an individual response.",
      };
    }, [ops, alerts.length]);

  const dwin = ops?.metrics.durable_window;
  const generationAttempts =
    durable?.counters?.["generation.attempts"] ??
    dwin?.generation_attempts ??
    null;
  const p95 = dwin?.http_latency?.p95_ms ?? null;
  const errorRate = dwin?.request_error_rate ?? null;

  if (loading) {
    return (
      <div>
        <header className="page-header">
          <div>
            <h1 className="page-title">Overview</h1>
            <p className="page-desc">
              Is your RAG system healthy, and what should you look at?
            </p>
          </div>
        </header>
        <LoadingState label="Loading system overview…" />
      </div>
    );
  }

  return (
    <div>
      <header className="page-header">
        <div>
          <h1 className="page-title">Overview</h1>
          <p className="page-desc">
            Is your RAG system healthy, and what should you look at next?
          </p>
        </div>
        <div className="page-actions">
          <button type="button" onClick={() => onNavigate("investigate")}>
            Investigate an AI answer
          </button>
        </div>
      </header>

      <ErrorBanner message={error} />

      <Stagger className="overview">
        <StaggerItem>
          <section
            className={`overview-hero sev-${health.level === "unknown" ? "medium" : health.level}`}
            aria-label="System health summary"
          >
            <div className="overview-hero-text">
              <p className="diagnosis-kicker">System health</p>
              <h2 className="overview-headline">{health.headline}</h2>
              <p className="overview-sub">{health.sub}</p>
            </div>
            <div className="overview-hero-cta">
              <StatusBadge
                status={
                  health.level === "ok"
                    ? "Healthy"
                    : health.level === "high"
                      ? "Needs attention"
                      : health.level === "medium"
                        ? "Review signals"
                        : "Checking"
                }
                tone={
                  health.level === "ok"
                    ? "ok"
                    : health.level === "high"
                      ? "fail"
                      : "warn"
                }
              />
              <button
                type="button"
                className="secondary"
                onClick={() => onNavigate("operations")}
              >
                View operations
              </button>
            </div>
          </section>
        </StaggerItem>

        <StaggerItem>
          <div className="stat-row">
            <div className="stat">
              <span className="stat-k">
                Answers generated
                <InfoDot label="How many answers the system has produced (generation attempts recorded in telemetry). Not a measure of accuracy." />
              </span>
              <span className="stat-v tnum">
                {compactNumber(generationAttempts)}
              </span>
              <span className="stat-sub">Last 7 days of telemetry</span>
            </div>
            <div className="stat">
              <span className="stat-k">
                Diagnoses
                <InfoDot label="Executions that were analysed by the diagnosis engine and assigned a failure code." />
              </span>
              <span className="stat-v tnum">{compactNumber(totals.total)}</span>
              <span className="stat-sub">
                {totals.total > 0
                  ? `${pct(totals.healthy / totals.total, 0)} healthy`
                  : "No diagnoses yet"}
              </span>
            </div>
            <div className="stat">
              <span className="stat-k">
                Needs attention
                <InfoDot label="Diagnoses with a high-severity failure such as a wrong retrieval, a hallucination, or a contradiction." />
              </span>
              <span
                className={`stat-v tnum ${totals.needsAttention > 0 ? "err" : "ok"}`}
              >
                {compactNumber(totals.needsAttention)}
              </span>
              <span className="stat-sub">High-severity diagnoses</span>
            </div>
            <div className="stat">
              <span className="stat-k">
                Request errors
                <InfoDot label="Share of HTTP requests that returned a server error. This is service reliability, separate from answer quality." />
              </span>
              <span
                className={`stat-v tnum sm ${errorRate == null ? "" : errorRate > 0.02 ? "err" : "ok"}`}
              >
                {errorRate == null ? "Not available" : pct(errorRate, 2)}
              </span>
              <span className="stat-sub">
                {dwin?.requests_total != null
                  ? `${compactNumber(dwin.requests_total)} requests`
                  : "No data"}
              </span>
            </div>
            <div className="stat">
              <span className="stat-k">
                Response time (p95)
                <InfoDot label="95th-percentile request latency: 95% of requests were faster than this. Sourced from durable telemetry." />
              </span>
              <span className="stat-v tnum sm">
                {p95 == null ? "Not available" : `${Math.round(p95)} ms`}
              </span>
              <span className="stat-sub">Slowest 5% exceed this</span>
            </div>
          </div>
        </StaggerItem>

        <StaggerItem>
          <div className="overview-cols">
            <section className="panel">
              <h3>What is failing</h3>
              <p className="section-desc" style={{ marginBottom: "var(--space-4)" }}>
                Diagnoses grouped by cause, most common first. Each is written in
                plain language; healthy outcomes are excluded here.
              </p>
              {(() => {
                const failures = codeCounts.filter(
                  (c) => friendlyDiagnosis(c.code).severity !== "ok",
                );
                if (!durable) {
                  return (
                    <EmptyState compact>
                      Failure breakdown is not available.
                      <span className="empty-hint">
                        Durable telemetry did not return counters. It may be
                        disabled, or no diagnoses have been recorded yet.
                      </span>
                    </EmptyState>
                  );
                }
                if (failures.length === 0) {
                  return (
                    <EmptyState compact>
                      No failing diagnoses recorded.
                      <span className="empty-hint">
                        Every diagnosed execution in this window was healthy.
                      </span>
                    </EmptyState>
                  );
                }
                const max = failures[0].count;
                const sevClass: Record<Severity, string> = {
                  ok: "ok",
                  medium: "warn",
                  high: "err",
                  unknown: "",
                };
                return (
                  <ul className="breakdown-list">
                    {failures.slice(0, 7).map(({ code, count }) => {
                      const f = friendlyDiagnosis(code);
                      return (
                        <li key={code} className="breakdown-row">
                          <div className="breakdown-top">
                            <span className="breakdown-name">{f.title}</span>
                            <span className="breakdown-count tnum">{count}</span>
                          </div>
                          <div
                            className="breakdown-bar"
                            role="img"
                            aria-label={`${f.title}: ${count}`}
                          >
                            <div
                              className={`breakdown-fill ${sevClass[f.severity]}`}
                              style={{ width: `${Math.max(3, (count / max) * 100)}%` }}
                            />
                          </div>
                        </li>
                      );
                    })}
                  </ul>
                );
              })()}
            </section>

            <section className="panel">
              <h3>Recent evaluation runs</h3>
              <p className="section-desc" style={{ marginBottom: "var(--space-4)" }}>
                The latest reproducible test runs. Open one to see per-category
                results and compare it against the accepted baseline.
              </p>
              {experiments.length === 0 ? (
                <EmptyState compact>
                  No evaluation runs yet.
                  <span className="empty-hint">
                    Run a suite from Evaluations to populate this list.
                  </span>
                </EmptyState>
              ) : (
                <ul className="recent-list">
                  {experiments.slice(0, 5).map((e) => (
                    <li key={e.experiment_id}>
                      <button
                        type="button"
                        className="recent-item"
                        onClick={() => onNavigate("experiments")}
                      >
                        <span style={{ minWidth: 0 }}>
                          <span className="recent-title">
                            {e.suite_id || "suite"}{" "}
                            <span className="muted">
                              @ {e.suite_version || "—"}
                            </span>
                          </span>
                          <span className="recent-meta" style={{ display: "block" }}>
                            {e.created_at
                              ? new Date(e.created_at).toLocaleString()
                              : e.experiment_id.slice(0, 8)}
                          </span>
                        </span>
                        <StatusBadge status={e.status} />
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </div>
        </StaggerItem>

        <StaggerItem>
          <section className="panel">
            <div className="inline spread" style={{ marginBottom: "var(--space-3)" }}>
              <h3 style={{ margin: 0 }}>Signals needing attention</h3>
              <button
                type="button"
                className="linkish"
                onClick={() => onNavigate("operations")}
              >
                Open operations <IconArrowRight aria-hidden />
              </button>
            </div>
            {alerts.length === 0 ? (
              <p className="muted small" style={{ margin: 0 }}>
                No operational signals are firing. Monitored rates (request
                errors, retrieval misses, judge problems) are within their
                thresholds, or there is not yet enough data to evaluate them.
              </p>
            ) : (
              <ul className="recent-list">
                {alerts.map((s) => (
                  <li key={s.signal}>
                    <div className="recent-item" style={{ cursor: "default" }}>
                      <span style={{ minWidth: 0 }}>
                        <span className="recent-title">{s.signal}</span>
                        {s.description ? (
                          <span className="recent-meta" style={{ display: "block" }}>
                            {s.description}
                          </span>
                        ) : null}
                      </span>
                      <StatusBadge status={s.status} />
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </StaggerItem>
      </Stagger>
    </div>
  );
}
