import { describe, it, expect } from "vitest";

describe("next.config.js", () => {
  it("uses environment variables for backend URL", async () => {
    // Read the config file as text to verify env vars are used
    const fs = await import("fs");
    const config = fs.readFileSync("next.config.js", "utf-8");

    expect(config).toContain("process.env.BACKEND_URL");
    expect(config).toContain("process.env.SIGNALS_URL");
    // Should NOT contain hardcoded localhost
    expect(config).not.toMatch(/destination:\s*["']http:\/\/localhost/);
  });
});

describe("providers config", () => {
  it("uses Privy as auth provider (no RainbowKit)", async () => {
    const fs = await import("fs");
    const config = fs.readFileSync("app/providers.tsx", "utf-8");

    expect(config).toContain("PrivyProvider");
    expect(config).not.toContain("RainbowKit");
    expect(config).toContain("WagmiProvider");
  });
});

describe("env vars", () => {
  it(".env.local has required keys", async () => {
    const fs = await import("fs");
    const env = fs.readFileSync(".env.local", "utf-8");

    expect(env).toContain("NEXT_PUBLIC_CONTRACT_ADDRESS_BASE");
    expect(env).toContain("NEXT_PUBLIC_PRIVY_APP_ID");
  });
});
