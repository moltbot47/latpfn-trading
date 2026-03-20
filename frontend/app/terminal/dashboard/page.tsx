"use client";

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { formatTime } from "@/lib/types";

// ─── Types ───────────────────────────────────────────────────────
interface DailyRecord {
  date: string;
  pnl: number;
  trades: number;
  win_rate: number;
  equity: number;
}

interface InstrumentPerf {
  symbol: string;
  trades: number;
  win_rate: number;
  pnl: number;
  pf: number;
  avg_trade: number;
}

interface PerformanceData {
  total_trades: number;
  win_rate: number;
  profit_factor: number;
  total_pnl: number;
  avg_trade: number;
  max_drawdown: number;
  sharpe_ratio: number;
  best_day: number;
  worst_day: number;
  by_instrument: InstrumentPerf[];
}

// ─── Progress Bar ────────────────────────────────────────────────
function Bar({ value, max, width = 20, color }: { value: number; max: number; width?: number; color: string }) {
  const filled = Math.round(Math.min(1, Math.abs(value) / max) * width);
  const empty = width - filled;
  return (
    <span style={{ fontFamily: "inherit", whiteSpace: "pre" }}>
      [<span style={{ color }}>{"█".repeat(filled)}</span>{"░".repeat(empty)}]
    </span>
  );
}

// ─── Sparkline (ASCII) ───────────────────────────────────────────
function Sparkline({ data, width = 40 }: { data: number[]; width?: number }) {
  if (data.length === 0) return <span style={{ color: "#767676" }}>No data</span>;
  const blocks = ["▁", "▂", "▃", "▄", "▅", "▆", "▇", "█"];
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  // Sample to fit width
  const step = Math.max(1, Math.floor(data.length / width));
  const sampled = [];
  for (let i = 0; i < data.length; i += step) sampled.push(data[i]);
  const last = data[data.length - 1];
  const first = data[0];
  const color = last >= first ? "#16c60c" : "#e74856";
  return (
    <span style={{ color, fontFamily: "inherit", letterSpacing: "-1px" }}>
      {sampled.map((v, i) => {
        const idx = Math.min(7, Math.floor(((v - min) / range) * 7));
        return <span key={i}>{blocks[idx]}</span>;
      })}
    </span>
  );
}

// ─── Fallback data ───────────────────────────────────────────────
const FALLBACK_INSTRUMENTS: InstrumentPerf[] = [
  { symbol: "MNQ", trades: 72, win_rate: 61.1, pnl: 1668, pf: 1.53, avg_trade: 23.17 },
  { symbol: "MES", trades: 56, win_rate: 51.8, pnl: 404, pf: 1.29, avg_trade: 7.21 },
  { symbol: "MBT", trades: 10, win_rate: 80.0, pnl: 263, pf: 2.14, avg_trade: 26.25 },
  { symbol: "MYM", trades: 48, win_rate: 50.0, pnl: 256, pf: 1.54, avg_trade: 5.33 },
];

const FALLBACK_PERF: PerformanceData = {
  total_trades: 187, win_rate: 56.7, profit_factor: 1.61, total_pnl: 3205.25,
  avg_trade: 17.14, max_drawdown: -412, sharpe_ratio: 1.82, best_day: 845, worst_day: -320,
  by_instrument: FALLBACK_INSTRUMENTS,
};

