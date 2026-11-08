import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { EvaluationsView } from "../views/EvaluationsView";
import { CaseTable } from "../components/EvalParts";
import { makeCase } from "./fixtures";

const api = vi.hoisted(() => ({ apiGet: vi.fn(), apiPost: vi.fn() }));

vi.mock("../api", async (orig) => ({
  ...(await orig<typeof import("../api")>()),
  apiGet: api.apiGet,
  apiPost: api.apiPost,
}));

describe("Evaluations suite picker", () => {
  it("offers live_v1 but never runs a suite just because it was selected", () => {
    render(<EvaluationsView apiKey="" onOpenExecution={() => undefined} />);
    const select = screen.getByLabelText("Suite") as HTMLSelectElement;
    expect(Array.from(select.options).map((o) => o.value)).toContain("live_v1");
    fireEvent.change(select, { target: { value: "live_v1" } });
    expect(select.value).toBe("live_v1");
    expect(api.apiPost).not.toHaveBeenCalled();
    expect(api.apiGet).not.toHaveBeenCalled();
    expect(screen.getByText(/No evaluation loaded/)).toBeInTheDocument();
  });
});

describe("CaseTable", () => {
  it("lists failures first, filters by search and links to Investigate", () => {
    const onOpen = vi.fn();
    render(
      <CaseTable
        cases={[makeCase("a_pass", true), makeCase("b_fail", false)]}
        onOpenExecution={onOpen}
      />,
    );
    const rows = screen.getAllByRole("row").slice(1);
    expect(rows[0]).toHaveTextContent("b_fail");
    fireEvent.change(screen.getByLabelText("Search cases"), { target: { value: "a_pass" } });
    expect(screen.getAllByRole("row")).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: "Investigate case a_pass" }));
    expect(onOpen).toHaveBeenCalledWith("exec-a_pass");
  });
});
