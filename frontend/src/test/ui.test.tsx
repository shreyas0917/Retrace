import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import {
  EmptyState,
  ErrorBanner,
  LoadingState,
  StatusBadge,
} from "../components/ui";
import { InvestigateView } from "../views/InvestigateView";
import { OperationsView } from "../views/OperationsView";
import { EvaluationsView } from "../views/EvaluationsView";

vi.mock("../api", () => ({
  API_BASE: "http://localhost:8000",
  apiGet: vi.fn(async (path: string) => {
    if (path === "/api/v1/corpora") return { corpora: [] };
    if (path.startsWith("/api/v1/ops/summary")) {
      return {
        ready: true,
        readiness_status: "ok",
        dependencies: { postgres: "ok", chroma: "ok" },
        metrics: {
          durable: false,
          source: "in-memory",
          durable_available: true,
          durable_window: {
            available: true,
            source: "postgres",
            window_minutes: 1440,
            event_count: 42,
            http_latency: { count: 3, p50_ms: 8, p95_ms: 12, p99_ms: 20, max_ms: 25 },
            requests_total: 3,
            requests_5xx: 0,
            request_error_rate: 0,
            tokens: { prompt: 120, completion: 40, total: 160 },
            cost_usd: 0.000128,
          },
          derived: {},
          http_latency: { p95_ms: 12 },
          counters_sample: { "http.requests_total": 3 },
        },
        signals: {
          alert_count: 0,
          signals: [
            {
              signal: "request_error_rate",
              actual: 0,
              threshold: 0.05,
              status: "OK",
            },
            {
              signal: "retrieval_miss_rate",
              actual: null,
              threshold: 0.1,
              status: "INSUFFICIENT_DATA",
            },
          ],
        },
      };
    }
    if (path === "/api/v1/runbooks") {
      return { by_signal: {}, runbooks: [], by_failure_code: {} };
    }
    if (path.startsWith("/api/v1/investigations/")) {
      return {
        execution: {
          execution_id: "exec-1",
          request_id: "req-1",
          corpus_version_id: "cv-1",
          retrieval_trace_id: "rt-1",
          query: "How much PTO?",
          status: "COMPLETED",
          error_code: null,
          error_message: null,
          abstained: false,
          abstention_kind: null,
          answer: "1.25 days per month",
          top_k: 5,
          generation: {
            model: "fake",
            temperature: 0,
            prompt_version: "generator.v1",
            latency_ms: 10,
            prompt_tokens: 1,
            completion_tokens: 1,
            total_tokens: 2,
          },
          latency_ms: { retrieval: 5, generation: 10, total: 15 },
        },
        diagnosis: {
          diagnosis_id: "d1",
          failure_code: "RETRIEVAL_MISS",
          rule_id: "R11",
          layer: "retrieval",
          confidence: "high",
          secondary_codes: [],
          recommendation_code: null,
          evidence_refs: ["chunk:c1", "retrieval:gold_miss"],
          taxonomy_version: "1.0",
        },
        rule: {
          rule_id: "R11",
          result: "RETRIEVAL_MISS",
          layer: "retrieval",
          conditions: ["gold_ids present", "gold_hit == false"],
          summary: "Gold miss",
        },
        failure: {
          code: "RETRIEVAL_MISS",
          description: "Gold miss",
          layer: "retrieval",
          runbook: "retrieval-miss-rate",
        },
        retrieval: {
          chunks: [
            {
              chunk_id: "c2",
              document_id: "d",
              source_name: "refund.md",
              rank: 1,
              score: 0.1,
              text: "refund policy",
              relevance: null,
              evidence_status: "distractor",
              is_gold_expected: false,
            },
            {
              chunk_id: "c1",
              document_id: null,
              source_name: null,
              rank: null,
              score: null,
              text: null,
              relevance: null,
              evidence_status: "missing",
              is_gold_expected: true,
            },
          ],
          gold_ids: ["c1"],
          gold_hit: false,
          gold_recall_at_k: 0,
          n_retrieved: 1,
          context_sufficient: null,
          irrelevant_frac: null,
        },
        judges: [
          {
            judge_type: "relevance",
            status: "ok",
            schema_ok: true,
            model: "fake",
            prompt_version: "rel.v1",
            latency_ms: 4,
            attempts: 1,
            result: { context_sufficient: false, item_count: 1 },
            output: {},
          },
        ],
        evidence: [
          { evidence_type: "chunk", ref: "chunk:c1", payload: {} },
          {
            evidence_type: "signal",
            ref: "retrieval:gold_miss",
            payload: {},
          },
        ],
        timeline: [
          {
            operation: "retrieval",
            status: "ok",
            duration_ms: 5,
            id: "rt-1",
          },
          {
            operation: "diagnosis",
            status: "RETRIEVAL_MISS",
            duration_ms: 2,
            id: "d1",
          },
        ],
        why: {
          engine: "deterministic_rule_engine",
          note: "Diagnosis is produced by ordered rules.",
          signals_used: { gold_hit: false },
          rule: {
            rule_id: "R11",
            result: "RETRIEVAL_MISS",
            layer: "retrieval",
            conditions: ["gold_hit == false"],
            summary: "Gold miss",
          },
        },
      };
    }
    throw new Error(`unexpected GET ${path}`);
  }),
  apiPost: vi.fn(),
  apiGetText: vi.fn(async () => "# Runbook\nsteps"),
}));

