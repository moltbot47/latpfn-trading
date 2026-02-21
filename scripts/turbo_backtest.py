#!/usr/bin/env python3
"""
Turbo Strategy Backtester — replays real 5-min crypto price data
against old vs new strategy logic.

Data source: yfinance 5-minute bars (up to 60 days history)

For each 5-minute window:
  1. Compute actual Up/Down outcome from OHLC
  2. Simulate market pricing (how Polymarket would price it mid-window)
  3. Apply strategy logic (contrarian, market_lean, filters)
  4. Track PnL with proper bet sizing

Usage:
    python scripts/turbo_backtest.py [--days 30] [--bet 1.0] [--verbose]
"""

import argparse
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import yfinance as yf
import numpy as np
import pandas as pd


ASSETS = {
    "btc": "BTC-USD",
    "eth": "ETH-USD",
    "sol": "SOL-USD",
    "xrp": "XRP-USD",
}

# ── Simulated Polymarket pricing ──────────────────────────────────
# In real markets, the Up/Down price reflects how likely the market
# thinks Up is. We simulate this from recent momentum.


@dataclass
class BacktestTrade:
    """One simulated trade."""
    timestamp: str
    asset: str
    direction: str
    signal_type: str
    entry_price: float
    outcome: str  # "win" or "loss"
    pnl: float
    bet_size: float
    streak_mult: float
    mom_strength: float
    mom_direction: str


@dataclass
class StrategyState:
    """Mutable state for a strategy variant."""
    name: str
    consecutive_wins: int = 0
    consecutive_losses: int = 0
    cooldown_until: float = 0.0
    trades: List[BacktestTrade] = field(default_factory=list)
    total_pnl: float = 0.0
    wins: int = 0
    losses: int = 0
    skipped_cooldown: int = 0
    skipped_momentum: int = 0
    skipped_direction: int = 0
    skipped_price: int = 0


def fetch_data(days: int) -> Dict[str, pd.DataFrame]:
    """Fetch 5-min OHLCV for all assets."""
    data = {}
    for asset, symbol in ASSETS.items():
        print(f"  Fetching {symbol} ({days}d, 5m bars)...", end=" ", flush=True)
        tk = yf.Ticker(symbol)
        df = tk.history(period=f"{days}d", interval="5m")
        if df.empty:
            print("FAILED")
            continue
        print(f"{len(df)} bars")
        data[asset] = df
    return data


def compute_momentum(prices: deque, current_price: float) -> Tuple[Optional[str], float]:
    """Compute momentum direction and strength from recent price history."""
    if len(prices) < 3:
        return None, 0.0

    # 1-minute lookback (last ~12 entries at 5s, but we have 5m bars, so use last 1)
    price_1m = prices[-1] if len(prices) >= 1 else current_price
    # 3-minute lookback (use 3 bars back)
    price_3m = prices[-3] if len(prices) >= 3 else prices[0]

    pct_1m = (current_price - price_1m) / price_1m if price_1m else 0
    pct_3m = (current_price - price_3m) / price_3m if price_3m else 0

    combined = pct_1m * 0.6 + pct_3m * 0.4
    threshold = 0.0003  # Same as strategy

    if abs(combined) < threshold:
        direction = None
    else:
        direction = "Up" if combined > 0 else "Down"

    strength = min(abs(combined) / 0.005, 1.0)
    return direction, strength


def simulate_market_price(
    open_price: float, close_price: float, mid_point_price: float
) -> Tuple[float, float]:
    """
    Simulate Polymarket Up/Down prices at the midpoint of the window.

    Returns (up_price, down_price).
    In real Polymarket:
      - If crypto trending up → Up is expensive (0.55-0.75), Down is cheap
      - If crypto trending down → Down is expensive, Up is cheap
      - Baseline is ~0.50/0.50

    We use the midpoint price relative to open to estimate market lean.
    """
    # Price change from open to midpoint
    if open_price == 0:
        return 0.50, 0.50

    pct_change = (mid_point_price - open_price) / open_price

    # Map to Up probability: baseline 0.50, scaled by momentum
    # Typical Polymarket pricing: 0.30-0.70 range for 5-min markets
    up_prob = 0.50 + pct_change * 200  # 0.5% move → 0.60 Up price
    up_prob = max(0.20, min(0.80, up_prob))

    return up_prob, 1.0 - up_prob


