import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import Watchlist from "@/components/Watchlist";

describe("Watchlist", () => {
  it("renders all 4 instruments", () => {
    const onSelect = vi.fn();
    render(<Watchlist onSelect={onSelect} selected="MNQ" />);

    expect(screen.getByText("MNQ")).toBeTruthy();
    expect(screen.getByText("MYM")).toBeTruthy();
    expect(screen.getByText("MES")).toBeTruthy();
    expect(screen.getByText("MBT")).toBeTruthy();
  });

  it("shows instrument names", () => {
    const onSelect = vi.fn();
    render(<Watchlist onSelect={onSelect} selected="MNQ" />);

    expect(screen.getByText("Micro Nasdaq")).toBeTruthy();
    expect(screen.getByText("Micro Dow")).toBeTruthy();
  });

  it("calls onSelect when row clicked", () => {
    const onSelect = vi.fn();
    render(<Watchlist onSelect={onSelect} selected="MNQ" />);

    fireEvent.click(screen.getByText("MYM"));
    expect(onSelect).toHaveBeenCalledWith("MYM");
  });

  it("highlights selected symbol", () => {
    const onSelect = vi.fn();
    const { container } = render(<Watchlist onSelect={onSelect} selected="MES" />);

    // MES row should have a highlight background
    const rows = container.querySelectorAll("tr[style]");
    const mesRow = Array.from(rows).find((r) => r.textContent?.includes("MES"));
    expect(mesRow).toBeTruthy();
  });

  it("displays win rate in signals section", () => {
    const onSelect = vi.fn();
    render(<Watchlist onSelect={onSelect} selected="MNQ" />);

    expect(screen.getByText("Win Rate")).toBeTruthy();
    expect(screen.getByText("56.7%")).toBeTruthy();
  });

  it("handles price ticks without NaN (C3 fix)", async () => {
    vi.useFakeTimers();
    const onSelect = vi.fn();
    const { container } = render(<Watchlist onSelect={onSelect} selected="MNQ" />);

    // Advance timer to trigger price update
    act(() => {
      vi.advanceTimersByTime(2500);
    });

    // Check no NaN appears in the rendered output
    const text = container.textContent || "";
    expect(text).not.toContain("NaN");
    expect(text).not.toContain("Infinity");

    vi.useRealTimers();
  });
});
