import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { InvestigateView } from "../views/InvestigateView";

// An external trace (POST /api/v1/traces) has no Retrace corpus version.
vi.mock("../api", () => ({
  API_BASE: "http://localhost:8000",
  apiGet: vi.fn(async (path: string) => {
    if (path === "/api/v1/corpora") return [];
    if (path.startsWith("/api/v1/investigations/")) {
      return {
        source: "external",
        execution: {
          execution_id: "ext-1",
          request_id: "req-ext",
          corpus_version_id: null,
          source: "external",
          retrieval_trace_id: null,
          query: "How much PTO do contractors accrue?",
          status: "ABSTAINED",
          error_code: null,
          error_message: null,
          abstained: true,
          abstention_kind: "ABSTAINED",
          answer: "I don't know.",
          top_k: 0,
          generation: {
            model: "gpt-4.1-mini",
            temperature: null,
            prompt_version: null,
            latency_ms: null,
            prompt_tokens: null,
            completion_tokens: null,
            total_tokens: null,
          },
          latency_ms: { retrieval: null, generation: null, total: null },
        },
        diagnosis: null,
        rule: null,
        failure: null,
        retrieval: {
          chunks: [],
          gold_ids: [],
          gold_hit: null,
          gold_recall_at_k: null,
          n_retrieved: 0,
          context_sufficient: null,
          irrelevant_frac: null,
        },
        judges: [],
        evidence: [],
        timeline: [],
        why: { engine: "rules", note: "", signals_used: {}, rule: null },
      };
    }
    throw new Error(`unexpected GET ${path}`);
  }),
  apiPost: vi.fn(),
  apiGetText: vi.fn(),
}));

describe("InvestigateView with an external trace", () => {
  it("labels the missing corpus instead of rendering a blank id", async () => {
    render(
      <InvestigateView
        apiKey="test"
        executionId="ext-1"
        onExecutionIdChange={() => undefined}
      />,
    );
    expect(await screen.findByText("External trace")).toBeInTheDocument();
    expect(
      screen.getByText(/Sent from another RAG app via POST \/api\/v1\/traces/),
    ).toBeInTheDocument();
  });
});