describe("ui primitives", () => {
  it("renders loading empty and error states", () => {
    render(
      <>
        <LoadingState label="Loading investigation..." />
        <EmptyState>No execution selected.</EmptyState>
        <ErrorBanner message="Unable to load experiment." />
        <StatusBadge status="INSUFFICIENT_DATA" />
      </>,
    );
    expect(screen.getByText("Loading investigation...")).toBeInTheDocument();
    expect(screen.getByText("No execution selected.")).toBeInTheDocument();
    expect(screen.getByText("Unable to load experiment.")).toBeInTheDocument();
    expect(screen.getByText("INSUFFICIENT_DATA")).toBeInTheDocument();
  });
});

describe("InvestigateView", () => {
  it("renders diagnosis rule evidence retrieval and judges", async () => {
    render(
      <InvestigateView
        apiKey="test"
        executionId="exec-1"
        onExecutionIdChange={() => undefined}
      />,
    );
    expect(
      (await screen.findAllByText("RETRIEVAL_MISS", {}, { timeout: 3000 }))
        .length,
    ).toBeGreaterThan(0);
    expect(screen.getAllByText("R11").length).toBeGreaterThan(0);
    expect(screen.getByText("Retrieval evidence")).toBeInTheDocument();
    expect(screen.getByText("refund policy")).toBeInTheDocument();
    expect(screen.getByText("missing")).toBeInTheDocument();
    expect(screen.getByText("relevance")).toBeInTheDocument();
    expect(screen.getByText("chunk:c1")).toBeInTheDocument();
    expect(
      screen.getByText("Diagnosis is produced by ordered rules."),
    ).toBeInTheDocument();
    expect(document.querySelector(".failure-code")?.textContent).toBe(
      "RETRIEVAL_MISS",
    );
    expect(document.querySelector(".rule-id")?.textContent).toBe("R11");
  });

  it("shows empty state when no execution", () => {
    render(
      <InvestigateView
        apiKey="test"
        executionId=""
        onExecutionIdChange={() => undefined}
      />,
    );
    expect(screen.getByText("No execution selected.")).toBeInTheDocument();
  });
});

describe("OperationsView", () => {
  it("renders metrics and signal statuses", async () => {
    render(<OperationsView apiKey="test" />);
    expect(await screen.findByText("request_error_rate")).toBeInTheDocument();
    expect(screen.getByText("OK")).toBeInTheDocument();
    expect(screen.getByText("INSUFFICIENT_DATA")).toBeInTheDocument();
    expect(screen.getByText(/source: postgres/i)).toBeInTheDocument();
    expect(screen.getByText("20 ms")).toBeInTheDocument();
  });
});

describe("EvaluationsView", () => {
  it("shows empty evaluation state", () => {
    render(
      <EvaluationsView apiKey="test" onOpenExecution={() => undefined} />,
    );
    expect(
      screen.getByText(/No evaluation loaded/i),
    ).toBeInTheDocument();
  });
});
