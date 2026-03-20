"use client";

import { useState, useEffect } from "react";
import type { AccountData } from "@/lib/types";

export default function AccountPanel() {
  const [account, setAccount] = useState<AccountData | null>(null);

  useEffect(() => {
    const fetchAccount = async () => {
      try {
        const res = await fetch("/api/account");
        if (res.ok) {
          const data = await res.json();
          setAccount(data);
        }
      } catch { /* not running */ }
    };

    fetchAccount();
    const interval = setInterval(fetchAccount, 15000);
    return () => clearInterval(interval);
  }, []);

  const metrics = account
    ? [
        { label: "Equity", value: `$${account.equity?.toLocaleString()}`, color: "var(--tv-text)" },
        { label: "Daily P&L", value: `${(account.daily_pnl || 0) >= 0 ? "+" : ""}$${(account.daily_pnl || 0).toFixed(2)}`, color: (account.daily_pnl || 0) >= 0 ? "var(--tv-green)" : "var(--tv-red)" },
        { label: "Unrealized", value: `${(account.unrealized_pnl || 0) >= 0 ? "+" : ""}$${(account.unrealized_pnl || 0).toFixed(2)}`, color: (account.unrealized_pnl || 0) >= 0 ? "var(--tv-green)" : "var(--tv-red)" },
        { label: "DD Cushion", value: `$${(account.cushion || 0).toFixed(0)}`, color: (account.cushion || 0) > 1000 ? "var(--tv-green)" : "var(--tv-red)" },
        { label: "Positions", value: `${account.positions_open || 0}`, color: "var(--tv-text)" },
        { label: "Daily Limit", value: `$${(account.max_daily_loss || 1000).toFixed(0)}`, color: "var(--tv-text-muted)" },
      ]
    : [
        { label: "Equity", value: "$50,000", color: "var(--tv-text)" },
        { label: "Daily P&L", value: "--", color: "var(--tv-text-muted)" },
        { label: "Unrealized", value: "--", color: "var(--tv-text-muted)" },
        { label: "DD Cushion", value: "--", color: "var(--tv-text-muted)" },
        { label: "Positions", value: "0", color: "var(--tv-text)" },
        { label: "Daily Limit", value: "$1,000", color: "var(--tv-text-muted)" },
      ];

  const cushionPct = account ? Math.min(100, ((account.cushion || 0) / 2000) * 100) : 100;
  const dailyUsedPct = account
    ? Math.min(100, (Math.abs(account.daily_pnl || 0) / (account.max_daily_loss || 1000)) * 100)
    : 0;

  return (
    <div className="h-full flex flex-col">
      <div className="tv-panel-header">Account</div>
      <div className="flex-1 overflow-y-auto" style={{ padding: "8px 12px" }}>
        {metrics.map((m) => (
          <div key={m.label} className="tv-metric">
            <span className="tv-metric-label">{m.label}</span>
            <span className="tv-metric-value" style={{ color: m.color }}>
              {m.value}
            </span>
          </div>
        ))}

        {/* Risk bars */}
        <div style={{ marginTop: 12 }}>
          <div style={{ fontSize: 11, color: "var(--tv-text-dim)", marginBottom: 4 }}>
            Drawdown Cushion
          </div>
          <div style={{ height: 4, background: "var(--tv-bg-tertiary)", borderRadius: 2, overflow: "hidden" }}>
            <div
              style={{
                height: "100%",
                width: `${cushionPct}%`,
                background: cushionPct > 50 ? "var(--tv-green)" : cushionPct > 25 ? "var(--tv-yellow)" : "var(--tv-red)",
                borderRadius: 2,
                transition: "width 0.5s",
              }}
            />
          </div>
        </div>

        <div style={{ marginTop: 8 }}>
          <div style={{ fontSize: 11, color: "var(--tv-text-dim)", marginBottom: 4 }}>
            Daily Loss Used
          </div>
          <div style={{ height: 4, background: "var(--tv-bg-tertiary)", borderRadius: 2, overflow: "hidden" }}>
            <div
              style={{
                height: "100%",
                width: `${dailyUsedPct}%`,
                background: dailyUsedPct < 50 ? "var(--tv-green)" : dailyUsedPct < 75 ? "var(--tv-yellow)" : "var(--tv-red)",
                borderRadius: 2,
                transition: "width 0.5s",
              }}
            />
          </div>
        </div>

        {/* Performance summary */}
        <div style={{ marginTop: 16, paddingTop: 12, borderTop: "1px solid var(--tv-border)" }}>
          <div style={{ fontSize: 11, color: "var(--tv-text-dim)", marginBottom: 8, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.5px" }}>
            Live Performance
          </div>
          {[
            { label: "Total Trades", value: "187" },
            { label: "Win Rate", value: "56.7%", color: "var(--tv-green)" },
            { label: "Profit Factor", value: "1.61", color: "var(--tv-green)" },
            { label: "Total P&L", value: "+$3,205", color: "var(--tv-green)" },
          ].map((s) => (
            <div key={s.label} className="tv-metric">
              <span className="tv-metric-label">{s.label}</span>
              <span className="tv-metric-value" style={{ color: s.color || "var(--tv-text)" }}>
                {s.value}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
