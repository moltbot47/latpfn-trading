"use client";

import { useState, useEffect } from "react";
import type { Instrument } from "@/lib/types";
import { safeChangePct } from "@/lib/types";

interface WatchlistProps {
  onSelect: (symbol: string) => void;
  selected: string;
}

const INSTRUMENTS: Instrument[] = [
  { symbol: "MNQ", name: "Micro Nasdaq", last: 20512.75, change: 45.25, changePct: 0.22 },
  { symbol: "MYM", name: "Micro Dow", last: 42185.00, change: -120.00, changePct: -0.28 },
  { symbol: "MES", name: "Micro S&P", last: 5812.50, change: 8.75, changePct: 0.15 },
  { symbol: "MBT", name: "Micro BTC", last: 68250.00, change: -485.00, changePct: -0.71 },
];

export default function Watchlist({ onSelect, selected }: WatchlistProps) {
  const [instruments, setInstruments] = useState(INSTRUMENTS);

  // Simulate live price updates
  useEffect(() => {
    const interval = setInterval(() => {
      setInstruments((prev) =>
        prev.map((inst) => {
          const tick = (Math.random() - 0.5) * inst.last * 0.0002;
          const newLast = Math.round((inst.last + tick) * 100) / 100;
          const newChange = Math.round((inst.change + tick) * 100) / 100;
          return {
            ...inst,
            last: newLast,
            change: newChange,
            changePct: safeChangePct(newChange, newLast),
          };
        })
      );
    }, 2000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="h-full flex flex-col">
      <div className="tv-panel-header">
        <span>Watchlist</span>
      </div>
      <div className="flex-1 overflow-y-auto">
        <table className="tv-table">
          <thead>
            <tr>
              <th>Symbol</th>
              <th className="num">Last</th>
              <th className="num">Chg%</th>
            </tr>
          </thead>
          <tbody>
            {instruments.map((inst) => (
              <tr
                key={inst.symbol}
                onClick={() => onSelect(inst.symbol)}
                style={{
                  cursor: "pointer",
                  background:
                    selected === inst.symbol
                      ? "rgba(41, 98, 255, 0.1)"
                      : undefined,
                }}
              >
                <td>
                  <div style={{ fontWeight: 600, color: "var(--tv-text)" }}>
                    {inst.symbol}
                  </div>
                  <div style={{ fontSize: 10, color: "var(--tv-text-dim)" }}>
                    {inst.name}
                  </div>
                </td>
                <td className="num" style={{ color: "var(--tv-text)" }}>
                  {inst.last.toLocaleString(undefined, {
                    minimumFractionDigits: 2,
                  })}
                </td>
                <td
                  className="num"
                  style={{
                    color:
                      inst.changePct >= 0 ? "var(--tv-green)" : "var(--tv-red)",
                  }}
                >
                  {inst.changePct >= 0 ? "+" : ""}
                  {inst.changePct.toFixed(2)}%
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        {/* Sections */}
        <div className="tv-panel-header" style={{ marginTop: 8 }}>
          Signals Today
        </div>
        <div style={{ padding: "8px 12px", fontSize: 12 }}>
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              padding: "4px 0",
            }}
          >
            <span style={{ color: "var(--tv-text-muted)" }}>Generated</span>
            <span style={{ fontWeight: 600 }}>--</span>
          </div>
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              padding: "4px 0",
            }}
          >
            <span style={{ color: "var(--tv-text-muted)" }}>Executed</span>
            <span style={{ fontWeight: 600 }}>--</span>
          </div>
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              padding: "4px 0",
            }}
          >
            <span style={{ color: "var(--tv-text-muted)" }}>Win Rate</span>
            <span className="text-green" style={{ fontWeight: 600 }}>
              56.7%
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
