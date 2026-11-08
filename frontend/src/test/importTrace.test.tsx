import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api";
import { validateTraceText } from "../importTrace";
import { ImportTrace } from "../components/ImportTrace";
import { InvestigateView } from "../views/InvestigateView";
import { makeInvestigation } from "./fixtures";

const api = vi.hoisted(() => ({ apiGet: vi.fn(), apiPost: vi.fn() }));

vi.mock("../api", async (orig) => ({
  ...(await orig<typeof import("../api")>()),
  apiGet: api.apiGet,
  apiPost: api.apiPost,
  apiGetText: vi.fn(async () => ""),
}));

describe("client-side trace validation", () => {
  it("rejects text that is not JSON", () => {
    const r = validateTraceText("{query: nope");
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.errors[0]).toMatch(/not valid JSON/);
  });

  it("rejects non-objects and empty input", () => {
    expect(validateTraceText("[]").ok).toBe(false);
    expect(validateTraceText("   ").ok).toBe(false);
  });

  it("reports missing query, answer and retrieved_chunks", () => {
    const r = validateTraceText("{}");
    expect(r.ok).toBe(false);
    if (!r.ok) {
      expect(r.errors.join("\n")).toMatch(/Missing "query"/);
      expect(r.errors.join("\n")).toMatch(/Missing "answer"/);
      expect(r.errors.join("\n")).toMatch(/Missing "retrieved_chunks"/);
    }
  });

  it("reports chunks without chunk_id or text", () => {
    const r = validateTraceText(
      JSON.stringify({ query: "q", answer: null, retrieved_chunks: [{ text: "t" }, { chunk_id: "c" }, 5] }),
    );
    expect(r.ok).toBe(false);
    if (!r.ok) {
      expect(r.errors).toContain('Chunk 1 is missing "chunk_id".');
      expect(r.errors).toContain('Chunk 2 is missing "text".');
      expect(r.errors[2]).toMatch(/Chunk 3 must be an object/);
    }
  });

  it("accepts a null answer and an empty chunk list", () => {
    expect(validateTraceText(JSON.stringify({ query: "q", answer: null, retrieved_chunks: [] })).ok).toBe(true);
  });
});

describe("ImportTrace form", () => {
  beforeEach(() => {
    api.apiPost.mockReset();
    api.apiGet.mockReset();
  });

  it("shows client errors and does not call the API", () => {
    render(<ImportTrace apiKey="" onImported={() => undefined} />);
    fireEvent.change(screen.getByLabelText("Trace JSON"), { target: { value: "{ not json" } });
    fireEvent.click(screen.getByRole("button", { name: "Import and diagnose" }));
    expect(screen.getByRole("alert")).toHaveTextContent(/not valid JSON/);
    expect(api.apiPost).not.toHaveBeenCalled();
  });

  it("fills in the example trace", () => {
    render(<ImportTrace apiKey="" onImported={() => undefined} />);
    fireEvent.click(screen.getByRole("button", { name: "Load example" }));
    const value = (screen.getByLabelText("Trace JSON") as HTMLTextAreaElement).value;
    expect(JSON.parse(value).query).toBe("How much PTO do full-time employees accrue per month?");
  });

  it("shows API validation errors (Retrace envelope)", async () => {
    api.apiPost.mockRejectedValue(
      new ApiError("Request validation failed", 400, {
        error: {
          code: "INVALID_REQUEST",
          message: "Request validation failed",
          details: {
            errors: [{ loc: ["body", "retrieved_chunks", 0, "chunk_id"], msg: "String should match pattern" }],
          },
        },
      }),
    );
    render(<ImportTrace apiKey="" onImported={() => undefined} />);
    fireEvent.click(screen.getByRole("button", { name: "Load example" }));
    fireEvent.click(screen.getByRole("button", { name: "Import and diagnose" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Request validation failed (HTTP 400)");
    expect(within(alert).getByText("retrieved_chunks[0].chunk_id: String should match pattern")).toBeInTheDocument();
  });

  it("shows FastAPI 422 detail arrays", async () => {
    api.apiPost.mockRejectedValue(
      new ApiError("HTTP 422", 422, {
        detail: [{ loc: ["body", "abstained"], msg: "Input should be a valid boolean" }],
      }),
    );
    render(<ImportTrace apiKey="" onImported={() => undefined} />);
    fireEvent.click(screen.getByRole("button", { name: "Load example" }));
    fireEvent.click(screen.getByRole("button", { name: "Import and diagnose" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("(HTTP 422)");
    expect(within(alert).getByText("abstained: Input should be a valid boolean")).toBeInTheDocument();
  });

  it("opens the imported execution in Investigate on success", async () => {
    const inv = makeInvestigation({
      execution: { ...makeInvestigation().execution, execution_id: "ext-9", source: "external", corpus_version_id: null },
    });
    api.apiPost.mockResolvedValue({ execution_id: "ext-9", warnings: ["No gold_chunk_ids: retrieval-miss detection is unavailable."] });
    api.apiGet.mockImplementation(async (path: string) => {
      if (path === "/api/v1/corpora") return [];
      if (path === "/api/v1/investigations/ext-9") return inv;
      throw new Error(`unexpected GET ${path}`);
    });
    const onChange = vi.fn();
    render(<InvestigateView apiKey="" executionId="" onExecutionIdChange={onChange} />);
    fireEvent.click(screen.getByRole("tab", { name: "Import a trace" }));
    fireEvent.click(screen.getByRole("button", { name: "Load example" }));
    fireEvent.click(screen.getByRole("button", { name: "Import and diagnose" }));

    expect(
      await screen.findByRole("heading", { name: "The answer contradicts the retrieved documents" }),
    ).toBeInTheDocument();
    expect(api.apiPost).toHaveBeenCalledWith(
      "/api/v1/traces",
      "",
      expect.objectContaining({ query: "How much PTO do full-time employees accrue per month?" }),
    );
    expect(onChange).toHaveBeenCalledWith("ext-9");
    expect(screen.getByText("External trace")).toBeInTheDocument();
    expect(screen.getByText(/retrieval-miss detection is unavailable/)).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Run or load" })).toHaveAttribute("aria-selected", "true");
  });
});
