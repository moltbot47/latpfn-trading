// Shared types for the LaT-PFN frontend

export interface Position {
  instrument: string;
  direction: string;
  entry_price: number;
  size: number;
  pnl: number;
  tier: string;
  stop_loss: number;
  take_profit: number;
  time_held: string;
}

export interface Trade {
  instrument: string;
  direction: string;
  entry_price: number;
  exit_price: number;
  pnl: number;
  tier: string;
  timestamp: string;
  status: string;
}

export interface Signal {
  instrument: string;
  direction: string;
  tier: string;
  confidence: number;
  entry: number;
  stop_loss: number;
  take_profit: number;
  regime: string;
  timestamp: string;
}

export interface AccountData {
  equity: number;
  daily_pnl: number;
  unrealized_pnl: number;
  starting_balance: number;
  drawdown_floor: number;
  cushion: number;
  max_daily_loss: number;
  high_water_mark: number;
  positions_open: number;
}

export interface Instrument {
  symbol: string;
  name: string;
  last: number;
  change: number;
  changePct: number;
}

/** Safe changePct calculation — avoids division by zero */
export function safeChangePct(change: number, last: number): number {
  const base = last - change;
  if (base === 0) return 0;
  return Math.round((change / base) * 10000) / 100;
}

/** Format a Date (or null) as HH:MM:SS */
export function formatTime(d: Date | null): string {
  return d
    ? d.toLocaleTimeString("en-US", { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" })
    : "--:--:--";
}
