import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";

// Mock lightweight-charts before importing TVChart
vi.mock("lightweight-charts", () => ({
  createChart: vi.fn(() => ({
    addSeries: vi.fn(() => ({
      setData: vi.fn(),
    })),
    timeScale: vi.fn(() => ({
      fitContent: vi.fn(),
    })),
    applyOptions: vi.fn(),
    remove: vi.fn(),
  })),
  ColorType: { Solid: "Solid" },
  CandlestickSeries: {},
}));

// Mock ResizeObserver
global.ResizeObserver = class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
} as any;

import TVChart from "@/components/TVChart";

describe("TVChart", () => {
  it("renders without crashing", () => {
    const { container } = render(<TVChart />);
    expect(container.firstChild).toBeTruthy();
  });

  it("accepts symbol prop", () => {
    const { container } = render(<TVChart symbol="MES" />);
    expect(container.firstChild).toBeTruthy();
  });

  it("accepts custom data", () => {
    const data = [
      { time: 1000 as any, open: 100, high: 110, low: 90, close: 105 },
    ];
    const { container } = render(<TVChart symbol="MNQ" data={data} />);
    expect(container.firstChild).toBeTruthy();
  });
});

// Test the OrderPanel component
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

import OrderPanel from "@/components/OrderPanel";

describe("OrderPanel", () => {
  beforeEach(() => {
    global.fetch = vi.fn().mockRejectedValue(new Error("offline"));
  });

  it("renders with tabs", () => {
    render(<OrderPanel />);
    expect(screen.getByText("Positions (0)")).toBeTruthy();
    expect(screen.getByText("Trades")).toBeTruthy();
    expect(screen.getByText("Signals")).toBeTruthy();
  });

  it("shows empty state for positions", () => {
    render(<OrderPanel />);
    expect(screen.getByText("No open positions")).toBeTruthy();
  });

  it("switches tabs on click", () => {
    render(<OrderPanel />);
    fireEvent.click(screen.getByText("Trades"));
    expect(screen.getByText("No recent trades")).toBeTruthy();
  });
});

import AccountPanel from "@/components/AccountPanel";

describe("AccountPanel", () => {
  beforeEach(() => {
    global.fetch = vi.fn().mockRejectedValue(new Error("offline"));
  });

  it("renders with fallback values when backend offline", () => {
    render(<AccountPanel />);
    expect(screen.getByText("Account")).toBeTruthy();
    expect(screen.getByText("Equity")).toBeTruthy();
    expect(screen.getByText("$50,000")).toBeTruthy();
  });

  it("shows live performance section", () => {
    render(<AccountPanel />);
    expect(screen.getByText("Live Performance")).toBeTruthy();
    expect(screen.getByText("56.7%")).toBeTruthy();
  });
});
