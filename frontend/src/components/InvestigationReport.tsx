import { useMemo, useState, type ReactNode } from "react";
import { Bar, EmptyState, RawToggle, StatusBadge, Tip } from "./ui";
import { MarkdownAnswer } from "./MarkdownAnswer";
import { RunbookDisclosure } from "./Runbook";
import {
  ABSTENTION_KIND_LABELS,
  EVIDENCE_STATUS_HELP,
  JUDGE_LABELS,
  abstentionDetectedByLabel,
  friendlyDiagnosis,
  humanize,
  judgeLabel,
  layerLabel,
  recommendationLabel,
  severityLabel,
  signalLabel,
  statusLabel,
  timelineLabel,
  SIGNAL_LABELS,
} from "../labels";
import { STAGE_STATE_LABELS, stageStates } from "../stages";
import { decimal, formatMs, isNum } from "../format";
import type { Investigation } from "../types";

type Chunk = Investigation["retrieval"]["chunks"][number];
type Judge = Investigation["judges"][number];

export const REPORT_SECTIONS: Array<{ id: string; label: string }> = [
  { id: "verdict", label: "Verdict" },
  { id: "next-step", label: "Next step" },
  { id: "answer", label: "Answer vs evidence" },
  { id: "retrieval-section", label: "Chunks" },
  { id: "judges-section", label: "Judges" },
  { id: "rule-section", label: "How it decided" },
  { id: "timing", label: "Timing" },
  { id: "execution-section", label: "Details" },
];

function prefersReducedMotion(): boolean {
  try {
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  } catch {
    return false;
  }
}

export function scrollToId(id: string): void {
  const el = document.getElementById(id);
  if (!el) return;
  el.scrollIntoView?.({
    behavior: prefersReducedMotion() ? "auto" : "smooth",
    block: "start",
  });
  if (el.tabIndex < 0 || el.hasAttribute("tabindex")) {
    el.focus?.({ preventScroll: true });
  }
}

function yesNo(v: unknown, whenNull = "Not evaluated"): string {
  if (v === null || v === undefined) return whenNull;
  if (typeof v === "boolean") return v ? "Yes" : "No";
  return String(v);
}

export function formatSignalValue(key: string, value: unknown): string {
  if (value === null || value === undefined) {
    if (key === "gold_hit" || key === "context_sufficient") return "Not evaluated";
    if (key === "stage_error") return "None";
    return "—";
  }
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "number") {
    if (Number.isInteger(value)) return String(value);
    return decimal(value, 2);
  }
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

const OPS: Record<string, string> = {
  "==": "is",
  "!=": "is not",
  ">=": "≥",
  "<=": "≤",
  ">": ">",
  "<": "<",
};

const THRESHOLD_NAMES: Record<string, string> = {
  TAU_FAITHFUL: "the faithfulness threshold",
  TAU_DISTRACTOR_FRAC: "the distractor threshold",
};

/** "context_sufficient == false" → readable parts; null when not parseable. */
export function describeCondition(
  condition: string,
): { label: string; op: string; value: string; key: string } | null {
  const m = condition.trim().match(/^([a-z_]+)\s*(==|!=|>=|<=|>|<)\s*(.+)$/);
  if (!m) return null;
  const [, key, op, raw] = m;
  if (!SIGNAL_LABELS[key]) return null;
  let value = raw.trim();
  if (value === "true") value = "Yes";
  else if (value === "false") value = "No";
  else if (THRESHOLD_NAMES[value]) value = THRESHOLD_NAMES[value];
  return { key, label: SIGNAL_LABELS[key].label, op: OPS[op] || op, value };
}

type BestEvidence =
  | { kind: "chunk"; chunk: Chunk; reason: string }
  | { kind: "missing"; chunkId: string; reason: string }
  | null;

function nliClaims(judges: Judge[]): Array<Record<string, unknown>> {
  const f = judges.find((j) => j.judge_type === "faithfulness");
  const claims = f?.output?.claims;
  return Array.isArray(claims) ? (claims as Array<Record<string, unknown>>) : [];
}