def run_strategy_old(
    state: StrategyState,
    asset: str,
    timestamp: str,
    up_price: float,
    down_price: float,
    outcome_up: bool,
    mom_dir: Optional[str],
    mom_strength: float,
    bet_size: float,
    intel_multiplier: float = 1.2,
):
    """OLD strategy: pure contrarian, 5-loss cooldown, uncapped intel multiplier."""
    now_ts = pd.Timestamp(timestamp).timestamp()

    # 5-loss cooldown (old threshold)
    if now_ts < state.cooldown_until:
        state.skipped_cooldown += 1
        return

    # Contrarian logic
    direction = None
    entry_price = None

    if up_price >= 0.60 and up_price <= 0.85:
        direction = "Down"
        entry_price = down_price
    elif down_price >= 0.60 and down_price <= 0.85:
        direction = "Up"
        entry_price = up_price

    if not direction:
        return

    # Old: Block Down direction (edge engine existed but with 5-loss cooldown)
    # For fairness, apply the same direction/asset blocks as old edge engine
    # We'll skip this since we want to see the RAW old strategy performance

    # Entry band: old was 0.28-0.45
    if entry_price < 0.28 or entry_price > 0.45:
        state.skipped_price += 1
        return

    # Old intel multiplier (uncapped, could be >1.0)
    adjusted_bet = bet_size * intel_multiplier
    shares = adjusted_bet / entry_price if entry_price > 0 else 0

    # Determine outcome
    if direction == "Up":
        won = outcome_up
    else:
        won = not outcome_up

    pnl = (1.0 - entry_price) * shares if won else -entry_price * shares

    trade = BacktestTrade(
        timestamp=timestamp, asset=asset, direction=direction,
        signal_type="contrarian", entry_price=entry_price,
        outcome="win" if won else "loss", pnl=pnl,
        bet_size=adjusted_bet, streak_mult=1.0,
        mom_strength=mom_strength, mom_direction=mom_dir or "",
    )
    state.trades.append(trade)
    state.total_pnl += pnl

    if won:
        state.wins += 1
        state.consecutive_losses = 0
        state.consecutive_wins += 1
    else:
        state.losses += 1
        state.consecutive_wins = 0
        state.consecutive_losses += 1
        if state.consecutive_losses >= 5:  # OLD threshold
            level = state.consecutive_losses - 5
            cooldown = 30 * (2 ** min(level, 4))  # OLD: 30s base
            state.cooldown_until = now_ts + cooldown


