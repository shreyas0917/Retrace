import type { ReactNode } from "react";

export type Tone = "ok" | "alert" | "warn" | "neutral" | "fail" | "pass" | "info";

export function StatusBadge({
  status,
  tone,
  label,
}: {
  status: string;
  tone?: Tone;
  /** Human text to show instead of the raw status (kept in data-status). */
  label?: string;
}) {
  const upper = status.toUpperCase();
  const resolved =
    tone ||
    (upper === "OK" ||
    upper === "PASS" ||
    upper === "READY" ||
    upper === "LIVE" ||
    upper === "GROUNDED" ||
    upper === "COMPLETED" ||
    upper === "ACCEPTED" ||
    status === "ok" ||
    status === "ready" ||
    upper.startsWith("OK_")
      ? "ok"
      : upper === "ALERT" ||
          upper === "FAIL" ||
          upper === "FAILED" ||
          upper === "FAILURE" ||
          upper === "ERROR" ||
          upper === "NOT_READY"
        ? "fail"
        : upper === "REGRESSION" ||
            upper === "WARN" ||
            upper === "WARNING" ||
            upper === "CHECKING"
          ? "warn"
          : upper === "RUNNING" || upper === "PENDING"
            ? "info"
            : upper === "INSUFFICIENT_DATA" || upper === "NO_BASELINE"
              ? "neutral"
              : "neutral");
  return (
    <span className={`badge badge-${resolved}`} data-status={status}>
      {label ?? status}
    </span>
  );
}

/**
 * Focusable help affordance: the text is the accessible name and shows as a
 * tooltip on hover and keyboard focus, so it is never mouse-only.
 */
export function Tip({ text, label = "?" }: { text: string; label?: string }) {
  return (
    <span className="tip" tabIndex={0} role="note" aria-label={text} data-tip={text}>
      <span aria-hidden="true">{label}</span>
    </span>
  );
}

/** Horizontal 0..1 bar with an accessible text value. */
export function Bar({
  value,
  tone = "accent",
  label,
  marker,
}: {
  value: number | null | undefined;
  tone?: "accent" | "ok" | "warn" | "err" | "muted";
  label: string;
  /** Optional 0..1 position of a threshold marker. */
  marker?: number | null;
}) {
  const v = value == null || !Number.isFinite(value) ? 0 : Math.max(0, Math.min(1, value));
  return (
    <span className="bar" role="img" aria-label={label}>
      <span className={`bar-fill ${tone}`} style={{ width: `${v * 100}%` }} />
      {marker != null && Number.isFinite(marker) ? (
        <span
          className="bar-marker"
          style={{ left: `${Math.max(0, Math.min(1, marker)) * 100}%` }}
          aria-hidden="true"
        />
      ) : null}
    </span>
  );
}

export function EmptyState({
  children,
  hint,
  compact,
}: {
  children: ReactNode;
  hint?: ReactNode;
  compact?: boolean;
}) {
  return (
    <div
      className={compact ? "empty-state compact" : "empty-state"}
      role="status"
    >
      <p className="empty">{children}</p>
      {hint ? <p className="empty-hint">{hint}</p> : null}
    </div>
  );
}

export function ErrorBanner({ message }: { message: string }) {
  if (!message) return null;
  return (
    <p className="error" role="alert">
      {message}
    </p>
  );
}

export function LoadingState({ label }: { label: string }) {
  return (
    <div className="loading-state" role="status" aria-live="polite">
      <span className="spinner" aria-hidden="true" />
      <p className="muted">{label}</p>
    </div>
  );
}

export function MetaTable({
  rows,
}: {
  rows: Array<[string, ReactNode]>;
}) {
  return (
    <table className="meta-table">
      <tbody>
        {rows.map(([k, v]) => (
          <tr key={k}>
            <th scope="row">{k}</th>
            <td>{v}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function RawToggle({
  label,
  data,
}: {
  label?: string;
  data: unknown;
}) {
  return (
    <details className="raw-toggle">
      <summary>{label || "Raw execution JSON"}</summary>
      <pre className="raw-json">{JSON.stringify(data, null, 2)}</pre>
    </details>
  );
}

export function Section({
  title,
  id,
  children,
  description,
}: {
  title: string;
  id?: string;
  children: ReactNode;
  description?: string;
}) {
  return (
    <section className="block" id={id}>
      <div className="section-head">
        <h3>{title}</h3>
        {description ? <p className="section-desc">{description}</p> : null}
      </div>
      {children}
    </section>
  );
}

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description: string;
  actions?: ReactNode;
  /** Accepted for call-site compatibility; intentionally not rendered. */
  eyebrow?: string;
}) {
  return (
    <header className="page-header">
      <div>
        <h1 className="page-title">{title}</h1>
        <p className="page-desc">{description}</p>
      </div>
      {actions ? <div className="page-actions">{actions}</div> : null}
    </header>
  );
}

/**
 * Small inline "what is this?" affordance. Focusable, with its explanation as
 * the accessible name and a tooltip on hover and focus.
 */
export function InfoDot({ label }: { label: string }) {
  return <Tip text={label} label="i" />;
}

export function Panel({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={className ? `panel ${className}` : "panel"}>{children}</div>
  );
}
