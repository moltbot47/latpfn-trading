"""
Shared simulation utilities for backtesting and optimization scripts.
"""

import numpy as np

from signals.generator import TradingSignal


def simulate_trade(
    signal: TradingSignal,
    future_prices: np.ndarray,
    contract_size: float,
    max_hold_bars: int = 0,
) -> dict | None:
    """
    Simulate a single trade through future price bars.

    Checks stop loss and take profit at each bar using Close prices.
    If neither is hit, exits at the last available price (timeout).
    In scalp mode, auto-closes after max_hold_bars.

    Args:
        signal: The trading signal with entry/SL/TP.
        future_prices: Array of Close prices after entry.
        contract_size: Dollar value per point.
        max_hold_bars: Max bars to hold before auto-close. 0 = no limit.

    Returns:
        Dict with keys: exit_price, pnl, reason, shot_type. None if no future data.
    """
    if len(future_prices) == 0:
        return None

    entry = signal.entry_price
    sl = signal.stop_loss
    tp = signal.take_profit
    is_long = signal.direction == "long"

    for i, price in enumerate(future_prices):
        # Max hold time exit (scalp mode) — only close if profitable
        if max_hold_bars > 0 and i >= max_hold_bars:
            pnl = (price - entry) * contract_size if is_long else (entry - price) * contract_size
            if pnl > 0:
                return {"exit_price": float(price), "pnl": pnl, "reason": "max_hold"}

        # Check stop loss
        if is_long and price <= sl:
            pnl = (sl - entry) * contract_size
            return {"exit_price": sl, "pnl": pnl, "reason": "stop_loss"}
        if not is_long and price >= sl:
            pnl = (entry - sl) * contract_size
            return {"exit_price": sl, "pnl": pnl, "reason": "stop_loss"}

        # Check take profit
        if is_long and price >= tp:
            pnl = (tp - entry) * contract_size
            return {"exit_price": tp, "pnl": pnl, "reason": "take_profit"}
        if not is_long and price <= tp:
            pnl = (entry - tp) * contract_size
            return {"exit_price": tp, "pnl": pnl, "reason": "take_profit"}

    # Exit at last price if neither SL nor TP hit
    last = float(future_prices[-1])
    pnl = (last - entry) * contract_size if is_long else (entry - last) * contract_size
    return {"exit_price": last, "pnl": pnl, "reason": "timeout"}
