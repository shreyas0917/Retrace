/** Shared number formatting, verdicts and table filters for the console. */
import { failureTitle } from "./labels";
import type { CaseResult } from "./types";

export function isNum(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

/** 0.8333 → "83.3%". */
export function pct(value: unknown, digits = 1): string {
  if (!isNum(value)) return "—";
  return `${(value * 100).toFixed(digits)}%`;
}

/** F1-style metrics are shown as decimals, not percentages. */
export function isF1Metric(metric: string): boolean {
  return /(^|_)f1$/.test(metric) || metric === "f1";
}

/** 0.8333 → "0.833". */
export function decimal(value: unknown, digits = 3): string {
  if (!isNum(value)) return "—";
  return value.toFixed(digits);
}

function signed(text: string, value: number): string {
  if (value > 0) return `+${text}`;
  if (value < 0) return `−${text.replace(/^-/, "")}`;
  return text;
}

/**
 * Baseline delta for a metric: accuracies as signed percentage points
 * (−0.0834 → "−8.3 pp"), F1 metrics as signed decimals (0.012 → "+0.012").
 * The minus sign is U+2212 so it reads clearly in tables.
 */
export function formatDelta(metric: string, delta: unknown): string {
  if (!isNum(delta)) return "—";
  if (isF1Metric(metric)) {
    const rounded = Number(delta.toFixed(3));
    if (rounded === 0) return "±0.000";
    return signed(Math.abs(rounded).toFixed(3), rounded);
  }
  const pp = Number((delta * 100).toFixed(1));
  if (pp === 0) return "±0.0 pp";
  return signed(`${Math.abs(pp).toFixed(1)} pp`, pp);
}

/** Current/baseline value for a metric: accuracy as %, F1 as decimal. */
export function formatMetricValue(metric: string, value: unknown): string {
  if (!isNum(value)) return "—";
  return isF1Metric(metric) ? decimal(value) : pct(value);
}

export function formatMs(ms: number | null | undefined): string {
  if (!isNum(ms)) return "—";
  if (ms >= 10000) return `${(ms / 1000).toFixed(1)} s`;
  return `${Math.round(ms)} ms`;
}

// --- Gate verdicts ----------------------------------------------------------

export type VerdictKind = "pass" | "regression" | "error" | "no_baseline" | "unknown";

export type Verdict = {
  kind: VerdictKind;
  exitCode: number | null;
  title: string;
  detail: string;
  /** True when the exit code was derived from a stored comparison. */
  derived: boolean;
};

const EXIT_MEANING: Record<number, string> = {
  0: "the gate passed",
  1: "a regression against the baseline or a threshold",
  2: "the run could not complete",
};

/**
 * Verdict for an evaluation run. `exitCode` comes from POST /experiments; for
 * stored experiments it is derived the way the backend gate computes it
 * (comparison.passed → 0, otherwise 1; a failed run → 2).
 */
export function gateVerdict(input: {
  exitCode?: number | null;
  status?: string | null;
  comparison?: { passed: boolean; has_baseline: boolean } | null;
}): Verdict {
  let exitCode = isNum(input.exitCode) ? input.exitCode : null;
  let derived = false;
  const status = (input.status || "").toUpperCase();
  if (exitCode == null) {
    if (status === "FAILED" || status === "ERROR") {
      exitCode = 2;
      derived = true;
    } else if (input.comparison) {
      exitCode = input.comparison.passed ? 0 : 1;
      derived = true;
    }
  }
  const noBaseline = input.comparison ? !input.comparison.has_baseline : false;
  if (exitCode === 0) {
    return {
      kind: noBaseline ? "no_baseline" : "pass",
      exitCode,
      title: noBaseline ? "Passed thresholds, no baseline to compare" : "Pass",
      detail: noBaseline
        ? "No accepted baseline exists for this suite, so only the absolute thresholds were checked."
        : "No metric regressed beyond its allowed drop and every threshold held.",
      derived,
    };
  }
  if (exitCode === 1) {
    return {
      kind: "regression",
      exitCode,
      title: "Regression",
      detail: "At least one metric dropped past its allowed tolerance or fell below a threshold.",
      derived,
    };
  }
  if (exitCode === 2) {
    return {
      kind: "error",
      exitCode,
      title: "Error",
      detail: "The run did not complete, so no verdict on quality is possible.",
      derived,
    };
  }
  return {
    kind: "unknown",
    exitCode,
    title: "No verdict",
    detail: "This run has no comparison stored.",
    derived,
  };
}

export function exitMeaning(code: number | null): string {
  return code == null ? "" : EXIT_MEANING[code] || "";
}

// --- Case table -------------------------------------------------------------

export function caseFailed(c: CaseResult): boolean {
  return c.passed !== true || !!c.error;
}

/** Failures first, then by case id. Does not mutate the input. */
export function sortFailuresFirst(cases: CaseResult[]): CaseResult[] {
  return [...cases].sort((a, b) => {
    const fa = caseFailed(a) ? 0 : 1;
    const fb = caseFailed(b) ? 0 : 1;
    if (fa !== fb) return fa - fb;
    return a.case_id.localeCompare(b.case_id);
  });
}

/**
 * Case-insensitive search over case id, query, expected/predicted codes,
 * their plain-English titles, rule ids and error text. Every whitespace-
 * separated term must match. `onlyFailures` keeps failed cases only.
 */
export function filterCases(
  cases: CaseResult[],
  query: string,
  onlyFailures = false,
): CaseResult[] {
  const terms = query.toLowerCase().split(/\s+/).filter(Boolean);
  return sortFailuresFirst(cases).filter((c) => {
    if (onlyFailures && !caseFailed(c)) return false;
    if (terms.length === 0) return true;
    const hay = [
      c.case_id,
      c.query,
      c.expected_failure_code,
      c.predicted_failure_code,
      c.expected_failure_code ? failureTitle(c.expected_failure_code) : "",
      c.predicted_failure_code ? failureTitle(c.predicted_failure_code) : "",
      c.expected_rule_id,
      c.predicted_rule_id,
      c.error,
      caseFailed(c) ? "fail failed" : "pass passed",
    ]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    return terms.every((t) => hay.includes(t));
  });
}
