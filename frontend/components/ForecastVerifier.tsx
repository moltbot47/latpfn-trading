"use client";

import { useState } from "react";
import { useReadContract } from "wagmi";
import { SIGNAL_ACCESS_ADDRESS, SIGNAL_ACCESS_ABI } from "@/lib/contract-wagmi";

interface Forecast {
  hash: string;
  timestamp: number;
  instrument: string;
}

export default function ForecastVerifier() {
  const [loadCount, setLoadCount] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const { data: forecasts, isLoading, refetch } = useReadContract({
    address: SIGNAL_ACCESS_ADDRESS,
    abi: SIGNAL_ACCESS_ABI,
    functionName: "getRecentForecasts",
    args: [BigInt(20)],
    query: { enabled: loadCount > 0 },
  });

  const handleLoad = async () => {
    setError(null);
    setLoadCount((c) => c + 1);
    try {
      await refetch();
    } catch (err) {
      setError("Failed to load forecasts. Make sure you're connected to Base network.");
    }
  };

  const items: Forecast[] = forecasts
    ? (forecasts as any[]).map((f) => ({
        hash: f.hash,
        timestamp: Number(f.timestamp),
        instrument: f.instrument,
      }))
    : [];

  return (
    <div style={{ border: "1px solid #767676", padding: "12px", position: "relative" }}>
      <span style={{ position: "absolute", top: "-0.65em", left: 16, background: "#0c0c0c", padding: "0 8px", color: "#61d6d6", fontWeight: 700, fontSize: 11, textTransform: "uppercase" }}>
        On-Chain Verification
      </span>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 4, marginBottom: 8 }}>
        <span style={{ color: "#767676", fontSize: 11 }}>
          Forecast hashes posted on-chain before delivery.
        </span>
        <button
          onClick={handleLoad}
          disabled={isLoading}
          className="tui-btn"
          style={{ fontSize: 11 }}
        >
          {isLoading ? "Loading..." : "Load Hashes"}
        </button>
      </div>

      {error && (
        <div style={{ color: "#e74856", fontSize: 11, marginBottom: 8 }}>
          [ERROR] {error}
        </div>
      )}

      {items.length > 0 ? (
        <table className="tui-table">
          <thead>
            <tr>
              <th>Instrument</th>
              <th>Time</th>
              <th>Hash</th>
            </tr>
          </thead>
          <tbody>
            {items.map((f, i) => (
              <tr key={`${f.hash}-${i}`}>
                <td style={{ fontWeight: 700 }}>{f.instrument}</td>
                <td style={{ color: "#767676" }}>
                  {new Date(f.timestamp * 1000).toLocaleString()}
                </td>
                <td style={{ fontSize: 10, color: "#767676", maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis" }}>
                  {f.hash}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : loadCount > 0 && !isLoading ? (
        <div style={{ textAlign: "center", color: "#767676", padding: 12, fontSize: 11 }}>
          No forecasts found on-chain.
        </div>
      ) : (
        <div style={{ textAlign: "center", color: "#767676", padding: 12, fontSize: 11 }}>
          Click &quot;Load Hashes&quot; to view on-chain forecast records.
        </div>
      )}
    </div>
  );
}