def run_strategy_new(
    state: StrategyState,
    asset: str,
    timestamp: str,
    up_price: float,
    down_price: float,
    outcome_up: bool,
    mom_dir: Optional[str],
    mom_strength: float,
    bet_size: float,
):
    """NEW strategy: hybrid contrarian+lean, 2-loss cooldown, streak sizing, capped intel."""
    now_ts = pd.Timestamp(timestamp).timestamp()

    # 2-loss cooldown (NEW threshold)
    if now_ts < state.cooldown_until:
        state.skipped_cooldown += 1
        return

    # Determine market lean
    market_up_lean = up_price >= 0.60 and up_price <= 0.85
    market_down_lean = down_price >= 0.60 and down_price <= 0.85

    direction = None
    entry_price = None
    signal_type = "contrarian"

    # MODE 1: Market lean WITH momentum confirmation → follow market
    if market_up_lean and mom_dir == "Up" and mom_strength > 0.2:
        direction = "Up"
        entry_price = up_price
        signal_type = "market_lean"
    elif market_down_lean and mom_dir == "Down" and mom_strength > 0.2:
        direction = "Down"
        entry_price = down_price
        signal_type = "market_lean"
    # MODE 2: Contrarian
    elif market_up_lean:
        direction = "Down"
        entry_price = down_price
        signal_type = "contrarian"
    elif market_down_lean:
        direction = "Up"
        entry_price = up_price
        signal_type = "contrarian"

    if not direction:
        return

    # Momentum conflict filter (NEW)
    if mom_dir and mom_strength > 0.3:
        if (direction == "Up" and mom_dir == "Down") or \
           (direction == "Down" and mom_dir == "Up"):
            state.skipped_momentum += 1
            return

    # Entry band: 0.28-0.45
    if entry_price < 0.28 or entry_price > 0.45:
        state.skipped_price += 1
        return

    # Streak-based sizing (NEW)
    if state.consecutive_wins >= 3:
        streak_mult = 1.75
    elif state.consecutive_wins >= 2:
        streak_mult = 1.5
    elif state.consecutive_losses >= 1:
        streak_mult = 0.5
    else:
        streak_mult = 1.0

    # Intel multiplier CAPPED at 1.0 (NEW)
    intel_mult = 1.0  # Capped

    adjusted_bet = bet_size * streak_mult * intel_mult
    shares = adjusted_bet / entry_price if entry_price > 0 else 0

    # Determine outcome
    if direction == "Up":
        won = outcome_up
    else:
        won = not outcome_up

    pnl = (1.0 - entry_price) * shares if won else -entry_price * shares

    trade = BacktestTrade(
        timestamp=timestamp, asset=asset, direction=direction,
        signal_type=signal_type, entry_price=entry_price,
        outcome="win" if won else "loss", pnl=pnl,
        bet_size=adjusted_bet, streak_mult=streak_mult,
        mom_strength=mom_strength, mom_direction=mom_dir or "",
    )
    state.trades.append(trade)
    state.total_pnl += pnl

    if won:
        state.wins += 1
        state.consecutive_losses = 0
        state.consecutive_wins += 1
    else:
        state.losses += 1
        state.consecutive_wins = 0
        state.consecutive_losses += 1
        if state.consecutive_losses >= 2:  # NEW threshold
            level = state.consecutive_losses - 2
            cooldown = 60 * (2 ** min(level, 4))  # NEW: 60s base
            state.cooldown_until = now_ts + cooldown


