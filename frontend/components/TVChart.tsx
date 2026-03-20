"use client";

import { useEffect, useRef } from "react";
import { createChart, ColorType, CandlestickSeries } from "lightweight-charts";

import type { Time } from "lightweight-charts";

interface CandleData {
  time: Time;
  open: number;
  high: number;
  low: number;
  close: number;
}

interface TVChartProps {
  symbol?: string;
  data?: CandleData[];
}

export default function TVChart({ symbol = "MNQ", data }: TVChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<any>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: "#131722" },
        textColor: "#787B86",
        fontSize: 11,
      },
      grid: {
        vertLines: { color: "rgba(42, 46, 57, 0.6)" },
        horzLines: { color: "rgba(42, 46, 57, 0.6)" },
      },
      crosshair: {
        vertLine: { color: "#758696", width: 1, style: 3 },
        horzLine: { color: "#758696", width: 1, style: 3 },
      },
      rightPriceScale: {
        borderColor: "#363A45",
      },
      timeScale: {
        borderColor: "#363A45",
        timeVisible: true,
        secondsVisible: false,
      },
    });

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: "#26A69A",
      downColor: "#EF5350",
      borderUpColor: "#26A69A",
      borderDownColor: "#EF5350",
      wickUpColor: "#26A69A",
      wickDownColor: "#EF5350",
    });

    // Use provided data or generate sample
    if (data && data.length > 0) {
      candleSeries.setData(data);
    } else {
      // Generate realistic sample data
      const sampleData = generateSampleData(symbol);
      candleSeries.setData(sampleData);
    }

    chart.timeScale().fitContent();
    chartRef.current = chart;

    const handleResize = () => {
      if (containerRef.current) {
        chart.applyOptions({
          width: containerRef.current.clientWidth,
          height: containerRef.current.clientHeight,
        });
      }
    };

    const observer = new ResizeObserver(handleResize);
    observer.observe(containerRef.current);

    return () => {
      observer.disconnect();
      chart.remove();
    };
  }, [symbol, data]);

  return <div ref={containerRef} style={{ width: "100%", height: "100%" }} />;
}

function generateSampleData(symbol: string): CandleData[] {
  const basePrice =
    symbol === "MNQ" ? 20500 :
    symbol === "MYM" ? 42000 :
    symbol === "MES" ? 5800 :
    symbol === "MBT" ? 68000 : 20000;

  const data: CandleData[] = [];
  let price = basePrice;
  const now = new Date();

  for (let i = 200; i >= 0; i--) {
    const date = new Date(now.getTime() - i * 5 * 60000);
    const volatility = basePrice * 0.001;
    const change = (Math.random() - 0.48) * volatility;
    const open = price;
    const close = price + change;
    const high = Math.max(open, close) + Math.random() * volatility * 0.5;
    const low = Math.min(open, close) - Math.random() * volatility * 0.5;
    price = close;

    data.push({
      time: Math.floor(date.getTime() / 1000) as Time,
      open: Math.round(open * 100) / 100,
      high: Math.round(high * 100) / 100,
      low: Math.round(low * 100) / 100,
      close: Math.round(close * 100) / 100,
    });
  }

  return data;
}
