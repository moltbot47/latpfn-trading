import { describe, it, expect } from "vitest";
import { safeChangePct, formatTime } from "@/lib/types";

describe("safeChangePct", () => {
  it("returns correct percentage for normal values", () => {
    // change=10, last=110 → base=100, pct = 10/100 * 100 = 10%
    expect(safeChangePct(10, 110)).toBe(10);
  });

  it("returns 0 when denominator is zero (last === change)", () => {
    expect(safeChangePct(100, 100)).toBe(0);
  });

  it("returns 0 when both are zero", () => {
    expect(safeChangePct(0, 0)).toBe(0);
  });

  it("handles negative change", () => {
    // change=-5, last=95 → base=100, pct = -5/100 * 100 = -5%
    expect(safeChangePct(-5, 95)).toBe(-5);
  });

  it("never returns NaN or Infinity", () => {
    const results = [
      safeChangePct(0, 0),
      safeChangePct(100, 100),
      safeChangePct(-50, -50),
      safeChangePct(1, 1),
    ];
    results.forEach((r) => {
      expect(Number.isFinite(r)).toBe(true);
      expect(Number.isNaN(r)).toBe(false);
    });
  });
});

describe("formatTime", () => {
  it("returns --:--:-- for null", () => {
    expect(formatTime(null)).toBe("--:--:--");
  });

  it("formats a real date as HH:MM:SS", () => {
    const d = new Date("2026-03-19T14:30:45");
    const result = formatTime(d);
    // Should contain colons and be 8 chars
    expect(result).toMatch(/^\d{2}:\d{2}:\d{2}$/);
  });
});
