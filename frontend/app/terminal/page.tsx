"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import Link from "next/link";
import TVChart from "@/components/TVChart";
import SignalToast from "@/components/SignalToast";
import type { Position, Trade, Signal, AccountData, Instrument } from "@/lib/types";
import { safeChangePct, formatTime } from "@/lib/types";

// ─── Progress Bar Helper ─────────────────────────────────────────
function ProgressBar({ value, max, color }: { value: number; max: number; color: string }) {
  const width = 20;
  const filled = Math.round(Math.min(1, value / max) * width);
  const empty = width - filled;
  const pct = Math.round(Math.min(100, (value / max) * 100));
  return (
    <span style={{ fontFamily: "inherit", whiteSpace: "pre" }}>
      [<span style={{ color }}>{"█".repeat(filled)}</span>
      {"░".repeat(empty)}] {String(pct).padStart(3)}%
    </span>
  );
}

// ─── Timeframe mapping ──────────────────────────────────────────
const TIMEFRAMES = [
  { label: "1m", value: "1" },
  { label: "5m", value: "5" },
  { label: "15m", value: "15" },
  { label: "1H", value: "60" },
  { label: "4H", value: "240" },
  { label: "1D", value: "D" },
];

// ─── Instruments ─────────────────────────────────────────────────
const INIT_INSTRUMENTS: Instrument[] = [
  { symbol: "MNQ", name: "Micro Nasdaq", last: 20512.75, change: 45.25, changePct: 0.22 },
  { symbol: "MYM", name: "Micro Dow", last: 42185.0, change: -120.0, changePct: -0.28 },
  { symbol: "MES", name: "Micro S&P", last: 5812.5, change: 8.75, changePct: 0.15 },
  { symbol: "MBT", name: "Micro BTC", last: 68250.0, change: -485.0, changePct: -0.71 },
];

// ─── Default performance stats (fallback when backend is offline) ─
const DEFAULT_PERF = {
  total_trades: 187, win_rate: 56.7, profit_factor: 1.61, total_pnl: 3205,
  by_instrument: [
    { sym: "MNQ", wr: 61.1, pnl: 1668 },
    { sym: "MES", wr: 51.8, pnl: 404 },
    { sym: "MBT", wr: 80.0, pnl: 263 },
    { sym: "MYM", wr: 50.0, pnl: 256 },
  ],
};