// Deterministic fallback daily data (seeded, not random)
const FALLBACK_DAILY: DailyRecord[] = [
  { date: "2026-02-19", pnl: 245.50, trades: 12, win_rate: 58.3, equity: 50245.50 },
  { date: "2026-02-20", pnl: 182.25, trades: 10, win_rate: 60.0, equity: 50427.75 },
  { date: "2026-02-21", pnl: -120.00, trades: 8, win_rate: 37.5, equity: 50307.75 },
  { date: "2026-02-24", pnl: 412.00, trades: 15, win_rate: 66.7, equity: 50719.75 },
  { date: "2026-02-25", pnl: 95.75, trades: 9, win_rate: 55.6, equity: 50815.50 },
  { date: "2026-02-26", pnl: -78.50, trades: 11, win_rate: 45.5, equity: 50737.00 },
  { date: "2026-02-27", pnl: 320.00, trades: 13, win_rate: 61.5, equity: 51057.00 },
  { date: "2026-02-28", pnl: 156.25, trades: 7, win_rate: 57.1, equity: 51213.25 },
  { date: "2026-03-03", pnl: 845.00, trades: 14, win_rate: 71.4, equity: 52058.25 },
  { date: "2026-03-04", pnl: -320.00, trades: 12, win_rate: 33.3, equity: 51738.25 },
  { date: "2026-03-05", pnl: 198.50, trades: 10, win_rate: 60.0, equity: 51936.75 },
  { date: "2026-03-06", pnl: 467.00, trades: 11, win_rate: 63.6, equity: 52403.75 },
  { date: "2026-03-07", pnl: 201.50, trades: 9, win_rate: 55.6, equity: 52605.25 },
  { date: "2026-03-10", pnl: -180.00, trades: 13, win_rate: 38.5, equity: 52425.25 },
  { date: "2026-03-11", pnl: 380.00, trades: 12, win_rate: 58.3, equity: 52805.25 },
];

