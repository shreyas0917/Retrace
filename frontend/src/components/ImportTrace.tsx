import { useState, type FormEvent } from "react";
import { apiPost } from "../api";
import { apiErrorLines, validateTraceText } from "../importTrace";
import exampleTrace from "../examples/contradictionTrace.json?raw";

type TraceResponse = {
  execution_id: string;
  warnings?: string[];
};

/**
 * Paste a trace from another RAG app, check it for obvious mistakes, send it
 * to POST /api/v1/traces and open the stored execution.
 */
export function ImportTrace({
  apiKey,
  onImported,
}: {
  apiKey: string;
  onImported: (executionId: string, warnings: string[]) => void;
}) {
  const [text, setText] = useState("");
  const [clientErrors, setClientErrors] = useState<string[]>([]);
  const [apiError, setApiError] = useState<{ summary: string; fields: string[] } | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (busy) return;
    setApiError(null);
    const check = validateTraceText(text);
    if (!check.ok) {
      setClientErrors(check.errors);
      return;
    }
    setClientErrors([]);
    setBusy(true);
    try {
      const res = await apiPost<TraceResponse>("/api/v1/traces", apiKey, check.trace);
      if (!res || !res.execution_id) {
        setApiError({ summary: "The API did not return an execution ID.", fields: [] });
        return;
      }
      onImported(res.execution_id, Array.isArray(res.warnings) ? res.warnings : []);
    } catch (err) {
      setApiError(apiErrorLines(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="import-trace" onSubmit={submit} aria-label="Import a trace">
      <div className="import-intro">
        <h2 className="import-title">Import a trace</h2>
        <p className="muted">
          Paste the question, the passages your retriever returned and the answer your model
          gave. Retrace stores it as an external trace, diagnoses it, and opens the result.
          The format is described in <code>docs/integrate.md</code>.
        </p>
      </div>
      <label className="import-field">
        Trace JSON
        <textarea
          className="mono import-textarea"
          value={text}
          onChange={(e) => {
            setText(e.target.value);
            if (clientErrors.length) setClientErrors([]);
          }}
          rows={16}
          spellCheck={false}
          placeholder={'{\n  "query": "…",\n  "retrieved_chunks": [{"chunk_id": "doc:c1", "text": "…"}],\n  "answer": "…"\n}'}
          aria-invalid={clientErrors.length > 0}
          aria-describedby={clientErrors.length ? "import-client-errors" : undefined}
        />
      </label>
      {clientErrors.length > 0 ? (
        <div className="error" role="alert" id="import-client-errors">
          <strong>Fix these before importing:</strong>
          <ul className="plain-list">
            {clientErrors.map((m) => (
              <li key={m}>{m}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {apiError ? (
        <div className="error" role="alert">
          <strong>The API rejected the trace: {apiError.summary}</strong>
          {apiError.fields.length ? (
            <ul className="plain-list">
              {apiError.fields.map((m, i) => (
                <li key={`${i}-${m}`}>
                  <code>{m}</code>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
      <div className="inline">
        <button type="submit" disabled={busy}>
          {busy ? "Importing and diagnosing…" : "Import and diagnose"}
        </button>
        <button
          type="button"
          className="secondary"
          onClick={() => {
            setText(exampleTrace.trim());
            setClientErrors([]);
            setApiError(null);
          }}
        >
          Load example
        </button>
        {text ? (
          <button
            type="button"
            className="secondary"
            onClick={() => {
              setText("");
              setClientErrors([]);
              setApiError(null);
            }}
          >
            Clear
          </button>
        ) : null}
      </div>
      <p className="muted small">
        The example is <code>examples/traces/contradiction.json</code>. Diagnosis can take a while
        when a judge model is involved.
      </p>
    </form>
  );
}
