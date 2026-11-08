import { useEffect, useState } from "react";
import { apiGet } from "../api";
import {
  EmptyState,
  ErrorBanner,
  LoadingState,
  PageHeader,
  RawToggle,
  StatusBadge,
  Tip,
  Bar,
} from "../components/ui";
import { RunbookDisclosure } from "../components/Runbook";
import { opsSignalLabel, statusLabel } from "../labels";
import type { DurableWindow, OpsSummaryV1 } from "../types";

type Props = {
  apiKey: string;
};

const WINDOWS: Array<{ label: string; minutes: number }> = [
  { label: "1h", minutes: 60 },
  { label: "24h", minutes: 1440 },
  { label: "7d", minutes: 10080 },
];

function signalTone(
  status: string,
): "ok" | "fail" | "warn" | "neutral" {
  if (status === "OK") return "ok";
  if (status === "ALERT") return "fail";
  if (status === "INSUFFICIENT_DATA") return "neutral";
  return "neutral";
}

/** Show real zeros; only "No data" when the counter key is absent. */
function counterValue(
  counters: Record<string, number>,
  key: string,
): { text: string; missing: boolean } {
  if (!(key in counters) || counters[key] == null) {
    return { text: "No data", missing: true };
  }
  return { text: String(counters[key]), missing: false };
}

function ms(value: number | null | undefined): string {
  return value == null ? "No data" : `${value} ms`;
}

function pct(value: number | null | undefined): string {
  return value == null ? "No data" : `${(Number(value) * 100).toFixed(2)}%`;
}

function tokens(value: number | null | undefined): string {
  return value == null ? "No data" : Number(value).toLocaleString();
}

function usd(value: number | null | undefined): string {
  if (value == null) return "No data";
  const n = Number(value);
  if (n === 0) return "$0.00";
  if (n < 0.01) return `$${n.toFixed(6)}`;
  return `$${n.toFixed(4)}`;
}

function DurablePanel({
  window,
  windowMinutes,
  onWindowChange,
  inMemorySource,
}: {
  window: DurableWindow | undefined;
  windowMinutes: number;
  onWindowChange: (minutes: number) => void;
  inMemorySource: string;
}) {
  const available = Boolean(window?.available);
  const http = window?.http_latency || {};
  const tok = window?.tokens || {};
  return (
    <section className="report-card" aria-labelledby="telemetry-title">
      <div
        className="inline"
        style={{ justifyContent: "space-between", alignItems: "baseline" }}
      >
        <h2 className="report-card-title" id="telemetry-title">Telemetry window</h2>
        <div className="inline" role="group" aria-label="Telemetry window">
          {WINDOWS.map((w) => (
            <button
              key={w.minutes}
              type="button"
              className={w.minutes === windowMinutes ? "" : "secondary"}
              aria-pressed={w.minutes === windowMinutes}
              onClick={() => onWindowChange(w.minutes)}
            >
              {w.label}
            </button>
          ))}
        </div>
      </div>
      <p className="muted small" style={{ margin: "6px 0 12px" }}>
        {available ? (
          <>
            source: {window?.source || "postgres"} — durable across restarts
            and shared across workers ({tokens(window?.event_count)} events in
            window). Live counters below are source: {inMemorySource} (per
            process).
          </>
        ) : (
          <>
            source: {inMemorySource} only — durable store unavailable
            {window?.reason ? ` (${window.reason})` : ""}. Values reset on
            process restart.
          </>
        )}
      </p>
      <div className="metric-strip">
        <div className="metric-cell">
          <div className="metric-label">p50 latency</div>
          <div className={http.p50_ms == null ? "metric-value muted" : "metric-value"}>
            {ms(http.p50_ms)}
          </div>
        </div>
        <div className="metric-cell">
          <div className="metric-label">p95 latency</div>
          <div className={http.p95_ms == null ? "metric-value muted" : "metric-value"}>
            {ms(http.p95_ms)}
          </div>
        </div>
        <div className="metric-cell">
          <div className="metric-label">p99 latency</div>
          <div className={http.p99_ms == null ? "metric-value muted" : "metric-value"}>
            {ms(http.p99_ms)}
          </div>
        </div>
        <div className="metric-cell">
          <div className="metric-label">Error rate</div>
          <div
            className={
              window?.request_error_rate == null
                ? "metric-value muted"
                : "metric-value"
            }
          >
            {pct(window?.request_error_rate)}
          </div>
        </div>
        <div className="metric-cell">
          <div className="metric-label">Tokens (prompt / completion)</div>
          <div className={available ? "metric-value" : "metric-value muted"}>
            {available
              ? `${tokens(tok.prompt ?? 0)} / ${tokens(tok.completion ?? 0)}`
              : "No data"}
          </div>
        </div>
        <div className="metric-cell">
          <div className="metric-label">Estimated cost</div>
          <div
            className={window?.cost_usd == null ? "metric-value muted" : "metric-value"}
          >
            {usd(window?.cost_usd)}
          </div>
        </div>
      </div>
      {available && (
        <p className="muted small" style={{ marginTop: 10, marginBottom: 0 }}>
          {tokens(window?.requests_total)} requests, {tokens(window?.requests_5xx)}{" "}
          5xx, {tokens(window?.llm_retries)} LLM retries,{" "}
          {tokens(window?.llm_failures)} LLM failures. Cost is an estimate from
          configs/pricing.yaml (illustrative rates), not a bill.
        </p>
      )}
    </section>
  );
}