/** Pick the chunk most worth reading next to the answer. */
export function bestEvidence(inv: Investigation): BestEvidence {
  const chunks = inv.retrieval.chunks || [];
  const byId = new Map(chunks.filter((c) => c.chunk_id).map((c) => [c.chunk_id!, c]));

  // 1. The NLI faithfulness judge's highest-entailment chunk.
  let best: { id: string; ent: number } | null = null;
  for (const c of nliClaims(inv.judges)) {
    const id = typeof c.best_chunk_id === "string" ? c.best_chunk_id : null;
    const ent = isNum(c.entailment) ? c.entailment : null;
    if (id && ent != null && (!best || ent > best.ent) && byId.get(id)?.text) {
      best = { id, ent };
    }
  }
  if (best) {
    return {
      kind: "chunk",
      chunk: byId.get(best.id)!,
      reason: "Highest-entailment passage for the answer's claims (faithfulness judge).",
    };
  }

  // 2. The first chunk the diagnosis cites as evidence.
  const refs = (inv.evidence?.length
    ? inv.evidence.map((e) => e.ref)
    : inv.diagnosis?.evidence_refs || []
  ).filter((r): r is string => !!r && r.startsWith("chunk:"));
  for (const ref of refs) {
    const c = byId.get(ref.slice(6));
    if (c?.evidence_status === "missing" || (c && !c.text)) {
      return {
        kind: "missing",
        chunkId: ref.slice(6),
        reason: "The diagnosis cites this expected passage, but the retriever did not return it.",
      };
    }
    if (c?.text) {
      return { kind: "chunk", chunk: c, reason: "The first passage the diagnosis cites as evidence." };
    }
  }

  // 3. The relevance judge's top-scored relevant chunk.
  const relevant = chunks
    .filter((c) => c.text && c.relevance && (c.relevance as { relevant?: unknown }).relevant === true)
    .sort(
      (a, b) =>
        Number((b.relevance as { score?: number }).score ?? 0) -
        Number((a.relevance as { score?: number }).score ?? 0),
    );
  if (relevant[0]) {
    return { kind: "chunk", chunk: relevant[0], reason: "The passage the relevance judge scored highest." };
  }

  // 4. The top-ranked retrieved chunk.
  const top = chunks
    .filter((c) => c.text)
    .sort((a, b) => (a.rank ?? 1e9) - (b.rank ?? 1e9))[0];
  return top ? { kind: "chunk", chunk: top, reason: "The top-ranked retrieved passage." } : null;
}

function evidenceTone(status: string): "ok" | "fail" | "warn" | "neutral" {
  const s = status.toLowerCase();
  if (s === "missing") return "fail";
  if (s === "expected" || s === "relevant") return "ok";
  if (s === "distractor") return "warn";
  return "neutral";
}

function similarityTone(score: number): "ok" | "accent" | "muted" {
  if (score >= 0.7) return "ok";
  if (score >= 0.4) return "accent";
  return "muted";
}

// --- Sections ---------------------------------------------------------------

function SectionCard({
  id,
  title,
  description,
  children,
  aside,
}: {
  id: string;
  title: string;
  description?: ReactNode;
  children: ReactNode;
  aside?: ReactNode;
}) {
  return (
    <section className="report-card" id={id} tabIndex={-1} aria-labelledby={`${id}-title`}>
      <div className="report-card-head">
        <div>
          <h2 className="report-card-title" id={`${id}-title`}>
            {title}
          </h2>
          {description ? <p className="section-desc">{description}</p> : null}
        </div>
        {aside}
      </div>
      {children}
    </section>
  );
}

function StageStrip({ code }: { code: string | null | undefined }) {
  const stages = stageStates(code);
  return (
    <ol className="stage-strip" aria-label="Pipeline stages">
      {stages.map((s, i) => (
        <li key={s.id} className={`stage stage-${s.state}`}>
          <span className="stage-index" aria-hidden="true">
            {s.state === "passed" ? "✓" : s.state === "failed" ? "!" : i + 1}
          </span>
          <span className="stage-body">
            <span className="stage-name">{s.label}</span>
            <span className="stage-state">{STAGE_STATE_LABELS[s.state]}</span>
            <span className="stage-note">{s.note}</span>
          </span>
        </li>
      ))}
    </ol>
  );
}

