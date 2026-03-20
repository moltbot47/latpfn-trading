"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { usePrivy } from "@privy-io/react-auth";
import { useAccount, useReadContract, useWriteContract, useWaitForTransactionReceipt } from "wagmi";
import { formatEther } from "viem";
import { SIGNAL_ACCESS_ADDRESS, SIGNAL_ACCESS_ABI } from "@/lib/contract-wagmi";
import { motion } from "framer-motion";

const STATS = [
  { value: "56.7%", label: "Win Rate", color: "var(--green)" },
  { value: "1.61", label: "Profit Factor", color: "var(--green)" },
  { value: "187", label: "Live Trades", color: "var(--text-strong)" },
  { value: "+$3,205", label: "Live P&L", color: "var(--green)" },
];

const BASIC_FEATURES = [
  "Real-time LaT-PFN forecasts",
  "All 4 active instruments",
  "Entry / SL / TP levels",
  "NBA shot-tier classification",
  "On-chain verification",
];

const PREMIUM_FEATURES = [
  "Everything in Basic",
  "Regime detection (trending/ranging/volatile)",
  "Confidence breakdown",
  "EMA trend filter insights",
  "Priority API access",
  "Signal archive",
];

const fadeUp = {
  hidden: { opacity: 0, y: 20 },
  visible: (i: number) => ({
    opacity: 1, y: 0,
    transition: { delay: i * 0.08, duration: 0.45, ease: "easeOut" as const },
  }),
};

