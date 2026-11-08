import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { InvestigationReport, bestEvidence, describeCondition } from "../components/InvestigationReport";
import { makeInvestigation } from "./fixtures";

vi.mock("../api", async (orig) => ({
  ...(await orig<typeof import("../api")>()),
  apiGetText: vi.fn(async () => "# Retrieval misses\n\n1. Check the index."),
}));

describe("InvestigationReport", () => {
  it("leads with the verdict, code, rule and calibrated confidence", () => {
    render(<InvestigationReport inv={makeInvestigation()} />);
    const verdict = document.getElementById("verdict")!;
    expect(within(verdict).getByRole("heading", { level: 2 })).toHaveTextContent(
      "The answer contradicts the retrieved documents",
    );
    expect(within(verdict).getByText("GENERATION_CONTRADICTION")).toBeInTheDocument();
    expect(within(verdict).getByText("R30")).toBeInTheDocument();
    expect(within(verdict).getByText("50%")).toBeInTheDocument();
    const stages = within(verdict).getByRole("list", { name: "Pipeline stages" });
    expect(within(stages).getAllByText("Broke here")).toHaveLength(1);
    expect(within(stages).getAllByText("Not assessed")).toHaveLength(1);
  });

  it("shows NLI faithfulness per-claim rows and the truncation flag", () => {
    render(<InvestigationReport inv={makeInvestigation()} />);
    const card = document.getElementById("judge-faithfulness")!;
    const table = within(card).getByRole("table");
    expect(within(table).getByText("Full-time employees accrue 3 days of PTO per month.")).toBeInTheDocument();
    expect(within(table).getByText("handbook:c000")).toBeInTheDocument();
    expect(within(table).getByText("0.04")).toBeInTheDocument();
    expect(within(table).getByText("Contradicted")).toBeInTheDocument();
    expect(within(card).getByRole("note")).toHaveTextContent(/Truncated:.*2000.*3 least-similar/);
  });

  it("puts the answer beside the best evidence chunk", () => {
    const inv = makeInvestigation();
    const best = bestEvidence(inv);
    expect(best?.kind).toBe("chunk");
    if (best?.kind === "chunk") expect(best.chunk.chunk_id).toBe("handbook:c000");
    render(<InvestigationReport inv={inv} />);
    const answer = document.getElementById("answer")!;
    expect(within(answer).getByText("Full-time employees accrue 1.25 days of PTO per month.")).toBeInTheDocument();
  });

  it("highlights a chunk when its evidence reference is clicked", () => {
    render(<InvestigationReport inv={makeInvestigation()} />);
    fireEvent.click(screen.getByRole("button", { name: "Show evidence chunk:handbook:c000" }));
    expect(document.getElementById("chunk-handbook:c000")).toHaveClass("row-active");
  });

  it("renders a next step and loads the runbook inline as Markdown", async () => {
    const inv = makeInvestigation({
      failure: { code: "RETRIEVAL_MISS", description: null, layer: "retrieval", runbook: "retrieval-miss-rate" },
    });
    render(<InvestigationReport inv={inv} />);
    expect(screen.getByRole("heading", { name: "Tighten the generator" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Read the runbook/ }));
    expect(await screen.findByRole("heading", { name: "Retrieval misses" })).toBeInTheDocument();
  });

  it("marks every stage unknown for an infrastructure failure", () => {
    const base = makeInvestigation();
    const inv = makeInvestigation({
      diagnosis: { ...base.diagnosis!, failure_code: "EVAL_MODEL_TIMEOUT", rule_id: "R00" },
    });
    render(<InvestigationReport inv={inv} />);
    const stages = screen.getByRole("list", { name: "Pipeline stages" });
    expect(within(stages).getAllByText("Unknown")).toHaveLength(4);
  });

  it("renders an external trace without empty or undefined fields", () => {
    const base = makeInvestigation();
    const inv = makeInvestigation({
      execution: {
        ...base.execution,
        source: "external",
        corpus_version_id: null,
        retrieval_trace_id: null,
        generation: {
          model: null,
          temperature: null,
          prompt_version: null,
          latency_ms: null,
          prompt_tokens: null,
          completion_tokens: null,
          total_tokens: null,
        },
        latency_ms: { retrieval: null, generation: null, total: null },
      },
    });
    const { container } = render(<InvestigationReport inv={inv} />);
    expect(screen.getByText("External trace")).toBeInTheDocument();
    expect(screen.getByText("None (external trace)")).toBeInTheDocument();
    const visible = container.cloneNode(true) as HTMLElement;
    visible.querySelectorAll(".raw-json").forEach((el) => el.remove());
    expect(visible.textContent).not.toMatch(/undefined|NaN|null/);
  });

  it("describes rule conditions in words", () => {
    expect(describeCondition("context_sufficient == false")).toMatchObject({
      label: "Context sufficient",
      op: "is",
      value: "No",
    });
    expect(describeCondition("faithfulness_score < TAU_FAITHFUL")?.value).toBe("the faithfulness threshold");
    expect(describeCondition("gold_ids present")).toBeNull();
  });
});
