import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { readExecutionParam, urlWithExecution } from "../deepLink";
import { makeInvestigation } from "./fixtures";
import { ThemeProvider } from "../theme";

describe("deep-link parsing", () => {
  it("reads ?execution=<id>", () => {
    expect(readExecutionParam("?execution=9e152598-988a-4a9b-ac04-2daf97133024")).toBe(
      "9e152598-988a-4a9b-ac04-2daf97133024",
    );
    expect(readExecutionParam("?foo=1&execution=ext-abc_1.2")).toBe("ext-abc_1.2");
    expect(readExecutionParam("?execution=%20abc%20")).toBe("abc");
  });

  it("ignores missing, empty or unsafe values", () => {
    expect(readExecutionParam("")).toBeNull();
    expect(readExecutionParam("?execution=")).toBeNull();
    expect(readExecutionParam("?execution=a/b")).toBeNull();
    expect(readExecutionParam("?execution=<script>")).toBeNull();
    expect(readExecutionParam(`?execution=${"a".repeat(200)}`)).toBeNull();
  });

  it("sets and clears the parameter, keeping others", () => {
    expect(urlWithExecution("http://x.test/?a=1", "e1")).toBe("/?a=1&execution=e1");
    expect(urlWithExecution("http://x.test/?execution=e1&a=1", null)).toBe("/?a=1");
    expect(urlWithExecution("http://x.test/#h", "e2")).toBe("/?execution=e2#h");
  });
});

const api = vi.hoisted(() => ({
  fetchAuthState: vi.fn(),
  login: vi.fn(),
  apiGet: vi.fn(),
}));

vi.mock("../api", async (orig) => ({
  ...(await orig<typeof import("../api")>()),
  fetchAuthState: api.fetchAuthState,
  login: api.login,
  logout: vi.fn(async () => undefined),
  apiGet: api.apiGet,
  apiPost: vi.fn(),
  apiGetText: vi.fn(async () => ""),
}));

describe("deep link through the login screen", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 200 })));
    window.history.replaceState(null, "", "/?execution=exec-nli");
    api.fetchAuthState.mockResolvedValue({ authenticated: false, method: null, expires_at: null });
    api.login.mockResolvedValue({ authenticated: true, expires_at: "", ttl_seconds: 60 });
    api.apiGet.mockImplementation(async (path: string) => {
      if (path === "/api/v1/corpora") return [];
      if (path === "/api/v1/investigations/exec-nli") return makeInvestigation();
      throw new Error(`unexpected GET ${path}`);
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    window.history.replaceState(null, "", "/");
  });

  it("opens the linked execution after sign-in and keeps the URL", async () => {
    const { default: App } = await import("../App");
    render(
      <ThemeProvider>
        <App />
      </ThemeProvider>,
    );
    expect(await screen.findByText(/After you sign in, Investigate opens execution/)).toBeInTheDocument();
    expect(window.location.search).toBe("?execution=exec-nli");

    fireEvent.change(screen.getByLabelText("API key"), { target: { value: "k" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(
      await screen.findByRole("heading", { name: "The answer contradicts the retrieved documents" }),
    ).toBeInTheDocument();
    expect(api.apiGet).toHaveBeenCalledWith("/api/v1/investigations/exec-nli", "");
    await waitFor(() => expect(window.location.search).toBe("?execution=exec-nli"));
  });
});