function Verdict({ inv }: { inv: Investigation }) {
  const diag = inv.diagnosis;
  if (!diag) {
    return (
      <SectionCard id="verdict" title="Verdict">
        <EmptyState compact hint="Run diagnose for this execution to get a verdict.">
          No diagnosis yet for this execution.
        </EmptyState>
        <StageStrip code={null} />
      </SectionCard>
    );
  }
  const fd = friendlyDiagnosis(diag.failure_code);
  const calibrated = diag.calibrated_confidence ?? inv.why?.calibrated_confidence ?? null;
  const strength = diag.confidence
    ? diag.confidence.charAt(0).toUpperCase() + diag.confidence.slice(1).toLowerCase()
    : null;
  return (
    <section
      className={`verdict sev-${fd.severity}`}
      id="verdict"
      tabIndex={-1}
      aria-labelledby="verdict-title"
    >
      <div className="verdict-main">
        <p className="diagnosis-kicker">Verdict</p>
        <h2 className="verdict-title" id="verdict-title">
          {fd.title}
        </h2>
        <p className="verdict-what">{fd.what}</p>
        <div className="verdict-chips">
          <span className={`severity sev-${fd.severity}`}>{severityLabel(fd.severity)}</span>
          {diag.uncertain || diag.review_recommended ? (
            <StatusBadge status="UNCERTAIN" tone="warn" label="Manual review recommended" />
          ) : null}
        </div>
      </div>
      <dl className="verdict-facts">
        <div className="verdict-fact">
          <dt>Failure code</dt>
          <dd>
            <code className="failure-code">{diag.failure_code}</code>
          </dd>
        </div>
        <div className="verdict-fact">
          <dt>Rule</dt>
          <dd className="rule-dd">
            <code className="rule-id">{diag.rule_id}</code>
            <span className="muted small"> · {layerLabel(diag.layer)} layer</span>
          </dd>
        </div>
        <div className="verdict-fact">
          <dt>
            Calibrated confidence{" "}
            <Tip
              text={`Calibrated probability that this diagnosis is correct${diag.calibration_version ? ` (${diag.calibration_version})` : ""}. Rule strength is the rule's own heuristic, not a probability.`}
            />
          </dt>
          <dd>
            {calibrated != null ? (
              <>
                <span className="verdict-conf tnum">{Math.round(calibrated * 100)}%</span>
                <Bar
                  value={calibrated}
                  label={`Calibrated confidence ${Math.round(calibrated * 100)}%`}
                />
              </>
            ) : (
              <span className="muted">Not calibrated</span>
            )}
            {strength ? <span className="muted small">Rule strength: {strength}</span> : null}
          </dd>
        </div>
      </dl>
      {diag.secondary_codes?.length ? (
        <p className="verdict-secondary small">
          <span className="muted">Also noted: </span>
          {diag.secondary_codes.map((c, i) => (
            <span key={c}>
              {i > 0 ? ", " : ""}
              {friendlyDiagnosis(c).title} <code className="muted">{c}</code>
            </span>
          ))}
        </p>
      ) : null}
      <StageStrip code={diag.failure_code} />
    </section>
  );
}

function NextStep({ inv }: { inv: Investigation }) {
  const diag = inv.diagnosis;
  if (!diag) return null;
  const rec = recommendationLabel(diag.recommendation_code);
  const runbook = inv.failure?.runbook;
  return (
    <section className="nextstep-card" id="next-step" tabIndex={-1} aria-labelledby="next-step-title">
      <div className="nextstep-head">
        <p className="diagnosis-kicker">Next step</p>
        {diag.recommendation_code ? (
          <code className="muted small">{diag.recommendation_code}</code>
        ) : null}
      </div>
      <h3 className="nextstep-heading" id="next-step-title">
        {rec.title}
      </h3>
      <p className="nextstep-body">{rec.action}</p>
      {runbook ? (
        <RunbookDisclosure slug={runbook} />
      ) : (
        <p className="muted small nextstep-norunbook">No runbook is linked to this failure code.</p>
      )}
    </section>
  );
}

function ChunkCard({ chunk }: { chunk: Chunk }) {
  return (
    <div className="evidence-chunk">
      <div className="evidence-chunk-meta">
        <span className="evidence-source">{chunk.source_name || chunk.document_id || "Unknown source"}</span>
        <code className="muted">{chunk.chunk_id}</code>
        {chunk.rank != null ? <span className="muted small">rank {chunk.rank}</span> : null}
        {isNum(chunk.score) ? (
          <span className="muted small tnum">similarity {chunk.score.toFixed(2)}</span>
        ) : null}
      </div>
      <blockquote className="evidence-quote">{chunk.text}</blockquote>
    </div>
  );
}

function AnswerVsEvidence({ inv }: { inv: Investigation }) {
  const best = useMemo(() => bestEvidence(inv), [inv]);
  const ex = inv.execution;
  return (
    <SectionCard
      id="answer"
      title="Answer vs evidence"
      description={
        <>
          <span className="muted">Question: </span>
          <span className="answer-question">{ex.query}</span>
        </>
      }
    >
      <div className="compare">
        <div className="compare-col">
          <div className="compare-head">
            <h3 className="compare-title">Model answer</h3>
            {ex.abstained ? <StatusBadge status="ABSTAINED" tone="info" label="Declined to answer" /> : null}
          </div>
          {ex.answer ? (
            <MarkdownAnswer text={ex.answer} />
          ) : (
            <p className="muted compare-empty">No answer was recorded for this execution.</p>
          )}
          {ex.abstention_kind ? (
            <p className="muted small">
              Abstention: {ABSTENTION_KIND_LABELS[ex.abstention_kind] || humanize(ex.abstention_kind)}
            </p>
          ) : null}
        </div>
        <div className="compare-col">
          <div className="compare-head">
            <h3 className="compare-title">Best evidence</h3>
          </div>
          {best == null ? (
            <p className="muted compare-empty">No retrieved passage to compare with.</p>
          ) : best.kind === "missing" ? (
            <div className="evidence-missing">
              <p>
                <strong>Not retrieved:</strong> <code>{best.chunkId}</code>
              </p>
              <p className="muted small">{best.reason}</p>
            </div>
          ) : (
            <>
              <ChunkCard chunk={best.chunk} />
              <p className="muted small">{best.reason}</p>
            </>
          )}
        </div>
      </div>
    </SectionCard>
  );
}

