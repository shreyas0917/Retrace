import { useState, type FormEvent } from "react";
import { ApiError, login } from "../api";

type Props = {
  onAuthenticated: () => void;
  apiBase: string;
};

/**
 * One-time API key entry. The key is posted once to the backend, which
 * answers with an HttpOnly session cookie; the key itself is never stored
 * in the bundle, localStorage or React state after submission.
 */
export function LoginView({ onAuthenticated, apiBase }: Props) {
  const [apiKey, setApiKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const key = apiKey.trim();
    if (!key || busy) return;
    setBusy(true);
    setError(null);
    try {
      await login(key);
      setApiKey("");
      onAuthenticated();
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setError("That API key was not accepted.");
      } else if (err instanceof ApiError && err.status === 429) {
        setError("Too many attempts. Wait a minute and try again.");
      } else {
        setError(
          err instanceof Error ? err.message : "Unable to reach the API.",
        );
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-shell">
      <form className="login-card panel" onSubmit={submit} aria-label="Sign in">
        <div className="login-brand">
          <div className="brand">Retrace</div>
          <div className="brand-tag">AI Reliability</div>
        </div>
        <h1 className="login-title">Sign in to the console</h1>
        <p className="login-desc">
          Enter the operator API key once. The server issues a short-lived
          session cookie; the key is not stored in the browser.
        </p>
        <label className="login-field">
          API key
          <input
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            autoComplete="current-password"
            autoFocus
            required
            aria-label="API key"
            disabled={busy}
          />
        </label>
        {error ? (
          <div className="error" role="alert">
            {error}
          </div>
        ) : null}
        <button type="submit" disabled={busy || !apiKey.trim()}>
          {busy ? "Signing in…" : "Sign in"}
        </button>
        <div className="login-foot mono">API {apiBase}</div>
      </form>
    </div>
  );
}
