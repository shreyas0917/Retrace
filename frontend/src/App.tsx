import { useEffect, useState } from "react";
import { API_BASE } from "./api";
import { InvestigateView } from "./views/InvestigateView";
import { EvaluationsView } from "./views/EvaluationsView";
import { ExperimentsView } from "./views/ExperimentsView";
import { OperationsView } from "./views/OperationsView";
import type { NavId } from "./types";

const DEFAULT_KEY =
  import.meta.env.VITE_API_KEY ?? "dev-retrace-api-key-change-me";

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
  const [apiKey, setApiKey] = useState(DEFAULT_KEY);
  const [health, setHealth] = useState<"checking" | "ok" | "error">("checking");
  const [executionId, setExecutionId] = useState("");
  const [navOpen, setNavOpen] = useState(false);

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
            <span className="mono">v0.9.0</span>
            <span
              className={`status-dot ${health === "ok" ? "ok" : health === "error" ? "error" : ""}`}
              title="GET /health/live"
            >
              {healthLabel}
            </span>
          </div>
          <label className="api-key-field">
            API Key
            <input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              autoComplete="off"
              aria-label="API key"
            />
          </label>
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