type Signal = OpsSummaryV1["signals"]["signals"][number];

const SIGNAL_ORDER: Record<string, number> = { ALERT: 0, OK: 1, INSUFFICIENT_DATA: 2 };

/** Alerts first, then OK, then not-enough-data; stable by name. */
export function sortSignals(signals: Signal[]): Signal[] {
  return [...signals].sort(
    (a, b) =>
      (SIGNAL_ORDER[a.status] ?? 1.5) - (SIGNAL_ORDER[b.status] ?? 1.5) ||
      a.signal.localeCompare(b.signal),
  );
}

function formatSignalNumber(value: number | null | undefined, unit: "rate" | "ms"): string {
  if (value == null || !Number.isFinite(value)) return "—";
  if (unit === "ms") return `${Math.round(value)} ms`;
  return `${(value * 100).toFixed(value < 0.1 ? 2 : 1)}%`;
}

function SignalRow({ s, runbook }: { s: Signal; runbook?: string }) {
  const meta = opsSignalLabel(s.signal);
  const insufficient = s.status === "INSUFFICIENT_DATA" || s.actual == null;
  const scale = Math.max(s.threshold * 2, s.actual ?? 0) || 1;
  const alert = s.status === "ALERT";
  return (
    <li className={`signal-row ${alert ? "alert" : insufficient ? "nodata" : "ok"}`}>
      <div className="signal-row-head">
        <span className="signal-name">
          <span className="signal-title">
            {meta.label} <Tip text={s.description || meta.help} />
          </span>
          <code className="muted">{s.signal}</code>
        </span>
        <span className="signal-status">
          <StatusBadge status={s.status} label={statusLabel(s.status)} tone={signalTone(s.status)} />
          {statusLabel(s.status) !== s.status ? <code className="muted small">{s.status}</code> : null}
        </span>
      </div>
      <div className="signal-meter">
        {insufficient ? (
          <span className="muted small">Not enough observations yet; this is not the same as zero.</span>
        ) : (
          <>
            <Bar
              value={(s.actual ?? 0) / scale}
              marker={s.threshold / scale}
              tone={alert ? "err" : "ok"}
              label={`${meta.label}: ${formatSignalNumber(s.actual, meta.unit)} against threshold ${formatSignalNumber(s.threshold, meta.unit)}`}
            />
            <span className="signal-values tnum small">
              <strong>{formatSignalNumber(s.actual, meta.unit)}</strong>
              <span className="muted"> / threshold {formatSignalNumber(s.threshold, meta.unit)}</span>
            </span>
          </>
        )}
      </div>
      {runbook ? <RunbookDisclosure slug={runbook} label="Runbook" /> : null}
    </li>
  );
}