export default function Home() {
  const router = useRouter();
  const { login, authenticated, ready: privyReady, logout, user } = usePrivy();
  const { address, isConnected, chain } = useAccount();
  // C2 fix: separate months state per plan
  const [basicMonths, setBasicMonths] = useState(1);
  const [premiumMonths, setPremiumMonths] = useState(1);
  // C2 fix: separate pending state per plan
  const [pendingPlan, setPendingPlan] = useState<"basic" | "premium" | null>(null);

  const { data: subData } = useReadContract({
    address: SIGNAL_ACCESS_ADDRESS, abi: SIGNAL_ACCESS_ABI,
    functionName: "getSubscription",
    args: address ? [address] : undefined,
    query: { enabled: !!address },
  });
  const { data: price } = useReadContract({
    address: SIGNAL_ACCESS_ADDRESS, abi: SIGNAL_ACCESS_ABI, functionName: "monthlyPrice",
  });
  const { data: subscriberCount } = useReadContract({
    address: SIGNAL_ACCESS_ADDRESS, abi: SIGNAL_ACCESS_ABI, functionName: "subscriberCount",
  });
  const { writeContract, data: txHash, isPending } = useWriteContract();
  const { isSuccess: txConfirmed } = useWaitForTransactionReceipt({ hash: txHash });

  // C1 fix: validate subData shape before accessing
  const isSubscribed = Array.isArray(subData) && subData.length >= 3 ? Boolean(subData[2]) : false;
  const monthlyPrice = price ? formatEther(price) : "0.005";
  const isBase = chain?.id === 8453 || chain?.id === 84532;

  // C1 fix: proper auth flow — only redirect if subscribed OR in dev mode
  // Authenticated users without wallet see a "connect wallet" prompt instead of empty page
  useEffect(() => { if (isSubscribed) router.push("/terminal"); }, [isSubscribed, router]);
  useEffect(() => { if (txConfirmed) router.push("/terminal"); }, [txConfirmed, router]);
  // Reset pending state when tx completes
  useEffect(() => { if (!isPending) setPendingPlan(null); }, [isPending]);

  if (!privyReady) {
    return (
      <div style={{ background: "var(--bg)", height: "100vh", display: "flex", alignItems: "center", justifyContent: "center" }}>
        <div className="pulse-dot" style={{ width: 12, height: 12 }} />
      </div>
    );
  }

  const handleSubscribe = (premium: boolean) => {
    if (!price) return;
    const months = premium ? premiumMonths : basicMonths;
    const total = premium ? price * BigInt(2) * BigInt(months) : price * BigInt(months);
    setPendingPlan(premium ? "premium" : "basic");
    writeContract({
      address: SIGNAL_ACCESS_ADDRESS, abi: SIGNAL_ACCESS_ABI,
      functionName: premium ? "subscribePremium" : "subscribe",
      args: [BigInt(months)], value: total,
    });
  };

  const userLabel = user?.email?.address || user?.google?.email
    || (user?.twitter?.username ? `@${user.twitter.username}` : null)
    || (address ? `${address.slice(0, 6)}...${address.slice(-4)}` : null);

  // Determine which content section to show
  const showHero = !isConnected && !authenticated;
  const showConnectWallet = authenticated && !isConnected;
  const showSubscribe = isConnected && isBase && !isSubscribed;
  const showWrongNetwork = isConnected && !isBase;

  return (
    <div className="landing">
      {/* ===== NAV ===== */}
      <nav style={{
        height: 56, display: "flex", alignItems: "center", justifyContent: "space-between",
        padding: "0 32px", background: "var(--bg-surface)", borderBottom: "1px solid var(--border-subtle)",
        position: "sticky", top: 0, zIndex: 50,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div className="pulse-dot" />
          <span style={{ fontWeight: 700, fontSize: 16, color: "var(--text-strong)" }}>LaT-PFN</span>
          <span style={{ fontSize: 12, color: "var(--text-faint)" }}>Trading Terminal</span>
        </div>
        {isConnected ? (
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span style={{ fontSize: 12, color: "var(--text-muted)", fontFamily: "'Source Code Pro', monospace" }}>
              {address ? `${address.slice(0, 6)}...${address.slice(-4)}` : ""}
            </span>
            <button className="btn-raised" style={{ fontSize: 12, padding: "4px 12px" }} onClick={logout}>Sign Out</button>
          </div>
        ) : authenticated && userLabel ? (
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span style={{ fontSize: 13, color: "var(--text-muted)" }}>{userLabel}</span>
            <button className="btn-raised" style={{ fontSize: 12, padding: "4px 12px" }} onClick={logout}>Sign Out</button>
          </div>
        ) : (
          <button className="btn-raised primary" onClick={login}>Sign In</button>
        )}
      </nav>

      {/* ===== HERO (unauthenticated) ===== */}
      {showHero && (
        <>
          <div className="hero-section" style={{ padding: "80px 32px 100px", textAlign: "center" }}>
            <div className="hero-pattern" />
            <motion.div initial="hidden" animate="visible" custom={0} variants={fadeUp}>
              <div className="badge-green" style={{
                display: "inline-flex", alignItems: "center", gap: 8,
                background: "rgba(56, 134, 0, 0.15)", border: "1px solid rgba(56, 134, 0, 0.3)",
                borderRadius: 20, padding: "5px 14px", fontSize: 12, fontWeight: 600, color: "#6BDE3A",
                marginBottom: 28,
              }}>
                <span className="pulse-dot" style={{ width: 5, height: 5, background: "#6BDE3A", boxShadow: "0 0 6px #6BDE3A" }} />
                Live since Feb 2026 — broker-confirmed results
              </div>
            </motion.div>

            <motion.h1 initial="hidden" animate="visible" custom={1} variants={fadeUp}
              style={{ fontSize: 56, fontWeight: 800, color: "#fff", lineHeight: 1.05, marginBottom: 20,
                letterSpacing: "-0.03em", textShadow: "0 2px 16px rgba(0,0,0,0.5)" }}>
              AI Trading Signals<br />
              <span style={{ color: "var(--orange)" }}>Verified On-Chain</span>
            </motion.h1>

            <motion.p initial="hidden" animate="visible" custom={2} variants={fadeUp}
              style={{ fontSize: 16, color: "rgba(255,255,255,0.7)", maxWidth: 520, margin: "0 auto 44px", lineHeight: 1.7 }}>
              Zero-shot LaT-PFN forecasting for micro futures. Every signal hashed and posted to Base L2 before delivery. No hindsight bias — ever.
            </motion.p>

            <motion.div initial="hidden" animate="visible" custom={3} variants={fadeUp}
              style={{ display: "flex", justifyContent: "center", gap: 14, marginBottom: 14 }}>
              <button className="btn-hero" onClick={login}>Get Started Free</button>
              <button className="btn-hero-ghost" aria-label="Scroll to how it works section"
                onClick={() => document.getElementById("how-it-works")?.scrollIntoView({ behavior: "smooth" })}>
                Learn More
              </button>
            </motion.div>
            <motion.p initial="hidden" animate="visible" custom={4} variants={fadeUp}
              style={{ fontSize: 12, color: "rgba(255,255,255,0.4)" }}>
              Email, Google, Twitter, Apple — or connect your wallet. No wallet needed.
            </motion.p>
          </div>

          {/* Stats */}
          <div style={{ maxWidth: 960, margin: "-40px auto 0", padding: "0 32px", position: "relative", zIndex: 3 }}>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 14 }}>
              {STATS.map((s, i) => (
                <motion.div key={s.label} initial="hidden" whileInView="visible" viewport={{ once: true }} custom={i} variants={fadeUp}
                  className="stat-card">
                  <div className="kpi-value" style={{ color: s.color, marginBottom: 6 }}>{s.value}</div>
                  <div style={{ fontSize: 11, color: "var(--text-faint)", textTransform: "uppercase", letterSpacing: "0.8px", fontWeight: 600 }}>
                    {s.label}
                  </div>
                </motion.div>
              ))}
            </div>
            <div style={{ marginTop: 16, display: "flex", justifyContent: "center", gap: 8 }}>
              {["MNQ", "MYM", "MES", "MBT"].map((sym) => (
                <span key={sym} className="instrument-pill">{sym}</span>
              ))}
            </div>
          </div>

          {/* How It Works */}
          <div id="how-it-works" style={{ maxWidth: 640, margin: "72px auto 0", padding: "0 32px" }}>
            <motion.div initial="hidden" whileInView="visible" viewport={{ once: true }} custom={0} variants={fadeUp}>
              <div className="section-divider" />
              <h2 style={{ fontSize: 24, fontWeight: 700, color: "var(--text-strong)", marginBottom: 24 }}>How It Works</h2>
            </motion.div>
            {[
              { step: "1", title: "Sign In", desc: "Email, Google, Twitter, Apple — or connect MetaMask, Coinbase, 300+ wallets. We auto-create a wallet if you don't have one." },
              { step: "2", title: "Subscribe", desc: `${monthlyPrice} ETH/month — on-chain via Base L2. Cancel anytime.` },
              { step: "3", title: "Access Terminal", desc: "Live charts, signals, positions — TradingView-style interface with real-time updates." },
              { step: "4", title: "Verify On-Chain", desc: "Every forecast hashed on Base before delivery. Check Basescan yourself — fully transparent." },
            ].map((item, i) => (
              <motion.div key={item.step} initial="hidden" whileInView="visible" viewport={{ once: true }} custom={i + 1} variants={fadeUp}
                className="ph-card" style={{ display: "flex", gap: 16, marginBottom: 12, cursor: "default" }}>
                <div className="step-num">{item.step}</div>
                <div>
                  <div style={{ fontWeight: 600, fontSize: 15, color: "var(--text-strong)", marginBottom: 2 }}>{item.title}</div>
                  <div style={{ fontSize: 13, color: "var(--text-muted)", lineHeight: 1.6 }}>{item.desc}</div>
                </div>
              </motion.div>
            ))}
          </div>

          {/* Bottom CTA */}
          <motion.div initial="hidden" whileInView="visible" viewport={{ once: true }} custom={0} variants={fadeUp}
            style={{ textAlign: "center", margin: "56px 0 24px" }}>
            <button className="btn-raised primary" style={{ padding: "12px 32px", fontSize: 16, borderRadius: 10 }}
              onClick={login}>
              Start Trading with AI
            </button>
          </motion.div>

          {/* Footer */}
          <div style={{
            maxWidth: 640, margin: "0 auto", padding: "24px 32px 40px",
            borderTop: "1px solid var(--border-subtle)", fontSize: 12, color: "var(--text-faint)", textAlign: "center",
          }}>
            <p>Powered by LaT-PFN Zero-Shot Forecasting | Deployed on Base L2</p>
            <p style={{ marginTop: 6 }}>
              Contract:{" "}
              <a href="https://basescan.org/address/0x901c169aa21a9eC593c52bc6F0eaA814eDf41091"
                style={{ color: "var(--blue)", textDecoration: "none" }} target="_blank" rel="noopener noreferrer">
                0x901c...1091
              </a>
              {" | "}Built by{" "}
              <a href="https://github.com/moltbot47"
                style={{ color: "var(--blue)", textDecoration: "none" }} target="_blank" rel="noopener noreferrer">
                @moltbot47
              </a>
            </p>
          </div>
        </>
      )}

      {/* ===== CONNECT WALLET (authenticated but no wallet) ===== */}
      {showConnectWallet && (
        <div style={{ textAlign: "center", padding: "100px 32px" }}>
          <h2 style={{ fontSize: 28, fontWeight: 700, color: "var(--text-strong)", marginBottom: 12 }}>Connect Your Wallet</h2>
          <p style={{ color: "var(--text-muted)", marginBottom: 28, fontSize: 14, maxWidth: 420, margin: "0 auto 28px" }}>
            Connect a wallet on Base L2 to subscribe and access the trading terminal.
          </p>
          <button className="btn-raised primary" style={{ padding: "10px 28px", fontSize: 14 }} onClick={login}>
            Connect Wallet
          </button>
          <div style={{ marginTop: 20 }}>
            <button
              className="btn-raised"
              style={{ fontSize: 13, padding: "8px 20px" }}
              onClick={() => router.push("/terminal")}
            >
              Skip to Terminal (Free Preview)
            </button>
          </div>
          <p style={{ color: "var(--text-faint)", fontSize: 12, marginTop: 12 }}>
            Or skip to preview the terminal without a subscription.
          </p>
        </div>
      )}

      {/* ===== SUBSCRIBE CARDS ===== */}
      {showSubscribe && (
        <div style={{ maxWidth: 760, margin: "48px auto", padding: "0 32px" }}>
          <div style={{ textAlign: "center", marginBottom: 36 }}>
            <div className="section-divider" style={{ margin: "0 auto 16px" }} />
            <h2 style={{ fontSize: 28, fontWeight: 700, color: "var(--text-strong)", marginBottom: 8 }}>Choose Your Plan</h2>
            <p style={{ color: "var(--text-muted)", fontSize: 14 }}>
              {subscriberCount !== undefined ? `${Number(subscriberCount)} active subscribers — ` : ""}On-chain subscription via Base L2
            </p>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20 }}>
            {/* Basic */}
            <div className="ph-card">
              <h3 style={{ fontSize: 20, fontWeight: 700, color: "var(--text-strong)", marginBottom: 4 }}>Basic</h3>
              <p style={{ fontSize: 13, color: "var(--text-muted)", marginBottom: 20 }}>All signals for MNQ, MYM, MES, MBT</p>
              <div className="kpi-value" style={{ marginBottom: 20 }}>
                {monthlyPrice} <span style={{ fontSize: 16, color: "var(--text-faint)", fontWeight: 400, fontFamily: "inherit" }}>ETH/mo</span>
              </div>
              {BASIC_FEATURES.map((f) => (
                <div key={f} style={{ fontSize: 13, color: "var(--text-muted)", padding: "4px 0", display: "flex", gap: 8 }}>
                  <span style={{ color: "var(--green)", fontWeight: 700 }}>&#10003;</span> {f}
                </div>
              ))}
              <div style={{ display: "flex", alignItems: "center", gap: 8, margin: "20px 0 16px" }}>
                <span style={{ fontSize: 12, color: "var(--text-faint)" }}>Months:</span>
                <select value={basicMonths} onChange={(e) => setBasicMonths(Number(e.target.value))}
                  style={{ background: "var(--bg-accent)", border: "1px solid var(--border-subtle)", borderRadius: 6, color: "var(--text)", padding: "6px 10px", fontSize: 12, fontFamily: "inherit" }}>
                  {[1, 3, 6, 12].map((m) => <option key={m} value={m}>{m}</option>)}
                </select>
                <span style={{ fontSize: 12, color: "var(--text-faint)", marginLeft: "auto", fontFamily: "'Source Code Pro', monospace" }}>
                  {(parseFloat(monthlyPrice) * basicMonths).toFixed(4)} ETH
                </span>
              </div>
              <button className="btn-raised" style={{ width: "100%", justifyContent: "center", height: 42, fontSize: 14 }}
                onClick={() => handleSubscribe(false)} disabled={isPending && pendingPlan === "basic"}>
                {isPending && pendingPlan === "basic" ? "Confirming..." : "Subscribe Basic"}
              </button>
            </div>

            {/* Premium */}
            <div className="ph-card" style={{ borderColor: "var(--orange)", borderWidth: 2, position: "relative" }}>
              <div style={{
                position: "absolute", top: -12, right: 20,
                background: "var(--orange)", color: "white",
                padding: "4px 14px", borderRadius: 6, fontSize: 11, fontWeight: 700,
                letterSpacing: "0.5px", boxShadow: "0 2px 0 var(--orange-shadow)",
              }}>
                RECOMMENDED
              </div>
              <h3 style={{ fontSize: 20, fontWeight: 700, color: "var(--text-strong)", marginBottom: 4 }}>Premium</h3>
              <p style={{ fontSize: 13, color: "var(--text-muted)", marginBottom: 20 }}>Everything + regime analysis & confidence</p>
              <div className="kpi-value" style={{ marginBottom: 20 }}>
                {(parseFloat(monthlyPrice) * 2).toFixed(4)} <span style={{ fontSize: 16, color: "var(--text-faint)", fontWeight: 400, fontFamily: "inherit" }}>ETH/mo</span>
              </div>
              {PREMIUM_FEATURES.map((f) => (
                <div key={f} style={{ fontSize: 13, color: "var(--text-muted)", padding: "4px 0", display: "flex", gap: 8 }}>
                  <span style={{ color: "var(--orange)", fontWeight: 700 }}>&#10003;</span> {f}
                </div>
              ))}
              <div style={{ display: "flex", alignItems: "center", gap: 8, margin: "20px 0 16px" }}>
                <span style={{ fontSize: 12, color: "var(--text-faint)" }}>Months:</span>
                <select value={premiumMonths} onChange={(e) => setPremiumMonths(Number(e.target.value))}
                  style={{ background: "var(--bg-accent)", border: "1px solid var(--border-subtle)", borderRadius: 6, color: "var(--text)", padding: "6px 10px", fontSize: 12, fontFamily: "inherit" }}>
                  {[1, 3, 6, 12].map((m) => <option key={m} value={m}>{m}</option>)}
                </select>
                <span style={{ fontSize: 12, color: "var(--text-faint)", marginLeft: "auto", fontFamily: "'Source Code Pro', monospace" }}>
                  {(parseFloat(monthlyPrice) * 2 * premiumMonths).toFixed(4)} ETH
                </span>
              </div>
              <button className="btn-raised primary" style={{ width: "100%", justifyContent: "center", height: 42, fontSize: 14, borderRadius: 8 }}
                onClick={() => handleSubscribe(true)} disabled={isPending && pendingPlan === "premium"}>
                {isPending && pendingPlan === "premium" ? "Confirming..." : "Subscribe Premium"}
              </button>
            </div>
          </div>

          <div style={{ textAlign: "center", marginTop: 20 }}>
            <button
              className="btn-raised"
              style={{ fontSize: 13, padding: "8px 20px" }}
              onClick={() => router.push("/terminal")}
            >
              Skip to Terminal (Free Preview)
            </button>
          </div>
        </div>
      )}

      {/* ===== WRONG NETWORK ===== */}
      {showWrongNetwork && (
        <div style={{ textAlign: "center", padding: "100px 32px" }}>
          <h2 style={{ fontSize: 22, fontWeight: 700, color: "var(--text-strong)", marginBottom: 8 }}>Wrong Network</h2>
          <p style={{ color: "var(--text-muted)", marginBottom: 28, fontSize: 14 }}>
            Switch to Base network to access LaT-PFN signals.
          </p>
          <button className="btn-raised primary" style={{ padding: "10px 28px", fontSize: 14 }} onClick={login}>
            Switch Network
          </button>
        </div>
      )}
    </div>
  );
}
