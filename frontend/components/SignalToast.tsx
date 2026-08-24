"use client";

import { useEffect } from "react";
import type { Signal } from "@/lib/types";

interface SignalToastProps {
  toasts: Signal[];
  onDismiss: (index: number) => void;
}

export default function SignalToast({ toasts, onDismiss }: SignalToastProps) {
  // Auto-dismiss after 10 seconds
  useEffect(() => {
    if (toasts.length === 0) return;
    const timer = setTimeout(() => onDismiss(0), 10000);
    return () => clearTimeout(timer);
  }, [toasts, onDismiss]);

  if (toasts.length === 0) return null;

  return (
    <div style={{
      position: "fixed", bottom: 28, right: 16, zIndex: 100,
      display: "flex", flexDirection: "column", gap: 8, maxWidth: 320,
    }}>
      {toasts.slice(0, 3).map((s, i) => (
        <div
          key={`${s.instrument}-${s.timestamp}-${i}`}
          onClick={() => onDismiss(i)}
          style={{
            background: "#1a1a2e",
            border: "1px solid #61d6d6",
            borderRadius: 6,
            padding: "10px 14px",
            cursor: "pointer",
            fontFamily: "'JetBrains Mono', 'Source Code Pro', monospace",
            fontSize: 12,
            animation: "toast-slide-in 0.3s ease-out",
            boxShadow: "0 4px 16px rgba(0,0,0,0.5)",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
            <span style={{ color: "#61d6d6", fontWeight: 700, fontSize: 10, textTransform: "uppercase" }}>New Signal</span>
            <span style={{ fontWeight: 700, color: "#f2f2f2" }}>{s.instrument}</span>
            <span style={{ color: s.direction === "long" ? "#16c60c" : "#e74856", fontWeight: 700 }}>
              {s.direction?.toUpperCase()}
            </span>
            <span className={`tier-${s.tier}`} style={{ fontSize: 10 }}>{s.tier}</span>
          </div>
          <div style={{ display: "flex", gap: 16, color: "#999" }}>
            <span>Entry <span style={{ color: "#f2f2f2" }}>{s.entry?.toFixed(2)}</span></span>
            <span>SL <span style={{ color: "#e74856" }}>{s.stop_loss?.toFixed(2)}</span></span>
            <span>TP <span style={{ color: "#16c60c" }}>{s.take_profit?.toFixed(2)}</span></span>
          </div>
        </div>
      ))}
      <style jsx>{`
        @keyframes toast-slide-in {
          from { opacity: 0; transform: translateX(100px); }
          to { opacity: 1; transform: translateX(0); }
        }
      `}</style>
    </div>
  );
}