export function OperationsView({ apiKey: _apiKey }: Props) {
  const [ops, setOps] = useState<OpsSummaryV1 | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [runbookMap, setRunbookMap] = useState<Record<string, string>>({});
  const [windowMinutes, setWindowMinutes] = useState(1440);

  async function refresh(minutes: number = windowMinutes) {
    setLoading(true);
    setError("");
    try {
      const body = await apiGet<OpsSummaryV1>(`/api/v1/ops/summary?window_minutes=${minutes}`);
      setOps(body);
      try {
        const books = await apiGet<{ by_signal: Record<string, string> }>("/api/v1/runbooks");
        setRunbookMap(books?.by_signal || {});
      } catch {
        setRunbookMap({});
      }
    } catch (err) {
      setOps(null);
      setError(err instanceof Error ? err.message : "Unable to load ops summary");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void refresh(windowMinutes);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [windowMinutes]);

  const deps = (ops?.dependencies || {}) as Record<string, unknown>;
  const counters = ops?.metrics.counters_sample || {};
  const requests = counterValue(counters, "http.requests_total");
  const errors = counterValue(counters, "http.requests_5xx");
  const diagnoses = counterValue(counters, "diagnosis.total");
  const retrievalEmpty = counterValue(counters, "retrieval.empty");
  const judgeMalformed = counterValue(counters, "judge.malformed");
  const p95 = ops?.metrics.http_latency?.p95_ms;
  const inMemorySource = ops?.metrics.source || "in-memory";
  const signals = sortSignals(ops?.signals.signals || []);
  const alerts = signals.filter((s) => s.status === "ALERT");
  const noData = signals.filter((s) => s.status === "INSUFFICIENT_DATA" || s.actual == null);
  const depOk = (v: unknown) => String(v).toLowerCase() === "ok";

  const health = !ops
    ? null
    : !ops.ready
      ? {
          tone: "fail",
          title: "Not ready",
          detail:
            "A required dependency is unavailable. New executions may fail until it recovers.",
        }
      : alerts.length
        ? {
            tone: "warn",
            title: `${alerts.length} signal${alerts.length > 1 ? "s" : ""} alerting`,
            detail: "The service is up, but a monitored rate is past its threshold. Alerts are listed first below.",
          }
        : {
            tone: "ok",
            title: "Healthy",
            detail: "Dependencies are ready and no signal is past its threshold.",
          };

  return (
    <div>
      <PageHeader
        title="Operations"
        description="Service health, durable telemetry, alert signals and their runbooks."
        actions={
          <button type="button" className="secondary" disabled={loading} onClick={() => void refresh()}>
            Refresh
          </button>
        }
      />
      <ErrorBanner message={error} />
      {loading && !ops && <LoadingState label="Loading operations…" />}
      {!loading && !ops && <EmptyState>Unable to load operations.</EmptyState>}

      {ops && health && (
        <div className="eval-stack">
          <section className={`gate-banner gate-${health.tone}`} aria-label="Service health" role="status">
            <div className="gate-main">
              <p className="diagnosis-kicker">Service health</p>
              <h2 className="gate-title">{health.title}</h2>
              <p className="gate-detail">
                {health.detail}
                {noData.length
                  ? ` ${noData.length} signal${noData.length > 1 ? "s have" : " has"} too little data to judge.`
                  : ""}
              </p>
            </div>
            <ul className="dep-list" aria-label="Dependencies">
              {[
                ["PostgreSQL", deps.postgres],
                ["Chroma", deps.chroma],
              ].map(([name, v]) => (
                <li key={String(name)}>
                  <span className={depOk(v) ? "status-dot ok" : "status-dot error"}>{String(name)}</span>
                  <span className="muted small">{depOk(v) ? "Ready" : v == null ? "Unknown" : String(v)}</span>
                </li>
              ))}
              {deps.embedding_model ? (
                <li>
                  <span>Embedding model</span>
                  <span className="muted small">{String(deps.embedding_model)}</span>
                </li>
              ) : null}
            </ul>
          </section>

          <section className="report-card" aria-labelledby="signals-title">
            <div className="report-card-head">
              <div>
                <h2 className="report-card-title" id="signals-title">
                  Signals
                </h2>
                <p className="section-desc">
                  Actual value against its threshold (the dark marker). Alerts first.
                </p>
              </div>
            </div>
            {signals.length === 0 ? (
              <EmptyState compact>No signals configured.</EmptyState>
            ) : (
              <ul className="signal-list">
                {signals.map((s) => (
                  <SignalRow key={s.signal} s={s} runbook={runbookMap[s.signal]} />
                ))}
              </ul>
            )}
            {ops.signals.metrics_note ? <p className="muted small">{ops.signals.metrics_note}</p> : null}
          </section>

          <DurablePanel
            window={ops.metrics.durable_window}
            windowMinutes={windowMinutes}
            onWindowChange={setWindowMinutes}
            inMemorySource={inMemorySource}
          />

          <section className="report-card" aria-labelledby="counters-title">
            <div className="report-card-head">
              <div>
                <h2 className="report-card-title" id="counters-title">
                  Live process counters
                </h2>
                <p className="section-desc">Source: {inMemorySource}, since the last restart of this process.</p>
              </div>
            </div>
            <div className="metric-strip flush">
              {[
                ["Requests", requests.text, requests.missing],
                ["Server errors", errors.text, errors.missing],
                ["p95 latency", p95 != null ? `${p95} ms` : "No data", p95 == null],
                ["Diagnoses", diagnoses.text, diagnoses.missing],
                ["Empty retrievals", retrievalEmpty.text, retrievalEmpty.missing],
                ["Malformed judge outputs", judgeMalformed.text, judgeMalformed.missing],
              ].map(([label, text, missing]) => (
                <div className="metric-cell" key={String(label)}>
                  <div className="metric-label">{String(label)}</div>
                  <div className={missing ? "metric-value muted" : "metric-value"}>{String(text)}</div>
                </div>
              ))}
            </div>
          </section>

          <RawToggle label="View raw ops summary" data={ops} />
        </div>
      )}
    </div>
  );
}
