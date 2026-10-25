import { useEffect, useState } from "react";
import { apiGet, apiGetText } from "../api";
import {
  EmptyState,
  ErrorBanner,
  LoadingState,
  PageHeader,
  RawToggle,
  Section,
  StatusBadge,
} from "../components/ui";
import type { OpsSummary } from "../types";

type Props = {
  apiKey: string;
};

function signalTone(
  status: string,
): "ok" | "fail" | "warn" | "neutral" {
  if (status === "OK") return "ok";
  if (status === "ALERT") return "fail";
  if (status === "INSUFFICIENT_DATA") return "neutral";
  return "neutral";
}

function formatActual(actual: number | null | undefined, status: string) {
  if (actual == null || status === "INSUFFICIENT_DATA") {
    return "INSUFFICIENT DATA";
  }
  return Number(actual).toFixed(3);
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

export function OperationsView({ apiKey: _apiKey }: Props) {
  const [ops, setOps] = useState<OpsSummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [runbook, setRunbook] = useState("");
  const [runbookMap, setRunbookMap] = useState<Record<string, string>>({});

  async function refresh() {
    setLoading(true);
    setError("");
    try {
      const body = await apiGet<OpsSummary>("/api/v1/ops/summary");
      setOps(body);
      const books = await apiGet<{
        by_signal: Record<string, string>;
      }>("/api/v1/runbooks");
      setRunbookMap(books.by_signal || {});
    } catch (err) {
      setOps(null);
      setError(err instanceof Error ? err.message : "Unable to load ops summary");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  async function openRunbook(slug: string) {
    try {
      const text = await apiGetText(`/api/v1/runbooks/${slug}`);
      setRunbook(text);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load runbook");
    }
  }

  const deps = (ops?.dependencies || {}) as Record<string, unknown>;
  const counters = ops?.metrics.counters_sample || {};
  const requests = counterValue(counters, "http.requests_total");
  const errors = counterValue(counters, "http.requests_5xx");
  const diagnoses = counterValue(counters, "diagnosis.total");
  const retrievalEmpty = counterValue(counters, "retrieval.empty");
  const judgeMalformed = counterValue(counters, "judge.malformed");
  const p95 = ops?.metrics.http_latency?.p95_ms;

  return (
    <div>
      <PageHeader
        eyebrow="Operations"
        title="Operations"
        description="System health, metrics, signals, and runbooks."
        actions={
          <button
            type="button"
            className="secondary"
            disabled={loading}
            onClick={() => void refresh()}
          >
            Refresh
          </button>
        }
      />
      <p className="muted small" style={{ marginTop: -8, marginBottom: 16 }}>
        In-memory metrics — reset on process restart. Not durable production
        telemetry.
      </p>
      <ErrorBanner message={error} />
      {loading && !ops && <LoadingState label="Loading operations…" />}
      {!loading && !ops && <EmptyState>Unable to load operations.</EmptyState>}

      {ops && (
        <>
          <div className="panel tight" style={{ marginBottom: 16 }}>
            <h2>System health</h2>
            <div className="inline" style={{ margin: "8px 0 12px" }}>
              <StatusBadge
                status={ops.ready ? "READY" : "NOT_READY"}
                tone={ops.ready ? "ok" : "fail"}
              />
            </div>
            <div className="meta-grid">
              <div className="meta-item">
                <span className="meta-k">PostgreSQL</span>
                <span className="meta-v">
                  <span
                    className={
                      String(deps.postgres).toLowerCase() === "ok"
                        ? "status-dot ok"
                        : "status-dot error"
                    }
                  >
                    {String(deps.postgres ?? "—")}
                  </span>
                </span>
              </div>
              <div className="meta-item">
                <span className="meta-k">Chroma</span>
                <span className="meta-v">
                  <span
                    className={
                      String(deps.chroma).toLowerCase() === "ok"
                        ? "status-dot ok"
                        : "status-dot error"
                    }
                  >
                    {String(deps.chroma ?? "—")}
                  </span>
                </span>
              </div>
              <div className="meta-item">
                <span className="meta-k">Embedding model</span>
                <span className="meta-v">
                  {String(deps.embedding_model ?? "—")}
                </span>
              </div>
            </div>
          </div>

          <div className="metric-strip">
            <div className="metric-cell">
              <div className="metric-label">Requests</div>
              <div className={requests.missing ? "metric-value muted" : "metric-value"}>
                {requests.text}
              </div>
            </div>
            <div className="metric-cell">
              <div className="metric-label">Errors</div>
              <div className={errors.missing ? "metric-value muted" : "metric-value"}>
                {errors.text}
              </div>
            </div>
            <div className="metric-cell">
              <div className="metric-label">P95</div>
              <div className={p95 == null ? "metric-value muted" : "metric-value"}>
                {p95 != null ? `${p95} ms` : "No data"}
              </div>
            </div>
            <div className="metric-cell">
              <div className="metric-label">Diagnoses</div>
              <div className={diagnoses.missing ? "metric-value muted" : "metric-value"}>
                {diagnoses.text}
              </div>
            </div>
            <div className="metric-cell">
              <div className="metric-label">Retrieval empty</div>
              <div
                className={
                  retrievalEmpty.missing ? "metric-value muted" : "metric-value"
                }
              >
                {retrievalEmpty.text}
              </div>
            </div>
            <div className="metric-cell">
              <div className="metric-label">Judge malformed</div>
              <div
                className={
                  judgeMalformed.missing ? "metric-value muted" : "metric-value"
                }
              >
                {judgeMalformed.text}
              </div>
            </div>
          </div>

          <div className="panel tight">
            <Section title="Signals">
              {ops.signals.signals.length === 0 ? (
                <EmptyState>No signals configured.</EmptyState>
              ) : (
                <div className="table-scroll">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Signal</th>
                        <th>Actual</th>
                        <th className="num">Threshold</th>
                        <th>Status</th>
                        <th>Runbook</th>
                      </tr>
                    </thead>
                    <tbody>
                      {ops.signals.signals.map((s) => {
                        const insufficient =
                          s.status === "INSUFFICIENT_DATA" || s.actual == null;
                        return (
                          <tr key={s.signal}>
                            <td>
                              <code>{s.signal}</code>
                            </td>
                            <td>
                              {insufficient ? (
                                <span className="muted">INSUFFICIENT DATA</span>
                              ) : (
                                <span className="mono">
                                  {formatActual(s.actual, s.status)}
                                </span>
                              )}
                            </td>
                            <td className="num">{s.threshold}</td>
                            <td>
                              <StatusBadge
                                status={s.status}
                                tone={signalTone(s.status)}
                              />
                            </td>
                            <td>
                              {runbookMap[s.signal] ? (
                                <button
                                  type="button"
                                  className="secondary"
                                  onClick={() =>
                                    void openRunbook(runbookMap[s.signal])
                                  }
                                >
                                  Runbook
                                </button>
                              ) : (
                                "—"
                              )}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
              {ops.signals.signals.some(
                (s) => s.status === "INSUFFICIENT_DATA",
              ) && (
                <p className="muted small" style={{ marginTop: 12 }}>
                  INSUFFICIENT_DATA means not enough observations yet — not
                  zero.
                </p>
              )}
            </Section>

            {runbook && (
              <Section title="Runbook">
                <pre className="runbook">{runbook}</pre>
              </Section>
            )}

            <RawToggle label="View raw ops summary" data={ops} />
          </div>
        </>
      )}
    </div>
  );
}
