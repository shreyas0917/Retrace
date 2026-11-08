import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { ThemeToggle } from "../components/ThemeToggle";
import { ThemeProvider } from "../theme";

function renderToggle() {
  return render(
    <ThemeProvider>
      <ThemeToggle />
    </ThemeProvider>,
  );
}

describe("theme system", () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.removeAttribute("data-theme");
  });

  it("offers light, dark and system options", () => {
    renderToggle();
    expect(screen.getByLabelText("Light theme")).toBeInTheDocument();
    expect(screen.getByLabelText("Dark theme")).toBeInTheDocument();
    expect(screen.getByLabelText("System theme")).toBeInTheDocument();
  });

  it("applies and persists the chosen theme to the document root", () => {
    renderToggle();
    fireEvent.click(screen.getByLabelText("Dark theme"));
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    expect(localStorage.getItem("retrace-theme")).toBe("dark");
    expect(screen.getByLabelText("Dark theme")).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    fireEvent.click(screen.getByLabelText("Light theme"));
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
    expect(localStorage.getItem("retrace-theme")).toBe("light");
    expect(screen.getByLabelText("Light theme")).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("restores a saved preference on mount", () => {
    localStorage.setItem("retrace-theme", "light");
    renderToggle();
    expect(screen.getByLabelText("Light theme")).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
  });
});
