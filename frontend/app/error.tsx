"use client";

import { useEffect } from "react";

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("App error:", error);
  }, [error]);

  return (
    <div style={{
      minHeight: "100vh",
      background: "#0c0c0c",
      color: "#cccccc",
      fontFamily: "'JetBrains Mono', monospace",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      padding: 32,
    }}>
      <div style={{ maxWidth: 480, textAlign: "center" }}>
        <div style={{ color: "#e74856", fontWeight: 700, fontSize: 14, marginBottom: 8 }}>
          [ERROR] Something went wrong
        </div>
        <div style={{ color: "#767676", fontSize: 12, marginBottom: 24, lineHeight: 1.6 }}>
          {error.message || "An unexpected error occurred."}
        </div>
        <button
          onClick={reset}
          style={{
            background: "none",
            border: "none",
            color: "#cccccc",
            fontFamily: "inherit",
            fontSize: 12,
            cursor: "pointer",
          }}
        >
          [ Retry ]
        </button>
        <span style={{ color: "#767676", margin: "0 8px" }}>|</span>
        <a href="/" style={{ color: "#61d6d6", textDecoration: "none", fontSize: 12 }}>
          [ Home ]
        </a>
      </div>
    </div>
  );
}
