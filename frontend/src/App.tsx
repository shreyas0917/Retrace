import { useCallback, useEffect, useState, type ComponentType } from "react";
import { API_BASE, fetchAuthState, logout } from "./api";
import { LoginView } from "./views/LoginView";
import { OverviewView } from "./views/OverviewView";
import { InvestigateView } from "./views/InvestigateView";
import { EvaluationsView } from "./views/EvaluationsView";
import { ExperimentsView } from "./views/ExperimentsView";
import { OperationsView } from "./views/OperationsView";
import { ThemeToggle } from "./components/ThemeToggle";
import { ViewFade } from "./components/motion";
import {
  IconEvaluations,
  IconExperiments,
  IconInvestigate,
  IconLogo,
  IconMenu,
  IconOperations,
  IconOverview,
} from "./components/icons";
import type { NavId } from "./types";
import { readExecutionParam, syncExecutionUrl } from "./deepLink";

// Views receive an empty key: requests authenticate with the HttpOnly
// session cookie, so no credential is ever baked into the bundle.
const SESSION_AUTH_KEY = "";

type AuthStatus = "checking" | "anonymous" | "authenticated";

const NAV: Array<{
  id: NavId;
  label: string;
  sub: string;
  desc: string;
  Icon: ComponentType<{ "aria-hidden"?: boolean }>;
}> = [
  {
    id: "overview",
    label: "Overview",
    sub: "System health at a glance",
    desc: "Is your RAG system healthy, and what should you look at next?",
    Icon: IconOverview,
  },
  {
    id: "investigate",
    label: "Investigate",
    sub: "Why an answer went wrong",
    desc: "Trace one AI answer from question to diagnosis, with the evidence.",
    Icon: IconInvestigate,
  },
  {
    id: "evaluations",
    label: "Evaluations",
    sub: "Is it getting better or worse",
    desc: "Run reproducible tests and see whether the system passes.",
    Icon: IconEvaluations,
  },
  {
    id: "experiments",
    label: "Experiments",
    sub: "Compare against a baseline",
    desc: "Compare test runs against the accepted baseline to catch regressions.",
    Icon: IconExperiments,
  },
  {
    id: "operations",
    label: "Operations",
    sub: "Service health and signals",
    desc: "Dependency readiness, latency, error rates, signals, and runbooks.",
    Icon: IconOperations,
  },
];

export default function App() {
  // `?execution=<id>` deep link, parsed once at start-up. The URL is left
  // untouched while signed out, so the link survives the login screen.
  const [deepLinkId] = useState(() => readExecutionParam(window.location.search));
  const [nav, setNav] = useState<NavId>(() => (deepLinkId ? "investigate" : "overview"));
  const [auth, setAuth] = useState<AuthStatus>("checking");
  const [health, setHealth] = useState<"checking" | "ok" | "error">("checking");
  const [executionId, setExecutionId] = useState(deepLinkId || "");
  const [navOpen, setNavOpen] = useState(false);
  const apiKey = SESSION_AUTH_KEY;

  // Keep the URL in sync with the open execution once signed in.
  useEffect(() => {
    if (auth !== "authenticated") return;
    if (nav === "investigate" && executionId) syncExecutionUrl(executionId);
    else syncExecutionUrl(null, true);
  }, [auth, nav, executionId]);

  // Back/forward between executions.
  useEffect(() => {
    function onPop() {
      const id = readExecutionParam(window.location.search);
      if (id) {
        setExecutionId(id);
        setNav("investigate");
      }
    }
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

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

  function goTo(id: NavId) {
    setNav(id);
    setNavOpen(false);
  }

  function openExecution(id: string) {
    setExecutionId(id);
    setNav("investigate");
    setNavOpen(false);
  }

  const active = NAV.find((n) => n.id === nav);

  if (auth !== "authenticated") {
    return (
      <>
        <div className="login-topbar">
          <ThemeToggle />
        </div>
        {auth === "checking" ? (
          <div className="login-shell">
            <div className="login-card panel login-checking">
              Checking session…
            </div>
          </div>
        ) : (
          <LoginView
            apiBase={API_BASE}
            pendingExecution={deepLinkId}
            onAuthenticated={() => setAuth("authenticated")}
          />
        )}
      </>
    );
  }

  const healthLabel =
    health === "ok"
      ? "Connected"
      : health === "checking"
        ? "Checking…"
        : "API down";

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <aside
        className={navOpen ? "app-sidebar open" : "app-sidebar"}
        aria-label="Primary"
      >
        <div className="sidebar-brand">
          <span className="brand-mark" aria-hidden="true">
            <IconLogo />
          </span>
          <span className="brand-text">
            <span className="brand">Retrace</span>
            <span className="brand-tag">AI answer reliability</span>
          </span>
        </div>
        <nav className="side-nav" aria-label="Main">
          {NAV.map((item) => {
            const ItemIcon = item.Icon;
            return (
              <button
                key={item.id}
                type="button"
                className={
                  nav === item.id ? "side-nav-item active" : "side-nav-item"
                }
                aria-current={nav === item.id ? "page" : undefined}
                onClick={() => goTo(item.id)}
              >
                <span className="side-nav-label">
                  <ItemIcon aria-hidden /> {item.label}
                </span>
                <span className="side-nav-sub">{item.sub}</span>
              </button>
            );
          })}
        </nav>
        <div className="sidebar-foot">
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
          <div className="sidebar-meta">
            <span className="mono">v1.0.0</span>
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
        <header className="app-header">
          <button
            type="button"
            className="secondary menu-toggle"
            aria-label="Open navigation"
            onClick={() => setNavOpen(true)}
          >
            <IconMenu aria-hidden />
          </button>
          <div className="header-title">
            <span className="header-page">{active?.label}</span>
            <span className="header-desc">{active?.desc}</span>
          </div>
          <div className="header-actions">
            <span
              className={`health-pill ${health === "ok" ? "ok" : health === "error" ? "error" : "checking"}`}
              title="GET /health/live — backend process reachable"
            >
              {healthLabel}
            </span>
            <ThemeToggle />
          </div>
        </header>

        <main className="main-content" id="main" tabIndex={-1}>
          <ViewFade viewKey={nav}>
            {nav === "overview" && (
              <OverviewView apiKey={apiKey} onNavigate={goTo} />
            )}
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
          </ViewFade>
        </main>
      </div>
    </div>
  );
}
