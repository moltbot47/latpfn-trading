import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

// Need to mock console.error to prevent noise
beforeEach(() => {
  vi.spyOn(console, "error").mockImplementation(() => {});
});

// Dynamically import to avoid module-level React context issues
describe("App Error Boundary", () => {
  it("displays error message", async () => {
    const { default: ErrorPage } = await import("@/app/error");
    const error = new Error("Test error message");
    render(<ErrorPage error={error} reset={vi.fn()} />);

    expect(screen.getByText("[ERROR] Something went wrong")).toBeTruthy();
    expect(screen.getByText("Test error message")).toBeTruthy();
  });

  it("calls reset on retry click", async () => {
    const { default: ErrorPage } = await import("@/app/error");
    const reset = vi.fn();
    render(<ErrorPage error={new Error("fail")} reset={reset} />);

    fireEvent.click(screen.getByText("[ Retry ]"));
    expect(reset).toHaveBeenCalledOnce();
  });

  it("has home link", async () => {
    const { default: ErrorPage } = await import("@/app/error");
    render(<ErrorPage error={new Error("fail")} reset={vi.fn()} />);

    const homeLink = screen.getByText("[ Home ]");
    expect(homeLink.getAttribute("href")).toBe("/");
  });
});

describe("Terminal Error Boundary", () => {
  it("displays terminal-specific error", async () => {
    const { default: TerminalError } = await import("@/app/terminal/error");
    render(<TerminalError error={new Error("Chart crashed")} reset={vi.fn()} />);

    expect(screen.getByText("[ERROR] Terminal crashed")).toBeTruthy();
    expect(screen.getByText("Chart crashed")).toBeTruthy();
  });

  it("calls reset on retry click", async () => {
    const { default: TerminalError } = await import("@/app/terminal/error");
    const reset = vi.fn();
    render(<TerminalError error={new Error("fail")} reset={reset} />);

    fireEvent.click(screen.getByText("Retry"));
    expect(reset).toHaveBeenCalledOnce();
  });
});
