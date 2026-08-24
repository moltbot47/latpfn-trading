"use client";

import { useEffect, useRef, memo } from "react";

// Free TradingView widget doesn't include CME futures data.
// Use ETF/index equivalents that track the same underlying.
const SYMBOL_MAP: Record<string, string> = {
  MNQ: "NASDAQ:QQQ",      // Tracks Nasdaq 100 (same as MNQ/NQ)
  MYM: "AMEX:DIA",        // Tracks Dow Jones (same as MYM/YM)
  MES: "AMEX:SPY",        // Tracks S&P 500 (same as MES/ES)
  MBT: "COINBASE:BTCUSD", // Bitcoin (same underlying as MBT)
};

interface TVChartProps {
  symbol?: string;
  interval?: string;
}

function TVChartInner({ symbol = "MNQ", interval = "5" }: TVChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    const tvSymbol = SYMBOL_MAP[symbol] || `CME_MINI:${symbol}1!`;

    const widgetConfig = {
      autosize: true,
      symbol: tvSymbol,
      interval: interval,
      timezone: "America/New_York",
      theme: "dark",
      style: "1",
      locale: "en",
      backgroundColor: "rgba(19, 23, 34, 1)",
      gridColor: "rgba(42, 46, 57, 0.6)",
      hide_top_toolbar: false,
      hide_side_toolbar: false,
      allow_symbol_change: false,
      save_image: false,
      calendar: false,
      details: false,
      hotlist: false,
      show_popup_button: false,
      support_host: "https://www.tradingview.com",
    };

    const script = document.createElement("script");
    script.src = "https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js";
    script.type = "text/javascript";
    script.async = true;
    script.innerHTML = JSON.stringify(widgetConfig);

    const wrapper = document.createElement("div");
    wrapper.className = "tradingview-widget-container__widget";
    wrapper.style.height = "100%";
    wrapper.style.width = "100%";

    const container = containerRef.current;
    container.innerHTML = "";
    container.appendChild(wrapper);
    container.appendChild(script);

    return () => {
      container.innerHTML = "";
    };
  }, [symbol, interval]);

  return (
    <div
      ref={containerRef}
      className="tradingview-widget-container"
      style={{ width: "100%", height: "100%" }}
    />
  );
}

// Memo with key-based re-mount from parent — prevents unnecessary re-renders
const TVChart = memo(TVChartInner);
export default TVChart;
