"use client";

import { useEffect } from "react";

export default function TerminalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("Terminal error:", error);
  }, [error]);

  return (
    <div className="tui" style={{
      height: "100vh",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
    }}>
      <div style={{ textAlign: "center", maxWidth: 480 }}>
        <div style={{ color: "#e74856", fontWeight: 700, marginBottom: 8 }}>
          [ERROR] Terminal crashed
        </div>
        <pre style={{ color: "#767676", fontSize: 11, marginBottom: 16, whiteSpace: "pre-wrap" }}>
          {error.message}
        </pre>
        <button onClick={reset} className="tui-btn" style={{ marginRight: 8 }}>
          Retry
        </button>
        <a href="/" className="tui-btn" style={{ textDecoration: "none" }}>
          Home
        </a>
      </div>
    </div>
  );
}
