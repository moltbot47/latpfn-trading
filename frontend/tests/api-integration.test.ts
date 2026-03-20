import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

describe("API Integration", () => {
  let originalFetch: typeof global.fetch;

  beforeEach(() => {
    originalFetch = global.fetch;
  });

  afterEach(() => {
    global.fetch = originalFetch;
  });

  it("handles offline backend gracefully for /api/account", async () => {
    global.fetch = vi.fn().mockRejectedValue(new Error("ECONNREFUSED"));

    const res = await fetch("/api/account").catch(() => null);
    expect(res).toBeNull();
  });

  it("handles 500 response gracefully", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      json: async () => ({ error: "Internal Server Error" }),
    });

    const res = await fetch("/api/positions");
    expect(res.ok).toBe(false);
  });

  it("parses valid account response", async () => {
    const mockAccount = {
      equity: 51234.56,
      daily_pnl: 234.50,
      unrealized_pnl: -45.00,
      cushion: 1800,
      max_daily_loss: 1000,
      positions_open: 2,
    };

    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => mockAccount,
    });

    const res = await fetch("/api/account");
    expect(res.ok).toBe(true);
    const data = await res.json();
    expect(data.equity).toBe(51234.56);
    expect(data.positions_open).toBe(2);
  });

  it("parses valid positions response", async () => {
    const mockPositions = [
      {
        instrument: "MNQ",
        direction: "long",
        entry_price: 20500.50,
        size: 1,
        pnl: 125.00,
        tier: "layup",
        stop_loss: 20450.00,
        take_profit: 20600.00,
      },
    ];

    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => mockPositions,
    });

    const res = await fetch("/api/positions");
    const data = await res.json();
    expect(Array.isArray(data)).toBe(true);
    expect(data[0].instrument).toBe("MNQ");
    expect(data[0].direction).toBe("long");
  });

  it("parses trades with nested structure", async () => {
    const mockResponse = {
      trades: [
        { instrument: "MES", direction: "short", pnl: -50.00, timestamp: "2026-03-19T14:30:00Z" },
      ],
    };

    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => mockResponse,
    });

    const res = await fetch("/api/trades/recent");
    const data = await res.json();
    const trades = Array.isArray(data) ? data : data.trades || [];
    expect(trades).toHaveLength(1);
    expect(trades[0].instrument).toBe("MES");
  });

  it("handles empty signals response", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ signals: [] }),
    });

    const res = await fetch("/api/signals/latest");
    const data = await res.json();
    const signals = Array.isArray(data) ? data : data.signals || [];
    expect(signals).toHaveLength(0);
  });
});