// ─── Main Terminal Page ──────────────────────────────────────────
export default function Terminal() {
  const [selectedSymbol, setSelectedSymbol] = useState("MNQ");
  const [selectedInterval, setSelectedInterval] = useState("5");
  const [tab, setTab] = useState<"positions" | "trades" | "signals">("positions");
  const [instruments, setInstruments] = useState(INIT_INSTRUMENTS);
  const [positions, setPositions] = useState<Position[]>([]);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [signals, setSignals] = useState<Signal[]>([]);
  const [account, setAccount] = useState<AccountData | null>(null);
  const [now, setNow] = useState<Date | null>(null);
  const [backendConnected, setBackendConnected] = useState(false);
  const [perf, setPerf] = useState(DEFAULT_PERF);
  const [toasts, setToasts] = useState<Signal[]>([]);
  const lastSignalTimestamp = useRef<string>("");

  // Clock
  useEffect(() => {
    setNow(new Date());
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);

  // Simulated price ticks (fallback — replaced by /api/instruments when backend is live)
  useEffect(() => {
    const t = setInterval(() => {
      setInstruments((prev) =>
        prev.map((inst) => {
          const tick = (Math.random() - 0.5) * inst.last * 0.0002;
          const last = Math.round((inst.last + tick) * 100) / 100;
          const change = Math.round((inst.change + tick) * 100) / 100;
          return { ...inst, last, change, changePct: safeChangePct(change, last) };
        })
      );
    }, 2000);
    return () => clearInterval(t);
  }, []);

  // Fetch backend data
  const fetchData = useCallback(async () => {
    let anyOk = false;
    try {
      const [posRes, tradeRes, acctRes, sigRes, perfRes, instRes] = await Promise.all([
        fetch("/api/positions").catch(() => null),
        fetch("/api/trades/recent").catch(() => null),
        fetch("/api/account").catch(() => null),
        fetch("/api/signals").catch(() => null),
        fetch("/api/performance").catch(() => null),
        fetch("/api/instruments").catch(() => null),
      ]);
      if (posRes?.ok) {
        anyOk = true;
        const d = await posRes.json();
        const posList = Array.isArray(d) ? d : d.positions || [];
        setPositions(posList.map((p: any) => ({ ...p, pnl: p.pnl ?? p.unrealized_pnl ?? 0 })));
      }
      if (tradeRes?.ok) {
        anyOk = true;
        const d = await tradeRes.json();
        setTrades((Array.isArray(d) ? d : d.trades || []).slice(0, 30));
      }
      if (acctRes?.ok) {
        anyOk = true;
        const d = await acctRes.json();
        setAccount({
          equity: d.equity ?? d.estimated_equity ?? 50000,
          daily_pnl: d.daily_pnl ?? 0,
          unrealized_pnl: d.unrealized_pnl ?? 0,
          cushion: d.cushion ?? 2000,
          max_daily_loss: d.max_daily_loss ?? 1000,
          positions_open: d.positions_open ?? 0,
          starting_balance: d.starting_balance ?? 50000,
          drawdown_floor: d.drawdown_floor ?? 48000,
          high_water_mark: d.high_water_mark ?? 50000,
        });
      }
      if (sigRes?.ok) {
        anyOk = true;
        const d = await sigRes.json();
        const sigList: Signal[] = Array.isArray(d) ? d : d.signals || [];
        // Detect new signals for toast notifications
        if (sigList.length > 0) {
          const newest = sigList[0]?.timestamp || "";
          if (lastSignalTimestamp.current && newest > lastSignalTimestamp.current) {
            const newSignals = sigList.filter((s) => (s.timestamp || "") > lastSignalTimestamp.current);
            setToasts((prev) => [...prev, ...newSignals]);
            // Browser notification for background tabs
            if (typeof Notification !== "undefined" && Notification.permission === "granted") {
              for (const s of newSignals) {
                new Notification(`LaT-PFN: ${s.instrument} ${s.direction?.toUpperCase()}`, {
                  body: `${s.tier} | Entry: ${s.entry?.toFixed(2)} | Conf: ${((s.confidence || 0) * 100).toFixed(0)}%`,
                  icon: "/icon.svg",
                });
              }
            }
          }
          lastSignalTimestamp.current = newest;
        }
        setSignals(sigList);
      }
      if (perfRes?.ok) {
        anyOk = true;
        const d = await perfRes.json();
        if (d.total_trades || d.points) {
          setPerf({
            total_trades: d.total_trades ?? d.points?.total_trades ?? DEFAULT_PERF.total_trades,
            win_rate: d.win_rate ?? d.points?.win_rate ?? DEFAULT_PERF.win_rate,
            profit_factor: d.profit_factor ?? d.points?.profit_factor ?? DEFAULT_PERF.profit_factor,
            total_pnl: d.total_pnl ?? d.points?.total_pnl ?? DEFAULT_PERF.total_pnl,
            by_instrument: d.by_instrument ?? d.points?.by_instrument ?? DEFAULT_PERF.by_instrument,
          });
        }
      }
      if (instRes?.ok) {
        anyOk = true;
        const d = await instRes.json();
        const instList = Array.isArray(d) ? d : d.instruments || [];
        if (instList.length > 0) {
          setInstruments((prev) =>
            prev.map((inst) => {
              const updated = instList.find((u: any) => u.symbol === inst.symbol);
              if (!updated) return inst;
              return {
                ...inst,
                last: updated.last ?? updated.price ?? inst.last,
                change: updated.change ?? inst.change,
                changePct: updated.changePct ?? updated.change_pct ?? inst.changePct,
              };
            })
          );
        }
      }
    } catch { /* backend offline */ }
    setBackendConnected(anyOk);
  }, []);

  useEffect(() => {
    fetchData();
    const t = setInterval(fetchData, 15000);
    return () => clearInterval(t);
  }, [fetchData]);

  // Request notification permission on mount
  useEffect(() => {
    if (typeof Notification !== "undefined" && Notification.permission === "default") {
      Notification.requestPermission();
    }
  }, []);

  // Derived values
  const equity = account?.equity || 50000;
  const dailyPnl = account?.daily_pnl || 0;
  const unrealized = account?.unrealized_pnl || 0;
  const cushion = account?.cushion || 2000;
  const maxDailyLoss = account?.max_daily_loss || 1000;
  const cushionPct = Math.min(100, (cushion / 2000) * 100);
  const dailyUsedPct = Math.min(100, (Math.abs(dailyPnl) / maxDailyLoss) * 100);
  const posCount = account?.positions_open || positions.length;

  // Current timeframe display label
  const currentTfLabel = TIMEFRAMES.find((tf) => tf.value === selectedInterval)?.label || "5m";

  // Market status
  const getMarketStatus = () => {
    if (!now) return "--";
    try {
      const et = new Date(now.toLocaleString("en-US", { timeZone: "America/New_York" }));
      const day = et.getDay();
      if (day === 0 && et.getHours() < 18) return "CLOSED";
      if (day === 6) return "CLOSED";
      if (day === 5 && et.getHours() >= 17) return "CLOSED";
      return "OPEN";
    } catch { return "--"; }
  };
  const marketStatus = getMarketStatus();

  return (
    <div className="tui" style={{ height: "100vh", display: "flex", flexDirection: "column", paddingBottom: 17 }}>
      {/* ═══ TOP BAR ═══ */}
      <div style={{
        height: 24, display: "flex", alignItems: "center", padding: "0 8px",
        borderBottom: "1px solid #767676", gap: 16, flexShrink: 0,
      }}>
        <span style={{ color: "#61d6d6", fontWeight: 700 }}>LaT-PFN</span>
        <span style={{ color: "#767676" }}>│</span>
        {/* Mobile symbol selector (hidden on desktop via CSS) */}
        <select
          value={selectedSymbol}
          onChange={(e) => setSelectedSymbol(e.target.value)}
          className="tui-show-mobile"
          style={{
            background: "#0c0c0c", color: "#f2f2f2", border: "1px solid #767676",
            fontFamily: "inherit", fontSize: 11, padding: "0 4px",
          }}
        >
          {instruments.map((inst) => (
            <option key={inst.symbol} value={inst.symbol}>{inst.symbol}</option>
          ))}
        </select>
        <span className="tui-hide-mobile" style={{ color: "#f2f2f2", fontWeight: 700 }}>{selectedSymbol}</span>
        <span className="tui-hide-mobile" style={{ color: "#767676" }}>{currentTfLabel}</span>
        <span className="tui-hide-mobile" style={{ color: "#767676" }}>│</span>
        {TIMEFRAMES.map((tf) => (
          <span
            key={tf.value}
            onClick={() => setSelectedInterval(tf.value)}
            className="tui-hide-mobile"
            style={{
              color: selectedInterval === tf.value ? "#f2f2f2" : "#767676",
              cursor: "pointer",
              fontWeight: selectedInterval === tf.value ? 700 : 400,
            }}
          >
            {tf.label}
          </span>
        ))}
        <span style={{ flex: 1 }} />
        <span style={{ color: backendConnected ? "#16c60c" : "#767676", fontSize: 8, marginRight: -8 }} title={backendConnected ? "Backend connected" : "Backend offline"}>●</span>
        <span style={{ color: marketStatus === "OPEN" ? "#16c60c" : "#e74856" }}>●</span>
        <span style={{ color: "#767676" }}>{marketStatus === "OPEN" ? "LIVE" : "CLOSED"}</span>
        <span style={{ color: "#767676" }}>│</span>
        <Link href="/terminal/dashboard" style={{ color: "#3b78ff", textDecoration: "none", fontSize: 11 }}>Dashboard</Link>
        <span style={{ color: "#767676" }}>│</span>
        <span style={{ color: "#767676" }}>{formatTime(now)}</span>
      </div>

      {/* ═══ MAIN LAYOUT ═══ */}
      <div className="tui-mobile-stack" style={{ flex: 1, display: "flex", overflow: "hidden" }}>

        {/* ─── LEFT: Watchlist ─── */}
        <div className="tui-hide-mobile" style={{ width: 200, borderRight: "1px solid #767676", display: "flex", flexDirection: "column", flexShrink: 0 }}>
          <div style={{ padding: "4px 8px", borderBottom: "1px solid #767676", color: "#61d6d6", fontWeight: 700, fontSize: 11, textTransform: "uppercase", letterSpacing: "0.05em" }}>
            ┌ Watchlist
          </div>
          <div style={{ flex: 1, overflow: "auto" }}>
            {instruments.map((inst) => (
              <div
                key={inst.symbol}
                onClick={() => setSelectedSymbol(inst.symbol)}
                style={{
                  padding: "4px 8px",
                  cursor: "pointer",
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  background: selectedSymbol === inst.symbol ? "rgba(97,214,214,0.1)" : undefined,
                  borderLeft: selectedSymbol === inst.symbol ? "2px solid #61d6d6" : "2px solid transparent",
                }}
              >
                <div>
                  <div style={{ fontWeight: 700, color: selectedSymbol === inst.symbol ? "#f2f2f2" : "#cccccc", fontSize: 12 }}>
                    {inst.symbol}
                  </div>
                  <div style={{ color: "#767676", fontSize: 10 }}>{inst.name}</div>
                </div>
                <div style={{ textAlign: "right" }}>
                  <div style={{ fontVariantNumeric: "tabular-nums", color: "#f2f2f2", fontSize: 11 }}>
                    {inst.last.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                  </div>
                  <div style={{
                    color: inst.changePct >= 0 ? "#16c60c" : "#e74856",
                    fontSize: 10, fontVariantNumeric: "tabular-nums",
                  }}>
                    {inst.changePct >= 0 ? "+" : ""}{inst.changePct.toFixed(2)}%
                  </div>
                </div>
              </div>
            ))}
          </div>

          {/* Signals Today */}
          <div style={{ borderTop: "1px solid #767676", padding: "4px 8px" }}>
            <div style={{ color: "#61d6d6", fontWeight: 700, fontSize: 10, textTransform: "uppercase", marginBottom: 4 }}>
              ├ Signals Today
            </div>
            {([
              { l: "Generated", v: String(signals.length || "--"), c: "#f2f2f2" },
              { l: "Executed", v: String(positions.length || "--"), c: "#f2f2f2" },
              { l: "Win Rate", v: `${perf.win_rate.toFixed(1)}%`, c: "#16c60c" },
            ] as const).map((s) => (
              <div key={s.l} style={{ display: "flex", justifyContent: "space-between", fontSize: 11, padding: "1px 0" }}>
                <span style={{ color: "#767676" }}>{s.l}</span>
                <span style={{ color: s.c, fontWeight: 700 }}>{s.v}</span>
              </div>
            ))}
          </div>
        </div>

        {/* ─── CENTER: Chart + Bottom Panel ─── */}
        <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
          {/* Chart */}
          <div style={{ flex: 1, minHeight: 0 }}>
            <TVChart key={`${selectedSymbol}-${selectedInterval}`} symbol={selectedSymbol} interval={selectedInterval} />
          </div>

          {/* Bottom panel: Positions / Trades / Signals */}
          <div style={{ height: 220, borderTop: "1px solid #767676", display: "flex", flexDirection: "column", flexShrink: 0 }}>
            <div className="tui-tabs">
              {[
                { id: "positions" as const, label: `Positions (${posCount})` },
                { id: "trades" as const, label: "Trades" },
                { id: "signals" as const, label: "Signals" },
              ].map((t) => (
                <div key={t.id} className={`tui-tab ${tab === t.id ? "tui-tab-active" : ""}`} onClick={() => setTab(t.id)}>
                  {t.label}
                </div>
              ))}
            </div>
            <div style={{ flex: 1, overflow: "auto", padding: "0 8px" }}>
              {tab === "positions" && (
                <table className="tui-table">
                  <thead>
                    <tr>
                      <th>Symbol</th><th>Side</th><th className="num">Entry</th>
                      <th className="num">SL</th><th className="num">TP</th>
                      <th className="num">P&L</th><th>Tier</th>
                    </tr>
                  </thead>
                  <tbody>
                    {positions.length === 0 ? (
                      <tr><td colSpan={7} style={{ textAlign: "center", color: "#767676", padding: 16 }}>No open positions</td></tr>
                    ) : positions.map((p, i) => (
                      <tr key={i}>
                        <td style={{ fontWeight: 700 }}>{p.instrument}</td>
                        <td><span className={p.direction === "long" ? "tui-long" : "tui-short"}>{p.direction?.toUpperCase()}</span></td>
                        <td className="num">{p.entry_price?.toFixed(2)}</td>
                        <td className="num" style={{ color: "#e74856" }}>{p.stop_loss?.toFixed(2)}</td>
                        <td className="num" style={{ color: "#16c60c" }}>{p.take_profit?.toFixed(2)}</td>
                        <td className="num" style={{ color: (p.pnl || 0) >= 0 ? "#16c60c" : "#e74856" }}>
                          {(p.pnl || 0) >= 0 ? "+" : ""}${(p.pnl || 0).toFixed(2)}
                        </td>
                        <td><span className={`tier-${p.tier}`}>{p.tier}</span></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}

              {tab === "trades" && (
                <table className="tui-table">
                  <thead>
                    <tr>
                      <th>Time</th><th>Symbol</th><th>Side</th>
                      <th className="num">Entry</th><th className="num">Exit</th>
                      <th className="num">P&L</th><th>Tier</th>
                    </tr>
                  </thead>
                  <tbody>
                    {trades.length === 0 ? (
                      <tr><td colSpan={7} style={{ textAlign: "center", color: "#767676", padding: 16 }}>No recent trades</td></tr>
                    ) : trades.map((t, i) => (
                      <tr key={i}>
                        <td style={{ color: "#767676", fontSize: 11 }}>
                          {t.timestamp ? new Date(t.timestamp).toLocaleTimeString("en-US", { hour12: false }) : "--"}
                        </td>
                        <td style={{ fontWeight: 700 }}>{t.instrument}</td>
                        <td><span className={t.direction === "long" ? "tui-long" : "tui-short"}>{t.direction?.toUpperCase()}</span></td>
                        <td className="num">{t.entry_price?.toFixed(2)}</td>
                        <td className="num">{t.exit_price?.toFixed(2) || "--"}</td>
                        <td className="num" style={{ color: (t.pnl || 0) >= 0 ? "#16c60c" : "#e74856" }}>
                          {(t.pnl || 0) >= 0 ? "+" : ""}${(t.pnl || 0).toFixed(2)}
                        </td>
                        <td><span className={`tier-${t.tier}`}>{t.tier}</span></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}

              {tab === "signals" && (
                <div style={{ padding: "8px 0" }}>
                  {signals.length === 0 ? (
                    <div style={{ textAlign: "center", color: "#767676", padding: 16 }}>
                      <div>Signal feed updates every 5 minutes during market hours.</div>
                      <div style={{ marginTop: 4, fontSize: 11 }}>CME Globex: Sun 6PM — Fri 5PM ET</div>
                    </div>
                  ) : signals.map((s, i) => (
                    <div key={i} className="tui-signal">
                      <div className="tui-signal-header">
                        <span style={{ fontWeight: 700, color: "#f2f2f2" }}>{s.instrument}</span>
                        <span className={s.direction === "long" ? "tui-long" : "tui-short"}>{s.direction?.toUpperCase()}</span>
                        <span className={`tier-${s.tier}`}>{s.tier}</span>
                        <span style={{ marginLeft: "auto", color: "#767676", fontSize: 10 }}>
                          {s.timestamp ? new Date(s.timestamp).toLocaleTimeString("en-US", { hour12: false }) : ""}
                        </span>
                      </div>
                      <div className="tui-signal-grid">
                        <div className="tui-signal-field"><label>Entry</label><br /><span>{s.entry?.toFixed(2)}</span></div>
                        <div className="tui-signal-field"><label>SL</label><br /><span style={{ color: "#e74856" }}>{s.stop_loss?.toFixed(2)}</span></div>
                        <div className="tui-signal-field"><label>TP</label><br /><span style={{ color: "#16c60c" }}>{s.take_profit?.toFixed(2)}</span></div>
                        <div className="tui-signal-field"><label>Conf</label><br /><span>{(s.confidence * 100).toFixed(1)}%</span></div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>

        {/* ─── RIGHT: Account Panel ─── */}
        <div className="tui-hide-mobile" style={{ width: 220, borderLeft: "1px solid #767676", display: "flex", flexDirection: "column", flexShrink: 0 }}>
          <div style={{ padding: "4px 8px", borderBottom: "1px solid #767676", color: "#61d6d6", fontWeight: 700, fontSize: 11, textTransform: "uppercase", letterSpacing: "0.05em" }}>
            ┌ Account
          </div>
          <div style={{ flex: 1, overflow: "auto", padding: "8px" }}>
            {/* Account metrics */}
            {[
              { l: "Equity", v: `$${equity.toLocaleString()}`, c: "#f2f2f2" },
              { l: "Daily P&L", v: `${dailyPnl >= 0 ? "+" : ""}$${dailyPnl.toFixed(2)}`, c: dailyPnl >= 0 ? "#16c60c" : "#e74856" },
              { l: "Unrealized", v: `${unrealized >= 0 ? "+" : ""}$${unrealized.toFixed(2)}`, c: unrealized >= 0 ? "#16c60c" : "#e74856" },
              { l: "DD Cushion", v: `$${cushion.toFixed(0)}`, c: cushion > 1000 ? "#16c60c" : "#e74856" },
              { l: "Positions", v: `${posCount}`, c: "#f2f2f2" },
              { l: "Daily Limit", v: `$${maxDailyLoss.toFixed(0)}`, c: "#767676" },
            ].map((m) => (
              <div key={m.l} className="tui-row" style={{ padding: "2px 0" }}>
                <span className="tui-row-label">{m.l}</span>
                <span className="tui-row-value" style={{ color: m.c }}>{m.v}</span>
              </div>
            ))}

            {/* Risk bars */}
            <div style={{ marginTop: 12, borderTop: "1px solid #767676", paddingTop: 8 }}>
              <div style={{ fontSize: 10, color: "#767676", textTransform: "uppercase", marginBottom: 4 }}>
                ├ Risk
              </div>
              <div className="tui-row" style={{ padding: "2px 0" }}>
                <span style={{ color: "#767676", fontSize: 10, minWidth: "8ch" }}>Cushion</span>
                <span className="tui-bar-track">
                  <ProgressBar value={cushionPct} max={100} color={cushionPct > 50 ? "#16c60c" : cushionPct > 25 ? "#c19c00" : "#e74856"} />
                </span>
              </div>
              <div className="tui-row" style={{ padding: "2px 0" }}>
                <span style={{ color: "#767676", fontSize: 10, minWidth: "8ch" }}>DailyLoss</span>
                <span className="tui-bar-track">
                  <ProgressBar value={dailyUsedPct} max={100} color={dailyUsedPct < 50 ? "#16c60c" : dailyUsedPct < 75 ? "#c19c00" : "#e74856"} />
                </span>
              </div>
            </div>

            {/* Performance — from API or fallback */}
            <div style={{ marginTop: 12, borderTop: "1px solid #767676", paddingTop: 8 }}>
              <div style={{ fontSize: 10, color: "#767676", textTransform: "uppercase", marginBottom: 4 }}>
                ├ Live Performance
              </div>
              {[
                { l: "Trades", v: String(perf.total_trades), c: "#f2f2f2" },
                { l: "Win Rate", v: `${perf.win_rate.toFixed(1)}%`, c: "#16c60c" },
                { l: "PF", v: perf.profit_factor.toFixed(2), c: "#16c60c" },
                { l: "Total P&L", v: `+$${perf.total_pnl.toLocaleString()}`, c: "#16c60c" },
              ].map((s) => (
                <div key={s.l} className="tui-row" style={{ padding: "2px 0" }}>
                  <span className="tui-row-label">{s.l}</span>
                  <span className="tui-row-value" style={{ color: s.c }}>{s.v}</span>
                </div>
              ))}
            </div>

            {/* Per-instrument breakdown */}
            <div style={{ marginTop: 12, borderTop: "1px solid #767676", paddingTop: 8 }}>
              <div style={{ fontSize: 10, color: "#767676", textTransform: "uppercase", marginBottom: 4 }}>
                └ By Instrument
              </div>
              {perf.by_instrument.map((s) => (
                <div key={s.sym} style={{ display: "flex", justifyContent: "space-between", fontSize: 11, padding: "1px 0" }}>
                  <span style={{ color: "#cccccc", fontWeight: 700, minWidth: "4ch" }}>{s.sym}</span>
                  <span style={{ color: "#767676" }}>{s.wr.toFixed(1)}%</span>
                  <span style={{ color: s.pnl >= 0 ? "#16c60c" : "#e74856", fontVariantNumeric: "tabular-nums" }}>
                    {s.pnl >= 0 ? "+" : ""}${s.pnl.toLocaleString()}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* ═══ VIM STATUS LINE ═══ */}
      <div className="tui-statusline">
        <span className="tui-statusline-mode">NORMAL</span>
        <span style={{ padding: "0 8px" }}>latpfn-terminal</span>
        <span style={{ color: "#767676" }}>│</span>
        <span style={{ padding: "0 8px" }}>{selectedSymbol} {currentTfLabel}</span>
        <span style={{ color: "#767676" }}>│</span>
        <span style={{ padding: "0 8px", color: posCount > 0 ? "#0c0c0c" : "#767676" }}>
          {posCount} pos
        </span>
        <span className="tui-statusline-right">
          <span style={{ color: dailyPnl >= 0 ? "#13a10e" : "#c50f1f", fontWeight: 700 }}>
            {dailyPnl >= 0 ? "+" : ""}${dailyPnl.toFixed(0)}
          </span>
          <span style={{ color: "#767676" }}> │ </span>
          {formatTime(now)}
        </span>
      </div>

      {/* ═══ SIGNAL TOASTS ═══ */}
      <SignalToast toasts={toasts} onDismiss={(idx) => setToasts((prev) => prev.filter((_, i) => i !== idx))} />
    </div>
  );
}