def run_backtest(days: int, bet_size: float, verbose: bool):
    """Run full backtest comparing old vs new strategy."""
    print(f"\n{'='*70}")
    print(f"  TURBO STRATEGY BACKTEST — {days} days of real 5-min crypto data")
    print(f"  Bet size: ${bet_size:.2f} | Assets: {', '.join(ASSETS.keys())}")
    print(f"{'='*70}\n")

    # Fetch data
    print("Fetching historical data...")
    all_data = fetch_data(days)
    if not all_data:
        print("ERROR: No data fetched")
        return

    total_bars = sum(len(df) for df in all_data.values())
    print(f"\nTotal data: {total_bars} bars across {len(all_data)} assets")

    date_range = None
    for df in all_data.values():
        if not df.empty:
            date_range = f"{df.index[0].strftime('%Y-%m-%d')} → {df.index[-1].strftime('%Y-%m-%d')}"
            break
    print(f"Date range: {date_range}\n")

    # Initialize strategy states
    old_state = StrategyState(name="OLD (pure contrarian, 5L cooldown)")
    new_state = StrategyState(name="NEW (hybrid, 2L cooldown, streak sizing)")

    # Track price history per asset for momentum calculation
    price_histories: Dict[str, deque] = {
        asset: deque(maxlen=20) for asset in ASSETS
    }

    total_windows = 0
    windows_with_signal = 0

    # Process each 5-min window
    for asset, df in sorted(all_data.items()):
        for i in range(1, len(df)):
            bar = df.iloc[i]
            prev_bar = df.iloc[i - 1]

            open_price = bar["Open"]
            close_price = bar["Close"]
            high_price = bar["High"]
            low_price = bar["Low"]
            timestamp = str(df.index[i])

            # Midpoint price (simulates what price looks like mid-window)
            mid_price = (open_price + close_price) / 2

            # Update price history
            price_histories[asset].append(close_price)

            # Compute momentum from history
            mom_dir, mom_strength = compute_momentum(
                price_histories[asset], close_price
            )

            # Actual outcome: did price go Up or Down?
            outcome_up = close_price >= open_price

            # Simulate market pricing
            up_price, down_price = simulate_market_price(
                prev_bar["Close"], close_price, mid_price
            )

            total_windows += 1

            # Only consider windows where market has a lean (>= 0.60)
            if max(up_price, down_price) < 0.60:
                continue

            windows_with_signal += 1

            # Run both strategies
            run_strategy_old(
                old_state, asset, timestamp, up_price, down_price,
                outcome_up, mom_dir, mom_strength, bet_size,
            )
            run_strategy_new(
                new_state, asset, timestamp, up_price, down_price,
                outcome_up, mom_dir, mom_strength, bet_size,
            )

    # ── Results ──────────────────────────────────────────────────
    print(f"\n{'='*70}")
    print(f"  BACKTEST RESULTS")
    print(f"{'='*70}")
    print(f"\n  Total 5-min windows: {total_windows:,}")
    print(f"  Windows with market lean: {windows_with_signal:,}")
    print()

    for state in [old_state, new_state]:
        total = state.wins + state.losses
        wr = state.wins / total * 100 if total > 0 else 0
        avg_win = np.mean([t.pnl for t in state.trades if t.outcome == "win"]) if state.wins else 0
        avg_loss = np.mean([t.pnl for t in state.trades if t.outcome == "loss"]) if state.losses else 0
        payoff = abs(avg_win / avg_loss) if avg_loss != 0 else 0
        ev = state.total_pnl / total if total > 0 else 0

        # Drawdown
        running = 0.0
        peak = 0.0
        max_dd = 0.0
        for t in state.trades:
            running += t.pnl
            if running > peak:
                peak = running
            dd = peak - running
            if dd > max_dd:
                max_dd = dd

        # Win streak stats
        streaks = []
        current_streak = 0
        for t in state.trades:
            if t.outcome == "win":
                current_streak += 1
            else:
                if current_streak > 0:
                    streaks.append(current_streak)
                current_streak = 0
        if current_streak > 0:
            streaks.append(current_streak)

        # Loss streak stats
        loss_streaks = []
        current_streak = 0
        for t in state.trades:
            if t.outcome == "loss":
                current_streak += 1
            else:
                if current_streak > 0:
                    loss_streaks.append(current_streak)
                current_streak = 0
        if current_streak > 0:
            loss_streaks.append(current_streak)

        # Signal type breakdown
        by_type = {}
        for t in state.trades:
            if t.signal_type not in by_type:
                by_type[t.signal_type] = {"w": 0, "l": 0, "pnl": 0.0}
            if t.outcome == "win":
                by_type[t.signal_type]["w"] += 1
            else:
                by_type[t.signal_type]["l"] += 1
            by_type[t.signal_type]["pnl"] += t.pnl

        # Per-asset breakdown
        by_asset = {}
        for t in state.trades:
            if t.asset not in by_asset:
                by_asset[t.asset] = {"w": 0, "l": 0, "pnl": 0.0}
            if t.outcome == "win":
                by_asset[t.asset]["w"] += 1
            else:
                by_asset[t.asset]["l"] += 1
            by_asset[t.asset]["pnl"] += t.pnl

        pnl_color = "\033[32m" if state.total_pnl >= 0 else "\033[31m"
        reset = "\033[0m"

        print(f"  ┌─ {state.name}")
        print(f"  │  Trades: {total} ({state.wins}W / {state.losses}L)")
        print(f"  │  Win Rate: {wr:.1f}%")
        print(f"  │  PnL: {pnl_color}${state.total_pnl:+.2f}{reset}")
        print(f"  │  EV/trade: {pnl_color}${ev:+.4f}{reset}")
        print(f"  │  Avg Win: ${avg_win:+.2f} | Avg Loss: ${avg_loss:.2f}")
        print(f"  │  Payoff Ratio: {payoff:.2f}x")
        print(f"  │  Max Drawdown: ${max_dd:.2f}")
        print(f"  │  Best Win Streak: {max(streaks) if streaks else 0}")
        print(f"  │  Worst Loss Streak: {max(loss_streaks) if loss_streaks else 0}")
        print(f"  │  Skipped: cooldown={state.skipped_cooldown}, "
              f"momentum={state.skipped_momentum}, price={state.skipped_price}")
        print(f"  │")
        print(f"  │  By Signal Type:")
        for st, d in sorted(by_type.items(), key=lambda x: x[1]["pnl"], reverse=True):
            t = d["w"] + d["l"]
            w = d["w"] / t * 100 if t > 0 else 0
            print(f"  │    {st:15s} {d['w']:3d}W/{d['l']:3d}L  {w:5.1f}%  ${d['pnl']:+.2f}")
        print(f"  │")
        print(f"  │  By Asset:")
        for a in sorted(by_asset.keys()):
            d = by_asset[a]
            t = d["w"] + d["l"]
            w = d["w"] / t * 100 if t > 0 else 0
            pc = "\033[32m" if d["pnl"] >= 0 else "\033[31m"
            print(f"  │    {a.upper():4s}  {d['w']:3d}W/{d['l']:3d}L  {w:5.1f}%  {pc}${d['pnl']:+.2f}{reset}")
        print(f"  └{'─'*60}\n")

    # Comparison
    diff = new_state.total_pnl - old_state.total_pnl
    dc = "\033[32m" if diff >= 0 else "\033[31m"
    reset = "\033[0m"
    print(f"  IMPROVEMENT: {dc}${diff:+.2f}{reset} "
          f"({new_state.name.split('(')[0].strip()} vs {old_state.name.split('(')[0].strip()})")

    old_wr = old_state.wins / (old_state.wins + old_state.losses) * 100 if (old_state.wins + old_state.losses) else 0
    new_wr = new_state.wins / (new_state.wins + new_state.losses) * 100 if (new_state.wins + new_state.losses) else 0
    print(f"  Win Rate: {old_wr:.1f}% → {new_wr:.1f}% ({new_wr - old_wr:+.1f}pp)")
    print(f"  Trades: {len(old_state.trades)} → {len(new_state.trades)} "
          f"({len(new_state.trades) - len(old_state.trades):+d})")
    print()

    if verbose and new_state.trades:
        print(f"\n  Last 20 NEW strategy trades:")
        print(f"  {'Time':20s} {'Asset':5s} {'Dir':5s} {'Type':13s} "
              f"{'Entry':>6s} {'Result':>6s} {'PnL':>8s} {'Streak':>6s}")
        print(f"  {'─'*20} {'─'*5} {'─'*5} {'─'*13} {'─'*6} {'─'*6} {'─'*8} {'─'*6}")
        for t in new_state.trades[-20:]:
            rc = "\033[32m" if t.outcome == "win" else "\033[31m"
            print(f"  {t.timestamp[:19]:20s} {t.asset.upper():5s} {t.direction:5s} "
                  f"{t.signal_type:13s} {t.entry_price:6.3f} "
                  f"{rc}{t.outcome:>6s}\033[0m {rc}${t.pnl:+7.2f}\033[0m "
                  f"{t.streak_mult:5.2f}x")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Turbo Strategy Backtester")
    parser.add_argument("--days", type=int, default=30, help="Days of history (max ~59)")
    parser.add_argument("--bet", type=float, default=1.0, help="Base bet size in USDC")
    parser.add_argument("--verbose", action="store_true", help="Show individual trades")
    args = parser.parse_args()

    run_backtest(args.days, args.bet, args.verbose)
