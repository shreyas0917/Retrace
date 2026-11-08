import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { OverviewView } from "../views/OverviewView";

vi.mock("../api", () => ({
  API_BASE: "http://localhost:8000",
  apiGet: vi.fn(async (path: string) => {
    if (path.startsWith("/api/v1/ops/summary")) {
      return {
        ready: true,
        readiness_status: "ok",
        dependencies: { postgres: "ok", chroma: "ok" },
        metrics: {
          durable: false,
          derived: {},
          http_latency: null,
          counters_sample: {},
          durable_window: {
            available: true,
            generation_attempts: 210,
            requests_total: 4232,
            request_error_rate: 0.0014,
            http_latency: { p95_ms: 128 },
          },
        },
        signals: { alert_count: 0, signals: [] },
      };
    }
    if (path.startsWith("/api/v1/metrics/durable")) {
      return {
        durable: true,
        counters: {
          "diagnosis.code.RETRIEVAL_MISS": 163,
          "diagnosis.code.OK_GROUNDED": 202,
          "diagnosis.code.GENERATION_HALLUCINATION": 98,
          "generation.attempts": 210,
        },
      };
    }
    if (path.startsWith("/api/v1/experiments")) {
      return {
        experiments: [
          {
            experiment_id: "exp-1",
            suite_id: "heldout_v1",
            suite_version: "1.0.0",
            status: "COMPLETED",
            created_at: "2026-10-20T10:00:00Z",
          },
        ],
      };
    }
    throw new Error(`unexpected GET ${path}`);
  }),
  apiPost: vi.fn(),
  apiGetText: vi.fn(),
}));

describe("OverviewView", () => {
  it("shows a plain-English health summary and real data", async () => {
    render(<OverviewView apiKey="test" onNavigate={() => undefined} />);
    expect(
      await screen.findByText(/your rag system is healthy/i),
    ).toBeInTheDocument();
    expect(screen.getByText("Answers generated")).toBeInTheDocument();
    // Failure breakdown uses friendly titles; OK outcomes are excluded.
    expect(
      screen.getByText("The system retrieved the wrong information"),
    ).toBeInTheDocument();
    expect(screen.queryByText(/OK_GROUNDED/)).not.toBeInTheDocument();
    // Recent evaluation run from the experiments endpoint.
    expect(screen.getByText("heldout_v1")).toBeInTheDocument();
  });

  it("offers the primary investigate action", async () => {
    const onNavigate = vi.fn();
    render(<OverviewView apiKey="test" onNavigate={onNavigate} />);
    const cta = await screen.findByRole("button", {
      name: /investigate an ai answer/i,
    });
    cta.click();
    expect(onNavigate).toHaveBeenCalledWith("investigate");
  });
});
