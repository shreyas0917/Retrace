import { useState } from "react";
import ReactMarkdown from "react-markdown";
import { apiGetText } from "../api";

/** Renders runbook Markdown as React elements (no raw HTML). */
export function MarkdownDoc({ text }: { text: string }) {
  return (
    <div className="runbook-md answer-md">
      <ReactMarkdown>{text}</ReactMarkdown>
    </div>
  );
}

/**
 * A disclosure that fetches GET /api/v1/runbooks/{slug} the first time it is
 * opened and renders it inline as Markdown.
 */
export function RunbookDisclosure({
  slug,
  label,
}: {
  slug: string;
  label?: string;
}) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const panelId = `runbook-${slug}`;

  async function toggle() {
    const next = !open;
    setOpen(next);
    if (next && text == null && !loading) {
      setLoading(true);
      setError("");
      try {
        const body = await apiGetText(`/api/v1/runbooks/${encodeURIComponent(slug)}`);
        setText(typeof body === "string" ? body : "");
      } catch (err) {
        setError(err instanceof Error ? err.message : "Unable to load the runbook.");
      } finally {
        setLoading(false);
      }
    }
  }

  return (
    <div className="runbook-disclosure">
      <button
        type="button"
        className="secondary small-btn"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => void toggle()}
      >
        {open ? "Hide runbook" : label || "Read the runbook"}
        <span className="muted mono runbook-slug">{slug}</span>
      </button>
      {open ? (
        <div id={panelId} className="runbook-panel">
          {loading ? <p className="muted small">Loading runbook…</p> : null}
          {error ? (
            <p className="error" role="alert">
              {error}
            </p>
          ) : null}
          {text != null && !loading ? (
            text.trim() ? (
              <MarkdownDoc text={text} />
            ) : (
              <p className="muted small">This runbook is empty.</p>
            )
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
