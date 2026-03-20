"use client";

import { useState, useEffect } from "react";
import type { Position, Trade } from "@/lib/types";

export default function OrderPanel() {
  const [tab, setTab] = useState<"positions" | "trades" | "signals">("positions");
  const [positions, setPositions] = useState<Position[]>([]);
  const [trades, setTrades] = useState<Trade[]>([]);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [posRes, tradesRes] = await Promise.all([
          fetch("/api/positions").catch(() => null),
          fetch("/api/trades/recent").catch(() => null),
        ]);

        if (posRes?.ok) {
          const posData = await posRes.json();
          setPositions(Array.isArray(posData) ? posData : posData.positions || []);
        }
        if (tradesRes?.ok) {
          const trData = await tradesRes.json();
          setTrades(Array.isArray(trData) ? trData.slice(0, 20) : (trData.trades || []).slice(0, 20));
        }
      } catch { /* backend not running */ }
    };

    fetchData();
    const interval = setInterval(fetchData, 15000);
    return () => clearInterval(interval);
  }, []);

  const tabs = [
    { id: "positions" as const, label: `Positions (${positions.length})` },
    { id: "trades" as const, label: "Trades" },
    { id: "signals" as const, label: "Signals" },
  ];

  return (
    <div className="h-full flex flex-col">
      <div className="tv-tabs">
        {tabs.map((t) => (
          <div
            key={t.id}
            className={`tv-tab ${tab === t.id ? "tv-tab-active" : ""}`}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </div>
        ))}
      </div>

      <div className="flex-1 overflow-y-auto">
        {tab === "positions" && (
          <table className="tv-table">
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Side</th>
                <th className="num">Entry</th>
                <th className="num">SL</th>
                <th className="num">TP</th>
                <th className="num">P&L</th>
                <th>Tier</th>
              </tr>
            </thead>
            <tbody>
              {positions.length === 0 ? (
                <tr>
                  <td colSpan={7} style={{ textAlign: "center", color: "var(--tv-text-dim)", padding: 20 }}>
                    No open positions
                  </td>
                </tr>
              ) : (
                positions.map((p, i) => (
                  <tr key={i}>
                    <td style={{ fontWeight: 600 }}>{p.instrument}</td>
                    <td>
                      <span className={`tv-badge ${p.direction === "long" ? "tv-badge-long" : "tv-badge-short"}`}>
                        {p.direction?.toUpperCase()}
                      </span>
                    </td>
                    <td className="num">{p.entry_price?.toFixed(2)}</td>
                    <td className="num text-red">{p.stop_loss?.toFixed(2)}</td>
                    <td className="num text-green">{p.take_profit?.toFixed(2)}</td>
                    <td className="num" style={{ color: (p.pnl || 0) >= 0 ? "var(--tv-green)" : "var(--tv-red)" }}>
                      {(p.pnl || 0) >= 0 ? "+" : ""}${(p.pnl || 0).toFixed(2)}
                    </td>
                    <td style={{ color: "var(--tv-text-dim)", fontSize: 11 }}>{p.tier}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        )}

        {tab === "trades" && (
          <table className="tv-table">
            <thead>
              <tr>
                <th>Time</th>
                <th>Symbol</th>
                <th>Side</th>
                <th className="num">Entry</th>
                <th className="num">Exit</th>
                <th className="num">P&L</th>
                <th>Tier</th>
              </tr>
            </thead>
            <tbody>
              {trades.length === 0 ? (
                <tr>
                  <td colSpan={7} style={{ textAlign: "center", color: "var(--tv-text-dim)", padding: 20 }}>
                    No recent trades
                  </td>
                </tr>
              ) : (
                trades.map((t, i) => (
                  <tr key={i}>
                    <td style={{ color: "var(--tv-text-dim)", fontSize: 11 }}>
                      {t.timestamp ? new Date(t.timestamp).toLocaleTimeString() : "--"}
                    </td>
                    <td style={{ fontWeight: 600 }}>{t.instrument}</td>
                    <td>
                      <span className={`tv-badge ${t.direction === "long" ? "tv-badge-long" : "tv-badge-short"}`}>
                        {t.direction?.toUpperCase()}
                      </span>
                    </td>
                    <td className="num">{t.entry_price?.toFixed(2)}</td>
                    <td className="num">{t.exit_price?.toFixed(2) || "--"}</td>
                    <td className="num" style={{ color: (t.pnl || 0) >= 0 ? "var(--tv-green)" : "var(--tv-red)" }}>
                      {(t.pnl || 0) >= 0 ? "+" : ""}${(t.pnl || 0).toFixed(2)}
                    </td>
                    <td style={{ color: "var(--tv-text-dim)", fontSize: 11 }}>{t.tier}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        )}

        {tab === "signals" && (
          <div style={{ padding: 16, color: "var(--tv-text-dim)", textAlign: "center" }}>
            <p>Signal feed updates every 5 minutes during market hours.</p>
            <p style={{ marginTop: 8, fontSize: 11 }}>CME Globex: Sun 6PM — Fri 5PM ET</p>
          </div>
        )}
      </div>
    </div>
  );
}
