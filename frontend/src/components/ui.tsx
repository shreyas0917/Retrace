import type { ReactNode } from "react";

export function StatusBadge({
  status,
  tone,
}: {
  status: string;
  tone?: "ok" | "alert" | "warn" | "neutral" | "fail" | "pass" | "info";
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
      {status}
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
  eyebrow,
}: {
  title: string;
  description: string;
  actions?: ReactNode;
  eyebrow?: string;
}) {
  return (
    <header className="page-header">
      <div>
        {eyebrow ? <p className="page-eyebrow">{eyebrow}</p> : null}
        <h1 className="page-title">{title}</h1>
        <p className="page-desc">{description}</p>
      </div>
      {actions ? <div className="page-actions">{actions}</div> : null}
    </header>
  );
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