function ChunkText({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  const LIMIT = 140;
  if (text.length <= LIMIT) return <span className="chunk-text">{text}</span>;
  return (
    <span className="chunk-text">
      {open ? text : `${text.slice(0, LIMIT).trimEnd()}…`}{" "}
      <button
        type="button"
        className="linkish small"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      >
        {open ? "Show less" : "Show full text"}
      </button>
    </span>
  );
}

function ChunkTable({ inv, activeRef }: { inv: Investigation; activeRef: string | null }) {
  const r = inv.retrieval;
  const maxScore = Math.max(1, ...r.chunks.map((c) => (isNum(c.score) ? c.score : 0)));
  return (
    <SectionCard id="retrieval-section" title="Retrieval evidence" description="Every passage the retriever returned, plus expected passages it missed.">
      <dl className="fact-row">
        <div>
          <dt>{signalLabel("n_retrieved").label}</dt>
          <dd>{r.n_retrieved}</dd>
        </div>
        <div>
          <dt>
            {signalLabel("gold_hit").label} <Tip text={signalLabel("gold_hit").help} />
          </dt>
          <dd>{r.gold_ids?.length ? yesNo(r.gold_hit) : "Not evaluated"}</dd>
        </div>
        <div>
          <dt>
            {signalLabel("context_sufficient").label} <Tip text={signalLabel("context_sufficient").help} />
          </dt>
          <dd>{yesNo(r.context_sufficient)}</dd>
        </div>
        <div>
          <dt>
            {signalLabel("irrelevant_frac").label} <Tip text={signalLabel("irrelevant_frac").help} />
          </dt>
          <dd>{isNum(r.irrelevant_frac) ? `${Math.round(r.irrelevant_frac * 100)}%` : "—"}</dd>
        </div>
      </dl>
      {r.chunks.length === 0 ? (
        <EmptyState compact>No retrieved chunks.</EmptyState>
      ) : (
        <div className="table-scroll" role="region" aria-label="Retrieved chunks" tabIndex={0}>
          <table className="data-table chunk-table">
            <thead>
              <tr>
                <th className="num">Rank</th>
                <th>Passage</th>
                <th>Similarity</th>
                <th>Status</th>
                <th>Text</th>
              </tr>
            </thead>
            <tbody>
              {r.chunks.map((c) => {
                const ref = c.chunk_id ? `chunk:${c.chunk_id}` : "";
                const active = !!ref && activeRef === ref;
                return (
                  <tr
                    key={`${c.chunk_id}-${c.rank}-${c.evidence_status}`}
                    id={c.chunk_id ? `chunk-${c.chunk_id}` : undefined}
                    className={active ? "row-active row-flash" : undefined}
                  >
                    <td className="num">{c.rank ?? "—"}</td>
                    <td className="chunk-id-cell">
                      <span className="chunk-source">{c.source_name || c.document_id || "—"}</span>
                      <code className="muted">{c.chunk_id || "—"}</code>
                    </td>
                    <td className="sim-cell">
                      {isNum(c.score) ? (
                        <span className="sim">
                          <Bar
                            value={c.score / maxScore}
                            tone={similarityTone(c.score)}
                            label={`Similarity ${c.score.toFixed(4)}`}
                          />
                          <span className="tnum mono small">{c.score.toFixed(4)}</span>
                        </span>
                      ) : (
                        <span className="muted">—</span>
                      )}
                    </td>
                    <td>
                      <span title={EVIDENCE_STATUS_HELP[c.evidence_status] || undefined}>
                        <StatusBadge status={c.evidence_status} tone={evidenceTone(c.evidence_status)} />
                      </span>
                    </td>
                    <td className="chunk-text-cell">
                      {c.text ? <ChunkText text={c.text} /> : <span className="muted">Not retrieved</span>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </SectionCard>
  );
}

function ReadableValue({ value }: { value: unknown }) {
  if (value === null || value === undefined) return <span className="muted">—</span>;
  if (typeof value === "boolean") return <>{value ? "Yes" : "No"}</>;
  if (typeof value === "number") return <span className="tnum">{Number.isInteger(value) ? value : decimal(value, 3)}</span>;
  if (typeof value === "string") return <>{value || "—"}</>;
  if (Array.isArray(value) && value.every((v) => typeof v === "string")) {
    return value.length ? <code>{value.join(", ")}</code> : <span className="muted">none</span>;
  }
  return <code>{JSON.stringify(value)}</code>;
}

function RelevanceBody({ judge }: { judge: Judge }) {
  const items = Array.isArray(judge.output?.items)
    ? (judge.output.items as Array<Record<string, unknown>>)
    : [];
  return (
    <>
      <dl className="judge-facts">
        <div>
          <dt>Context sufficient</dt>
          <dd>{yesNo(judge.output?.context_sufficient ?? judge.result?.context_sufficient)}</dd>
        </div>
        <div>
          <dt>Passages judged</dt>
          <dd>{items.length}</dd>
        </div>
      </dl>
      {items.length ? (
        <ul className="judge-items">
          {items.map((it, i) => (
            <li key={`${String(it.chunk_id)}-${i}`}>
              <div className="judge-item-head">
                <code>{String(it.chunk_id ?? "—")}</code>
                <StatusBadge
                  status={it.relevant ? "relevant" : "not relevant"}
                  tone={it.relevant ? "ok" : "warn"}
                  label={it.relevant ? "Relevant" : "Not relevant"}
                />
                {isNum(it.score) ? <span className="muted small tnum">score {decimal(it.score, 2)}</span> : null}
              </div>
              {it.rationale ? <p className="judge-rationale">{String(it.rationale)}</p> : null}
            </li>
          ))}
        </ul>
      ) : null}
    </>
  );
}

function FaithfulnessBody({ judge }: { judge: Judge }) {
  const out = judge.output || {};
  const claims = Array.isArray(out.claims) ? (out.claims as Array<Record<string, unknown>>) : [];
  const isNli = out.backend === "nli" || claims.some((c) => "entailment" in c);
  return (
    <>
      <dl className="judge-facts">
        <div>
          <dt>Faithfulness score</dt>
          <dd>{isNum(out.faithfulness_score) ? decimal(out.faithfulness_score, 2) : "—"}</dd>
        </div>
        <div>
          <dt>Claims</dt>
          <dd>{claims.length}</dd>
        </div>
        {isNli ? (
          <div>
            <dt>Method</dt>
            <dd>Local NLI model</dd>
          </div>
        ) : null}
      </dl>
      {out.truncated === true ? (
        <p className="judge-flag" role="note">
          <strong>Truncated:</strong> scored {String(out.pair_count ?? "?")} claim and passage pairs (limit{" "}
          {String(out.max_pairs ?? "?")}); {String(out.chunks_skipped ?? 0)} least-similar passage(s) were not checked.
        </p>
      ) : isNli && isNum(out.pair_count) ? (
        <p className="muted small">
          Scored {out.pair_count} claim and passage pairs
          {isNum(out.max_pairs) ? ` (limit ${out.max_pairs})` : ""}.
        </p>
      ) : null}
      {claims.length ? (
        <div className="table-scroll" role="region" aria-label="Claims" tabIndex={0}>
          <table className="data-table claim-table">
            <thead>
              <tr>
                <th>Claim</th>
                <th>{isNli ? "Best passage" : "Supporting passages"}</th>
                {isNli ? <th className="num">Entailment</th> : null}
                <th>Supported</th>
              </tr>
            </thead>
            <tbody>
              {claims.map((c, i) => (
                <tr key={i}>
                  <td className="claim-cell">{String(c.claim ?? "—")}</td>
                  <td>
                    {isNli ? (
                      c.best_chunk_id ? <code>{String(c.best_chunk_id)}</code> : <span className="muted">—</span>
                    ) : (
                      <ReadableValue value={c.supporting_chunk_ids} />
                    )}
                  </td>
                  {isNli ? (
                    <td className="num">{isNum(c.entailment) ? decimal(c.entailment, 2) : "—"}</td>
                  ) : null}
                  <td>
                    <StatusBadge
                      status={c.supported ? "supported" : "unsupported"}
                      tone={c.supported ? "ok" : c.contradicted ? "fail" : "warn"}
                      label={c.supported ? "Supported" : c.contradicted ? "Contradicted" : "Not supported"}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </>
  );
}

function ContradictionBody({ judge }: { judge: Judge }) {
  const out = judge.output || {};
  return (
    <dl className="judge-facts stacked">
      <div>
        <dt>Contradicts the passages</dt>
        <dd>{yesNo(out.contradicts ?? judge.result?.contradicts)}</dd>
      </div>
      {out.explanation ? (
        <div>
          <dt>Explanation</dt>
          <dd>{String(out.explanation)}</dd>
        </div>
      ) : null}
      {Array.isArray(out.chunk_ids) && out.chunk_ids.length ? (
        <div>
          <dt>Passages involved</dt>
          <dd>
            <ReadableValue value={out.chunk_ids} />
          </dd>
        </div>
      ) : null}
    </dl>
  );
}

function GenericBody({ judge }: { judge: Judge }) {
  const entries = Object.entries(judge.result || {});
  if (!entries.length) return <p className="muted small">No summary fields.</p>;
  return (
    <dl className="judge-facts stacked">
      {entries.map(([k, v]) => (
        <div key={k}>
          <dt>{humanize(k)}</dt>
          <dd>
            <ReadableValue value={v} />
          </dd>
        </div>
      ))}
    </dl>
  );
}

function JudgeCard({ judge, active }: { judge: Judge; active: boolean }) {
  const body =
    judge.judge_type === "relevance" ? (
      <RelevanceBody judge={judge} />
    ) : judge.judge_type === "faithfulness" ? (
      <FaithfulnessBody judge={judge} />
    ) : judge.judge_type === "contradiction" ? (
      <ContradictionBody judge={judge} />
    ) : (
      <GenericBody judge={judge} />
    );
  return (
    <article className={active ? "judge-card row-flash" : "judge-card"} id={`judge-${judge.judge_type}`}>
      <header className="judge-head">
        <div>
          <h3 className="judge-title">{judgeLabel(judge.judge_type)} judge</h3>
          <code className="muted">{judge.judge_type}</code>
        </div>
        <StatusBadge
          status={judge.status}
          tone={judge.schema_ok ? "ok" : "fail"}
          label={judge.schema_ok ? "Valid output" : "Malformed output"}
        />
      </header>
      {JUDGE_LABELS[judge.judge_type] ? (
        <p className="muted small judge-help">{JUDGE_LABELS[judge.judge_type].help}</p>
      ) : null}
      {body}
      <p className="judge-meta muted small">
        {judge.model ? <span>Model {judge.model}</span> : null}
        {judge.latency_ms != null ? <span>{formatMs(judge.latency_ms)}</span> : null}
        {judge.attempts > 1 ? <span>{judge.attempts} attempts</span> : null}
        {judge.prompt_version ? <span>Prompt {judge.prompt_version}</span> : null}
      </p>
      <RawToggle label="Raw judge output" data={judge.output} />
    </article>
  );
}

function Judges({ inv, activeRef }: { inv: Investigation; activeRef: string | null }) {
  return (
    <SectionCard id="judges-section" title="Judges" description="The model-based checks the rules read their signals from.">
      {inv.judges.length === 0 ? (
        <EmptyState compact>No judges ran (short-circuit diagnosis or not yet diagnosed).</EmptyState>
      ) : (
        <div className="judge-grid">
          {inv.judges.map((j) => (
            <JudgeCard key={j.judge_type} judge={j} active={activeRef === `judge:${j.judge_type}`} />
          ))}
        </div>
      )}
    </SectionCard>
  );
}

function RuleDecision({
  inv,
  onJump,
}: {
  inv: Investigation;
  onJump: (ref: string) => void;
}) {
  const rule = inv.rule;
  const signals = inv.why?.signals_used || {};
  const explanation = inv.diagnosis?.explanation || inv.why?.explanation;
  const refs: Array<{ ref: string; type: string }> = inv.evidence?.length
    ? inv.evidence.filter((e) => e.ref).map((e) => ({ ref: e.ref!, type: e.evidence_type }))
    : (inv.diagnosis?.evidence_refs || []).map((r) => ({ ref: r, type: r.split(":")[0] }));
  return (
    <SectionCard id="rule-section" title="How the rule decided">
      {inv.why?.note ? <p className="note">{inv.why.note}</p> : null}
      {!rule ? (
        <EmptyState compact>No rule attached (diagnose first).</EmptyState>
      ) : (
        <>
          <p className="rule-line">
            Rule <code>{rule.rule_id}</code> fired: {rule.summary}
          </p>
          <h3 className="subhead">Matched conditions</h3>
          <ul className="condition-list">
            {rule.conditions.map((c) => {
              const d = describeCondition(c);
              const actual = d && d.key in signals ? formatSignalValue(d.key, signals[d.key]) : null;
              return (
                <li key={c}>
                  <span className="cond-check" aria-hidden="true">
                    ✓
                  </span>
                  <span className="cond-text">
                    {d ? (
                      <>
                        <span>
                          {d.label} {d.op} {d.value}
                          {actual != null ? <span className="muted"> (actual: {actual})</span> : null}
                        </span>
                        <code className="cond-raw">{c}</code>
                      </>
                    ) : (
                      <code>{c}</code>
                    )}
                  </span>
                </li>
              );
            })}
          </ul>
        </>
      )}
      {explanation ? (
        <p className="rule-explanation">
          <strong>Engine explanation: </strong>
          {explanation}
        </p>
      ) : null}
      {Object.keys(signals).length ? (
        <>
          <h3 className="subhead">Signals the rules read</h3>
          <dl className="signal-grid">
            {Object.entries(signals).map(([k, v]) => {
              const s = signalLabel(k);
              return (
                <div key={k} className="signal">
                  <dt>
                    {s.label} <Tip text={`${s.help} (${k})`} />
                  </dt>
                  <dd className="tnum">{formatSignalValue(k, v)}</dd>
                </div>
              );
            })}
          </dl>
        </>
      ) : null}
      <h3 className="subhead">Evidence references</h3>
      {refs.length === 0 ? (
        <p className="muted small">No evidence references stored.</p>
      ) : (
        <ul className="evidence-refs">
          {refs.map((e) => (
            <li key={`${e.type}-${e.ref}`}>
              <button
                type="button"
                className="ref-chip"
                onClick={() => onJump(e.ref)}
                aria-label={`Show evidence ${e.ref}`}
              >
                <code>{e.ref}</code>
              </button>
              <span className="muted small"> {humanize(e.type)}</span>
            </li>
          ))}
        </ul>
      )}
    </SectionCard>
  );
}

type WaterfallRow = {
  key: string;
  label: string;
  phase: string;
  start: number;
  duration: number | null;
  status: string;
};

export function waterfallRows(timeline: Investigation["timeline"]): WaterfallRow[] {
  const rows: WaterfallRow[] = [];
  const cursor: Record<string, number> = {};
  for (const t of timeline) {
    if (t.operation === "request") continue;
    const phase = t.phase || "other";
    const dur = isNum(t.duration_ms) ? t.duration_ms : null;
    // The diagnosis row is the diagnose request's wall clock: it spans the
    // judges, so it starts at the beginning of its phase.
    const start = t.operation === "diagnosis" ? 0 : cursor[phase] || 0;
    rows.push({
      key: `${t.operation}-${t.id ?? rows.length}`,
      label: timelineLabel(t.operation),
      phase,
      start,
      duration: dur,
      status: t.status,
    });
    if (t.operation !== "diagnosis" && dur != null) cursor[phase] = start + dur;
  }
  return rows;
}

function Waterfall({ inv }: { inv: Investigation }) {
  const rows = waterfallRows(inv.timeline || []);
  const total = Math.max(1, ...rows.map((r) => r.start + (r.duration ?? 0)));
  const phases = Array.from(new Set(rows.map((r) => r.phase)));
  return (
    <SectionCard
      id="timing"
      title="Latency"
      description="Generate and diagnose are separate requests; bars share one time scale. Judges run one after another inside diagnose."
    >
      {rows.length === 0 ? (
        <p className="muted small">No timing recorded.</p>
      ) : (
        <div className="waterfall">
          {phases.map((phase) => (
            <div key={phase} className="waterfall-phase">
              <h3 className="subhead">{phase === "generate" ? "Generate request" : phase === "diagnose" ? "Diagnose request" : humanize(phase)}</h3>
              <ul>
                {rows
                  .filter((r) => r.phase === phase)
                  .map((r) => (
                    <li key={r.key} className="wf-row">
                      <span className="wf-label">{r.label}</span>
                      <span className="wf-track" aria-hidden="true">
                        {r.duration != null ? (
                          <span
                            className={`wf-bar ${r.label === "Diagnosis" ? "total" : ""}`}
                            style={{
                              left: `${(r.start / total) * 100}%`,
                              width: `${Math.max(0.8, (r.duration / total) * 100)}%`,
                            }}
                          />
                        ) : null}
                      </span>
                      <span className="wf-value tnum">
                        {r.duration != null ? formatMs(r.duration) : <span className="muted">not recorded</span>}
                      </span>
                    </li>
                  ))}
              </ul>
            </div>
          ))}
        </div>
      )}
    </SectionCard>
  );
}

function Details({
  inv,
  corpusLabel,
}: {
  inv: Investigation;
  corpusLabel?: string | null;
}) {
  const ex = inv.execution;
  const external = ex.source === "external";
  const ext = (ex as { external?: { metadata?: Record<string, unknown> | null; abstention_detected_by?: string | null } | null })
    .external;
  const g = ex.generation;
  const items: Array<[string, ReactNode]> = [
    ["Query", ex.query || "—"],
    ["Execution ID", <code key="e">{ex.execution_id}</code>],
    ["Request ID", ex.request_id ? <code key="r">{ex.request_id}</code> : "—"],
    [
      "Corpus version",
      ex.corpus_version_id ? (
        <span key="cv">
          <code>{ex.corpus_version_id}</code>
          {corpusLabel ? <span className="meta-sub muted small">{corpusLabel}</span> : null}
        </span>
      ) : (
        <span key="cv">
          None (external trace)
          {external ? (
            <span className="meta-sub muted small">Sent from another RAG app via POST /api/v1/traces</span>
          ) : null}
        </span>
      ),
    ],
    ["Status", <StatusBadge key="s" status={ex.status} label={statusLabel(ex.status)} />],
    ["Passages requested (top k)", ex.top_k ? String(ex.top_k) : "—"],
    ["Model", g?.model || "—"],
    ["Temperature", g?.temperature == null ? "—" : String(g.temperature)],
    ["Prompt version", g?.prompt_version || "—"],
    [
      "Tokens (prompt / completion)",
      g?.prompt_tokens == null && g?.completion_tokens == null
        ? "—"
        : `${g?.prompt_tokens ?? "—"} / ${g?.completion_tokens ?? "—"}`,
    ],
    ["Generate total", formatMs(ex.latency_ms?.generate_total ?? ex.latency_ms?.total)],
    ["Diagnosis time", formatMs(ex.latency_ms?.diagnosis)],
  ];
  if (external) {
    items.push(["Abstention detected by", abstentionDetectedByLabel(ext?.abstention_detected_by)]);
    const app = ext?.metadata && typeof ext.metadata.app === "string" ? ext.metadata.app : null;
    if (app) items.push(["Source app", app]);
  }
  if (ex.error_code || ex.error_message) {
    items.push(["Error", `${ex.error_code || ""} ${ex.error_message || ""}`.trim()]);
  }
  return (
    <details className="disclosure report-details" id="execution-section" tabIndex={-1}>
      <summary>Execution details</summary>
      <div className="disclosure-body">
        <dl className="details-grid">
          {items.map(([k, v]) => (
            <div key={k} className="details-item">
              <dt>{k}</dt>
              <dd>{v}</dd>
            </div>
          ))}
        </dl>
      </div>
    </details>
  );
}

export function InvestigationReport({
  inv,
  corpusLabel,
}: {
  inv: Investigation;
  corpusLabel?: string | null;
}) {
  const [activeRef, setActiveRef] = useState<string | null>(null);
  const external = inv.execution.source === "external";

  function jumpToEvidence(ref: string) {
    setActiveRef(ref);
    if (ref.startsWith("chunk:")) scrollToId(`chunk-${ref.slice(6)}`);
    else if (ref.startsWith("judge:")) scrollToId(`judge-${ref.slice(6)}`);
    else if (ref.startsWith("execution:")) {
      const d = document.getElementById("execution-section") as HTMLDetailsElement | null;
      if (d) d.open = true;
      scrollToId("execution-section");
    } else if (ref.startsWith("retrieval")) scrollToId("retrieval-section");
  }

  return (
    <div className="report">
      <div className="report-top">
        <div className="report-id">
          <span className="muted small">Execution</span>
          <code title={inv.execution.execution_id}>{inv.execution.execution_id}</code>
        </div>
        {external ? <StatusBadge status="external" tone="info" label="External trace" /> : null}
      </div>
      <nav className="jump-nav" aria-label="Report sections">
        {REPORT_SECTIONS.filter((s) => inv.diagnosis || s.id !== "next-step").map((s) => (
          <a
            key={s.id}
            href={`#${s.id}`}
            className="jump-link"
            onClick={(e) => {
              e.preventDefault();
              if (s.id === "execution-section") {
                const d = document.getElementById(s.id) as HTMLDetailsElement | null;
                if (d) d.open = true;
              }
              scrollToId(s.id);
            }}
          >
            {s.label}
          </a>
        ))}
      </nav>
      <Verdict inv={inv} />
      <NextStep inv={inv} />
      <AnswerVsEvidence inv={inv} />
      <ChunkTable inv={inv} activeRef={activeRef} />
      <Judges inv={inv} activeRef={activeRef} />
      <RuleDecision inv={inv} onJump={jumpToEvidence} />
      <Waterfall inv={inv} />
      <Details inv={inv} corpusLabel={corpusLabel} />
      <RawToggle label="View raw execution JSON" data={inv} />
    </div>
  );
}
