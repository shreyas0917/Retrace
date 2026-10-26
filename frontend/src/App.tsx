import { useCallback, useEffect, useState } from "react";
import { API_BASE, fetchAuthState, logout } from "./api";
import { LoginView } from "./views/LoginView";
import { InvestigateView } from "./views/InvestigateView";
import { EvaluationsView } from "./views/EvaluationsView";
import { ExperimentsView } from "./views/ExperimentsView";
import { OperationsView } from "./views/OperationsView";
import type { NavId } from "./types";

// Views receive an empty key: requests authenticate with the HttpOnly
// session cookie, so no credential is ever baked into the bundle.
const SESSION_AUTH_KEY = "";

type AuthStatus = "checking" | "anonymous" | "authenticated";

const NAV: Array<{ id: NavId; label: string; desc: string }> = [
  {
    id: "investigate",
    label: "Investigate",
    desc: "Trace and diagnose a RAG execution.",
  },
  {
    id: "evaluations",
    label: "Evaluations",
    desc: "Run and inspect reproducible evaluation suites.",
  },
  {
    id: "experiments",
    label: "Experiments",
    desc: "Compare experiment results against accepted baselines.",
  },
  {
    id: "operations",
    label: "Operations",
    desc: "Inspect system health, metrics, signals, and runbooks.",
  },
];

export default function App() {
  const [nav, setNav] = useState<NavId>("investigate");
  const [auth, setAuth] = useState<AuthStatus>("checking");
  const [health, setHealth] = useState<"checking" | "ok" | "error">("checking");
  const [executionId, setExecutionId] = useState("");
  const [navOpen, setNavOpen] = useState(false);
  const apiKey = SESSION_AUTH_KEY;

  const refreshAuth = useCallback(async () => {
    try {
      const state = await fetchAuthState();
      setAuth(state.authenticated ? "authenticated" : "anonymous");
    } catch {
      setAuth("anonymous");
    }
  }, []);

  useEffect(() => {
    void refreshAuth();
  }, [refreshAuth]);

  async function signOut() {
    try {
      await logout();
    } finally {
      setAuth("anonymous");
      setNavOpen(false);
    }
  }

  useEffect(() => {
    let cancelled = false;
    async function ping() {
      try {
        const res = await fetch(`${API_BASE}/health/live`);
        if (!cancelled) setHealth(res.ok ? "ok" : "error");
      } catch {
        if (!cancelled) setHealth("error");
      }
    }
    void ping();
    const t = window.setInterval(ping, 20000);
    return () => {
      cancelled = true;
      window.clearInterval(t);
    };
  }, []);

  function openExecution(id: string) {
    setExecutionId(id);
    setNav("investigate");
    setNavOpen(false);
  }

  const active = NAV.find((n) => n.id === nav);

  if (auth !== "authenticated") {
    return auth === "checking" ? (
      <div className="login-shell">
        <div className="login-card panel login-checking">Checking session…</div>
      </div>
    ) : (
      <LoginView apiBase={API_BASE} onAuthenticated={() => setAuth("authenticated")} />
    );
  }

  const healthLabel =
    health === "ok"
      ? "API Connected"
      : health === "checking"
        ? "Checking…"
        : "API Down";

  return (
    <div className="app-shell">
      <aside className={navOpen ? "app-sidebar open" : "app-sidebar"} aria-label="Primary">
        <div className="sidebar-brand">
          <div className="brand">Retrace</div>
          <div className="brand-tag">AI Reliability</div>
        </div>
        <nav className="side-nav" aria-label="Main">
          {NAV.map((item) => (
            <button
              key={item.id}
              type="button"
              className={nav === item.id ? "side-nav-item active" : "side-nav-item"}
              aria-current={nav === item.id ? "page" : undefined}
              onClick={() => {
                setNav(item.id);
                setNavOpen(false);
              }}
            >
              {item.label}
            </button>
          ))}
        </nav>
        <div className="sidebar-foot">
          <div className="sidebar-meta">
            <span className="mono">v1.0.0</span>
            <span
              className={`status-dot ${health === "ok" ? "ok" : health === "error" ? "error" : ""}`}
              title="GET /health/live"
            >
              {healthLabel}
            </span>
          </div>
          <div className="sidebar-session">
            <span className="status-dot ok" title="HttpOnly session cookie">
              Signed in
            </span>
            <button
              type="button"
              className="secondary logout-button"
              onClick={() => void signOut()}
            >
              Log out
            </button>
          </div>
        </div>
      </aside>

      {navOpen ? (
        <button
          type="button"
          className="sidebar-backdrop"
          aria-label="Close navigation"
          onClick={() => setNavOpen(false)}
        />
      ) : null}

      <div className="app-main">
        <div className="main-toolbar">
          <button
            type="button"
            className="secondary menu-toggle"
            aria-label="Open navigation"
            onClick={() => setNavOpen(true)}
          >
            Menu
          </button>
          <div className="toolbar-title">
            <span className="toolbar-page">{active?.label}</span>
            <span className="toolbar-desc">{active?.desc}</span>
          </div>
        </div>

        <div className="main-content">
          {nav === "investigate" && (
            <InvestigateView
              apiKey={apiKey}
              executionId={executionId}
              onExecutionIdChange={setExecutionId}
            />
          )}
          {nav === "evaluations" && (
            <EvaluationsView apiKey={apiKey} onOpenExecution={openExecution} />
          )}
          {nav === "experiments" && (
            <ExperimentsView apiKey={apiKey} onOpenExecution={openExecution} />
          )}
          {nav === "operations" && <OperationsView apiKey={apiKey} />}
        </div>
      </div>
    </div>
  );
}
