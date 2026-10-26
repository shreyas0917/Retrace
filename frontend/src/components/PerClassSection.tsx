import { EmptyState, Section } from "./ui";
import type { PerClassMetric, SelectiveMetrics } from "../types";

type Props = {
  perClass?: Record<string, PerClassMetric> | null;
  selective?: SelectiveMetrics | null;
};

function f3(v: number | null | undefined): string {
  return v == null ? "—" : Number(v).toFixed(3);
}

function pct(v: number | null | undefined): string {
  return v == null ? "—" : `${Math.round(Number(v) * 100)}%`;
}

/** Per-failure-class precision / recall / F1 plus selective-prediction summary. */
export function PerClassSection({ perClass, selective }: Props) {
  const rows = Object.entries(perClass || {}).sort(([a], [b]) =>
    a.localeCompare(b),
  );
  return (
    <Section title="Per-class precision / recall / F1">
      {selective && (
        <p className="muted small" style={{ marginTop: 0 }}>
          Coverage {pct(selective.coverage)} · selective accuracy{" "}
          {pct(selective.selective_accuracy)} on answered cases ·{" "}
          {selective.deferred} deferred as uncertain
          {selective.deferred_accuracy != null
            ? ` (${pct(selective.deferred_accuracy)} of those would have been right)`
            : ""}
          .
        </p>
      )}
      {rows.length === 0 ? (
        <EmptyState>
          No per-class metrics stored for this experiment (runs before v1.0).
        </EmptyState>
      ) : (
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th>Expected label</th>
                <th className="num">Support</th>
                <th className="num">Precision</th>
                <th className="num">Recall</th>
                <th className="num">F1</th>
                <th className="num">FP</th>
                <th className="num">FN</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(([label, m]) => (
                <tr key={label}>
                  <td>
                    <code>{label}</code>
                  </td>
                  <td className="num">{m.support}</td>
                  <td className="num">{f3(m.precision)}</td>
                  <td className="num">{f3(m.recall)}</td>
                  <td className="num">{f3(m.f1)}</td>
                  <td className="num">{m.fp}</td>
                  <td className="num">{m.fn}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Section>
  );
}