// ─── Main Dashboard Page ─────────────────────────────────────────
export default function Dashboard() {
  const [perf, setPerf] = useState<PerformanceData>(FALLBACK_PERF);
  const [daily, setDaily] = useState<DailyRecord[]>(FALLBACK_DAILY);
  const [tab, setTab] = useState<"overview" | "daily" | "instruments">("overview");
  const [now, setNow] = useState<Date | null>(null);

  useEffect(() => {
    setNow(new Date());
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);

  const fetchData = useCallback(async () => {
    try {
      const [perfRes, dailyRes] = await Promise.all([
        fetch("/api/performance").catch(() => null),
        fetch("/api/daily-history").catch(() => null),
      ]);
      if (perfRes?.ok) setPerf(await perfRes.json());
      if (dailyRes?.ok) {
        const d = await dailyRes.json();
        setDaily(Array.isArray(d) ? d : d.history || []);
      }
    } catch { /* offline */ }
  }, []);

  useEffect(() => {
    fetchData();
    const t = setInterval(fetchData, 30000);
    return () => clearInterval(t);
  }, [fetchData]);

  // formatTime imported from lib/types

  const equityData = daily.map((d) => d.equity);
  const pnlData = daily.map((d) => d.pnl);
  const cumPnl = daily.reduce((acc, d) => { const last = acc.length > 0 ? acc[acc.length - 1] : 0; acc.push(last + d.pnl); return acc; }, [] as number[]);

  return (
    <div className="tui" style={{ height: "100vh", display: "flex", flexDirection: "column", paddingBottom: 17 }}>
      {/* ═══ TOP BAR ═══ */}
      <div style={{
        height: 24, display: "flex", alignItems: "center", padding: "0 8px",
        borderBottom: "1px solid #767676", gap: 16, flexShrink: 0,
      }}>
        <span style={{ color: "#61d6d6", fontWeight: 700 }}>LaT-PFN</span>
        <span style={{ color: "#767676" }}>│</span>
        <Link href="/terminal" style={{ color: "#767676", textDecoration: "none", fontSize: 11 }}>Terminal</Link>
        <span style={{ color: "#f2f2f2", fontWeight: 700, fontSize: 11 }}>Dashboard</span>
        <span style={{ flex: 1 }} />
        <span style={{ color: "#767676" }}>{formatTime(now)}</span>
      </div>

      {/* ═══ TABS ═══ */}
      <div className="tui-tabs">
        {[
          { id: "overview" as const, label: "Overview" },
          { id: "daily" as const, label: "Daily P&L" },
          { id: "instruments" as const, label: "By Instrument" },
        ].map((t) => (
          <div key={t.id} className={`tui-tab ${tab === t.id ? "tui-tab-active" : ""}`} onClick={() => setTab(t.id)}>
            {t.label}
          </div>
        ))}
      </div>

      {/* ═══ CONTENT ═══ */}
      <div style={{ flex: 1, overflow: "auto", padding: 8 }}>

        {tab === "overview" && (
          <div>
            {/* KPI Row */}
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 8, marginBottom: 16 }}>
              {[
                { l: "Total Trades", v: String(perf.total_trades), c: "#f2f2f2" },
                { l: "Win Rate", v: `${perf.win_rate}%`, c: "#16c60c" },
                { l: "Profit Factor", v: perf.profit_factor.toFixed(2), c: "#16c60c" },
                { l: "Total P&L", v: `+$${perf.total_pnl.toLocaleString()}`, c: "#16c60c" },
                { l: "Avg Trade", v: `$${perf.avg_trade.toFixed(2)}`, c: "#f2f2f2" },
                { l: "Max Drawdown", v: `$${perf.max_drawdown}`, c: "#e74856" },
                { l: "Best Day", v: `+$${perf.best_day}`, c: "#16c60c" },
                { l: "Worst Day", v: `$${perf.worst_day}`, c: "#e74856" },
              ].map((k) => (
                <div key={k.l} style={{ border: "1px solid #767676", padding: "8px 12px" }}>
                  <div style={{ color: "#767676", fontSize: 10, textTransform: "uppercase", marginBottom: 2 }}>{k.l}</div>
                  <div style={{ color: k.c, fontWeight: 700, fontSize: 16, fontVariantNumeric: "tabular-nums" }}>{k.v}</div>
                </div>
              ))}
            </div>

            {/* Equity Curve Sparkline */}
            <div style={{ border: "1px solid #767676", padding: "8px 12px", marginBottom: 8, position: "relative" }}>
              <span style={{ position: "absolute", top: "-0.65em", left: 16, background: "#0c0c0c", padding: "0 8px", color: "#61d6d6", fontWeight: 700, fontSize: 11, textTransform: "uppercase" }}>
                Equity Curve
              </span>
              <div style={{ marginTop: 8, fontSize: 14, letterSpacing: 0 }}>
                <Sparkline data={equityData} width={60} />
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", marginTop: 4, fontSize: 10, color: "#767676" }}>
                <span>{daily[0]?.date || ""}</span>
                <span>{daily[daily.length - 1]?.date || ""}</span>
              </div>
            </div>

            {/* Cumulative P&L Sparkline */}
            <div style={{ border: "1px solid #767676", padding: "8px 12px", position: "relative" }}>
              <span style={{ position: "absolute", top: "-0.65em", left: 16, background: "#0c0c0c", padding: "0 8px", color: "#61d6d6", fontWeight: 700, fontSize: 11, textTransform: "uppercase" }}>
                Cumulative P&L
              </span>
              <div style={{ marginTop: 8, fontSize: 14 }}>
                <Sparkline data={cumPnl} width={60} />
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", marginTop: 4, fontSize: 10, color: "#767676" }}>
                <span>$0</span>
                <span>+${cumPnl[cumPnl.length - 1]?.toFixed(0) || "0"}</span>
              </div>
            </div>
          </div>
        )}

        {tab === "daily" && (
          <div>
            <div style={{ border: "1px solid #767676", padding: "8px 12px", marginBottom: 8, position: "relative" }}>
              <span style={{ position: "absolute", top: "-0.65em", left: 16, background: "#0c0c0c", padding: "0 8px", color: "#61d6d6", fontWeight: 700, fontSize: 11, textTransform: "uppercase" }}>
                Daily P&L
              </span>
              <div style={{ marginTop: 4, fontSize: 14 }}>
                <Sparkline data={pnlData} width={60} />
              </div>
            </div>
            <table className="tui-table" style={{ marginTop: 12 }}>
              <thead>
                <tr>
                  <th>Date</th>
                  <th className="num">Trades</th>
                  <th className="num">Win Rate</th>
                  <th className="num">P&L</th>
                  <th>Bar</th>
                  <th className="num">Equity</th>
                </tr>
              </thead>
              <tbody>
                {[...daily].reverse().map((d, i) => {
                  const maxPnl = Math.max(...daily.map((x) => Math.abs(x.pnl)), 1);
                  return (
                    <tr key={i}>
                      <td style={{ color: "#767676" }}>{d.date}</td>
                      <td className="num">{d.trades}</td>
                      <td className="num" style={{ color: d.win_rate >= 50 ? "#16c60c" : "#e74856" }}>{d.win_rate.toFixed(1)}%</td>
                      <td className="num" style={{ color: d.pnl >= 0 ? "#16c60c" : "#e74856" }}>
                        {d.pnl >= 0 ? "+" : ""}${d.pnl.toFixed(2)}
                      </td>
                      <td>
                        <Bar value={d.pnl} max={maxPnl} width={12} color={d.pnl >= 0 ? "#16c60c" : "#e74856"} />
                      </td>
                      <td className="num" style={{ color: "#f2f2f2" }}>${d.equity.toLocaleString(undefined, { minimumFractionDigits: 2 })}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {tab === "instruments" && (
          <div>
            <table className="tui-table">
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th className="num">Trades</th>
                  <th className="num">Win Rate</th>
                  <th className="num">PF</th>
                  <th className="num">Avg Trade</th>
                  <th className="num">P&L</th>
                  <th>Bar</th>
                </tr>
              </thead>
              <tbody>
                {perf.by_instrument.map((inst, i) => {
                  const maxPnl = Math.max(...perf.by_instrument.map((x) => Math.abs(x.pnl)), 1);
                  return (
                    <tr key={i}>
                      <td style={{ fontWeight: 700 }}>{inst.symbol}</td>
                      <td className="num">{inst.trades}</td>
                      <td className="num" style={{ color: inst.win_rate >= 50 ? "#16c60c" : "#e74856" }}>
                        {inst.win_rate.toFixed(1)}%
                      </td>
                      <td className="num" style={{ color: inst.pf >= 1 ? "#16c60c" : "#e74856" }}>
                        {inst.pf.toFixed(2)}
                      </td>
                      <td className="num">${inst.avg_trade.toFixed(2)}</td>
                      <td className="num" style={{ color: inst.pnl >= 0 ? "#16c60c" : "#e74856" }}>
                        +${inst.pnl.toLocaleString()}
                      </td>
                      <td>
                        <Bar value={inst.pnl} max={maxPnl} width={16} color={inst.pnl >= 0 ? "#16c60c" : "#e74856"} />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>

            {/* Win rate comparison bars */}
            <div style={{ border: "1px solid #767676", padding: "8px 12px", marginTop: 16, position: "relative" }}>
              <span style={{ position: "absolute", top: "-0.65em", left: 16, background: "#0c0c0c", padding: "0 8px", color: "#61d6d6", fontWeight: 700, fontSize: 11, textTransform: "uppercase" }}>
                Win Rate Comparison
              </span>
              <div style={{ marginTop: 8 }}>
                {perf.by_instrument.map((inst) => (
                  <div key={inst.symbol} className="tui-row" style={{ padding: "2px 0" }}>
                    <span style={{ color: "#f2f2f2", fontWeight: 700, minWidth: "5ch" }}>{inst.symbol}</span>
                    <span className="tui-bar-track">
                      <Bar value={inst.win_rate} max={100} width={25} color={inst.win_rate >= 55 ? "#16c60c" : inst.win_rate >= 50 ? "#c19c00" : "#e74856"} />
                    </span>
                    <span style={{ color: "#f2f2f2", fontWeight: 700, minWidth: "6ch", textAlign: "right" }}>{inst.win_rate}%</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* ═══ VIM STATUS LINE ═══ */}
      <div className="tui-statusline">
        <span className="tui-statusline-mode">NORMAL</span>
        <span style={{ padding: "0 8px" }}>latpfn-dashboard</span>
        <span style={{ color: "#767676" }}>│</span>
        <span style={{ padding: "0 8px" }}>{perf.total_trades} trades</span>
        <span className="tui-statusline-right">
          <span style={{ color: "#13a10e", fontWeight: 700 }}>+${perf.total_pnl.toLocaleString()}</span>
          <span style={{ color: "#767676" }}> │ </span>
          {formatTime(now)}
        </span>
      </div>
    </div>
  );
}
