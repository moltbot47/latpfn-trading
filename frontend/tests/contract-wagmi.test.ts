import { describe, it, expect } from "vitest";
import { SIGNAL_ACCESS_ADDRESS, SIGNAL_ACCESS_ABI } from "@/lib/contract-wagmi";

describe("contract-wagmi", () => {
  it("exports a valid address", () => {
    expect(SIGNAL_ACCESS_ADDRESS).toMatch(/^0x[a-fA-F0-9]{40}$/);
  });

  it("exports ABI with required functions", () => {
    const functionNames = SIGNAL_ACCESS_ABI
      .filter((item) => item.type === "function")
      .map((item) => item.name);

    expect(functionNames).toContain("subscribe");
    expect(functionNames).toContain("subscribePremium");
    expect(functionNames).toContain("getSubscription");
    expect(functionNames).toContain("monthlyPrice");
    expect(functionNames).toContain("subscriberCount");
    expect(functionNames).toContain("forecastCount");
    expect(functionNames).toContain("getRecentForecasts");
    expect(functionNames).toContain("isSubscribed");
  });

  it("subscribe is payable", () => {
    const sub = SIGNAL_ACCESS_ABI.find(
      (item) => item.type === "function" && item.name === "subscribe"
    );
    expect(sub).toBeDefined();
    expect((sub as any).stateMutability).toBe("payable");
  });

  it("getSubscription returns 3 fields", () => {
    const fn = SIGNAL_ACCESS_ABI.find(
      (item) => item.type === "function" && item.name === "getSubscription"
    );
    expect(fn).toBeDefined();
    expect((fn as any).outputs).toHaveLength(3);
  });
});
