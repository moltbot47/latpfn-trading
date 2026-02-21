"""
Auto profit-taking manager for open positions.

Monitors unrealized P&L on open positions and recommends actions to
capture profits and free up position slots for new signals.

!! DATA ACCURACY DISCLAIMER !!
-------------------------------
This module uses yfinance for price data. CME futures data (YM=F, NQ=F,
ES=F, etc.) is delayed ~10-15 minutes. Actions recommended here are based
on DELAYED prices — the actual market price may be significantly different,
especially during fast-moving sessions.

Always cross-reference with live broker data (PickMyTrade dashboard,
Tradovate) before acting on recommendations from this module.

Profit-taking thresholds:
  - 75%+ of take-profit target AND open > 15 min: tighten stop to breakeven
  - 90%+ of take-profit target: close position to capture profit
  - Profitable position with higher-conviction replacement: close to free slot
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import yfinance as yf

logger = logging.getLogger(__name__)

# ── Default thresholds (can be overridden via profit_config) ─────────
DEFAULT_PROFIT_CONFIG = {
    "tighten_stop_pct": 0.75,      # 75% of TP target reached
    "close_pct": 0.90,             # 90% of TP target reached
    "min_hold_minutes": 15,        # Minimum hold time before tightening
    "slot_free_min_profit_pct": 0.25,  # Must be 25%+ toward TP to close for slot
    "trailing_stop_activation_pct": 0.50,  # Activate trail at 50% of TP
    "trailing_stop_distance_pct": 0.40,    # Trail distance = 40% of total TP target
    "scale_out_pct": 0.50,         # Partial close at 50% of TP
    "scale_out_fraction": 0.50,    # Close 50% of position
}

# Scalp mode: tighter thresholds for fast near-term profit capture
SCALP_PROFIT_CONFIG = {
    "tighten_stop_pct": 0.60,      # BE at 60% of TP (vs 75%)
    "close_pct": 0.85,             # auto-close at 85% of TP (vs 90%)
    "min_hold_minutes": 3,         # faster tightening (vs 15 min)
    "slot_free_min_profit_pct": 0.15,  # close for slot at 15% (vs 25%)
    "trailing_stop_activation_pct": 0.30,  # activate trail at 30% (vs 50%)
    "trailing_stop_distance_pct": 0.20,    # trail 20% of TP distance (vs 40%)
    "scale_out_pct": 0.40,         # partial close at 40% (vs 50%)
    "scale_out_fraction": 0.50,    # close 50% of position
}


def check_profit_actions(
    open_positions: Dict[str, Any],
    instruments_config: dict,
    profit_config: Optional[dict] = None,
    pending_signals: Optional[List[dict]] = None,
    strategy_mode: str = "standard",
    scalp_config: Optional[dict] = None,
) -> List[dict]:
    """
    Evaluate open positions and recommend profit-taking actions.

    For each open position, fetches the latest 1-minute bar from yfinance,
    calculates how far the position has moved toward its take-profit target,
    and returns recommended actions.

    NOTE: yfinance CME futures data is delayed ~10-15 minutes. Recommendations
    are based on DELAYED data and should be treated as guidance, not as
    real-time triggers. Always verify with live broker data.

    Args:
        open_positions:     Dict of instrument -> Position objects (from
                            OrderManager.open_positions). Each Position has
                            instrument, direction, size, entry_price, stop_loss,
                            take_profit, entry_time, current_price.
        instruments_config: The config['instruments'] dict with yfinance_ticker,
                            contract_size, etc.
        profit_config:      Optional overrides for thresholds. Keys:
                            - tighten_stop_pct (default 0.75)
                            - close_pct (default 0.90)
                            - min_hold_minutes (default 15)
                            - slot_free_min_profit_pct (default 0.25)
        pending_signals:    Optional list of new signal dicts that need a slot.
                            Each should have at least 'instrument' and
                            'composite_score'. Used for slot-freeing logic.
        strategy_mode:      'standard' or 'scalp'. Selects default thresholds.

    Returns:
        List of action dicts. Each dict contains:
            instrument:         str — the position instrument (e.g. "MNQ")
            action:             str — "tighten_stop" or "close"
            current_price:      float — latest price from yfinance (delayed)
            unrealized_pnl_pct: float — % of take-profit target reached (0.0-1.0+)
            pnl_dollars:        float — estimated unrealized P&L in dollars
            reason:             str — human-readable explanation

        Returns an empty list if no actions are recommended or if all
        checks fail gracefully.
    """
    if not open_positions:
        return []

    if strategy_mode == "scalp":
        # Use scalp config from settings.yaml if provided, else fall back to defaults
        base = {**SCALP_PROFIT_CONFIG, **(scalp_config or {})}
    else:
        base = DEFAULT_PROFIT_CONFIG
    cfg = {**base, **(profit_config or {})}
    actions: List[dict] = []

    for instrument, pos in list(open_positions.items()):
        try:
            action = _evaluate_position(
                pos, instruments_config, cfg, pending_signals,
            )
            if action is not None:
                actions.append(action)
        except Exception as e:
            # Never crash the trading loop — log and continue
            logger.debug(
                "Profit check failed for %s: %s", instrument, e,
            )

    return actions


def _evaluate_position(
    pos,
    instruments_config: dict,
    cfg: dict,
    pending_signals: Optional[List[dict]],
) -> Optional[dict]:
    """
    Evaluate a single position for profit-taking actions.

    Returns an action dict if action is recommended, None otherwise.
    Wrapped by caller in try/except so exceptions here are safe.
    """
    inst_cfg = instruments_config.get(pos.instrument)
    if inst_cfg is None:
        return None

    ticker = inst_cfg.get("yfinance_ticker")
    if not ticker:
        return None

    # ── Fetch latest price from yfinance ─────────────────────────
    current_price = _fetch_latest_price(ticker)
    if current_price is None:
        return None

    # Update the position's current_price for other consumers
    pos.current_price = current_price

    contract_size = inst_cfg.get("contract_size", 1.0)

    # ── Calculate profit progress toward take-profit target ──────
    tp_target_points = pos.take_profit - pos.entry_price
    if pos.direction == "short":
        tp_target_points = pos.entry_price - pos.take_profit

    # Avoid division by zero (degenerate bracket)
    if abs(tp_target_points) < 1e-10:
        return None

    current_move_points = current_price - pos.entry_price
    if pos.direction == "short":
        current_move_points = pos.entry_price - current_price

    # How far toward the take-profit target (can be negative if losing)
    pnl_pct_of_target = current_move_points / tp_target_points
    pnl_dollars = current_move_points * contract_size * pos.size

    # Time in position
    try:
        hold_minutes = (datetime.now() - pos.entry_time).total_seconds() / 60.0
    except Exception:
        hold_minutes = 0.0

    # ── Max hold time exit (scalp mode) ────────────────────────────
    # Only force-close if profitable or breakeven. If losing, let stop
    # loss handle it — cutting losers early via max_hold just converts
    # potential winners into realized losses.
    max_hold = getattr(pos, "max_hold_minutes", 0)
    if max_hold > 0 and hold_minutes >= max_hold and pnl_pct_of_target > 0:
        return _build_action(
            pos, "close", current_price, pnl_pct_of_target, pnl_dollars,
            reason=(
                f"Max hold time ({max_hold} min) exceeded after {hold_minutes:.0f} min. "
                f"Position at {pnl_pct_of_target:.0%} of target. "
                f"Closing to capture ${pnl_dollars:+.2f} and free slot."
            ),
        )

    # ── Trailing stop logic ───────────────────────────────────────
    trail_activation = cfg.get("trailing_stop_activation_pct", 0.50)
    trail_distance_pct = cfg.get("trailing_stop_distance_pct", 0.40)
    trail_distance = abs(tp_target_points) * trail_distance_pct

    if pnl_pct_of_target >= trail_activation and not pos.trailing_stop_active:
        # Activate trailing stop
        pos.trailing_stop_active = True
        pos.best_price = current_price
        if pos.direction == "long":
            pos.trailing_stop_level = current_price - trail_distance
        else:
            pos.trailing_stop_level = current_price + trail_distance
        logger.info(
            "TRAILING STOP ACTIVATED: %s at %.2f (trail=%.2f pts, level=%.2f)",
            pos.instrument, current_price, trail_distance, pos.trailing_stop_level,
        )

    if pos.trailing_stop_active:
        # Update best price and ratchet the trailing stop
        if pos.direction == "long":
            if current_price > pos.best_price:
                pos.best_price = current_price
                pos.trailing_stop_level = current_price - trail_distance
            # Check if trailing stop hit
            if current_price <= pos.trailing_stop_level:
                return _build_action(
                    pos, "trailing_stop_close", current_price, pnl_pct_of_target, pnl_dollars,
                    reason=(
                        f"Trailing stop hit: price {current_price:.2f} fell below "
                        f"trail level {pos.trailing_stop_level:.2f} "
                        f"(best: {pos.best_price:.2f}, trail: {trail_distance:.2f} pts). "
                        f"Locking in ${pnl_dollars:+.2f} est. profit."
                    ),
                )
        else:  # short
            if current_price < pos.best_price:
                pos.best_price = current_price
                pos.trailing_stop_level = current_price + trail_distance
            # Check if trailing stop hit
            if current_price >= pos.trailing_stop_level:
                return _build_action(
                    pos, "trailing_stop_close", current_price, pnl_pct_of_target, pnl_dollars,
                    reason=(
                        f"Trailing stop hit: price {current_price:.2f} rose above "
                        f"trail level {pos.trailing_stop_level:.2f} "
                        f"(best: {pos.best_price:.2f}, trail: {trail_distance:.2f} pts). "
                        f"Locking in ${pnl_dollars:+.2f} est. profit."
                    ),
                )

    # ── Partial close (scale-out) at 50% of TP ──────────────────
    # Close half the position at 50% of TP, move SL to breakeven.
    # Only triggers once (scale_out_done flag prevents repeats).
    scale_out_pct = cfg.get("scale_out_pct", 0.50)  # trigger at 50% of TP
    scale_out_fraction = cfg.get("scale_out_fraction", 0.50)  # close 50%
    if (
        pnl_pct_of_target >= scale_out_pct
        and not getattr(pos, "scale_out_done", False)
        and hold_minutes >= cfg.get("min_hold_minutes", 15)
    ):
        return _build_action(
            pos, "partial_close", current_price, pnl_pct_of_target, pnl_dollars,
            reason=(
                f"Scale-out: position at {pnl_pct_of_target:.0%} of TP target "
                f"(threshold: {scale_out_pct:.0%}). "
                f"Closing {scale_out_fraction:.0%} to lock in ${pnl_dollars * scale_out_fraction:+.2f} est. "
                f"Moving SL to breakeven on remaining."
            ),
        )

    # ── Decision logic (highest priority first) ──────────────────

    # 1. Close at 90%+ of TP target — capture the profit
    if pnl_pct_of_target >= cfg["close_pct"]:
        return _build_action(
            pos, "close", current_price, pnl_pct_of_target, pnl_dollars,
            reason=(
                f"Position reached {pnl_pct_of_target:.0%} of take-profit target "
                f"(threshold: {cfg['close_pct']:.0%}). Recommending close to "
                f"capture ${pnl_dollars:+.2f} estimated profit and free the slot."
            ),
        )

    # 2. Tighten stop at 75%+ if held > 15 min — protect profits
    if (
        pnl_pct_of_target >= cfg["tighten_stop_pct"]
        and hold_minutes >= cfg["min_hold_minutes"]
    ):
        return _build_action(
            pos, "tighten_stop", current_price, pnl_pct_of_target, pnl_dollars,
            reason=(
                f"Position reached {pnl_pct_of_target:.0%} of take-profit target "
                f"after {hold_minutes:.0f} min (threshold: {cfg['tighten_stop_pct']:.0%} "
                f"after {cfg['min_hold_minutes']} min). Recommending move stop to "
                f"breakeven ({pos.entry_price:.2f}) to protect ${pnl_dollars:+.2f} "
                f"estimated unrealized profit."
            ),
        )

    # 3. Slot-freeing: profitable position + higher-conviction signal waiting
    if (
        pending_signals
        and pnl_pct_of_target >= cfg["slot_free_min_profit_pct"]
        and pnl_pct_of_target > 0
    ):
        replacement = _find_higher_conviction_signal(
            pos.instrument, pending_signals,
        )
        if replacement is not None:
            return _build_action(
                pos, "close", current_price, pnl_pct_of_target, pnl_dollars,
                reason=(
                    f"Position is {pnl_pct_of_target:.0%} toward take-profit "
                    f"(${pnl_dollars:+.2f} est.). A higher-conviction signal "
                    f"exists for {replacement['instrument']} "
                    f"(score={replacement.get('composite_score', 'N/A')}). "
                    f"Recommending close to free slot for the new signal."
                ),
            )

    return None


def _fetch_latest_price(ticker: str) -> Optional[float]:
    """
    Fetch the latest closing price from yfinance 1-minute bars.

    Uses the same pattern as position_monitor.py: Ticker.history()
    with period="1d" and interval="1m", taking the last bar's Close.

    Returns None if data is unavailable. Never raises.
    """
    try:
        tf = yf.Ticker(ticker)
        hist = tf.history(period="1d", interval="1m")
    except Exception as e:
        logger.debug("yfinance fetch failed for %s: %s", ticker, e)
        return None

    if hist is None or hist.empty:
        logger.debug("No yfinance data for %s", ticker)
        return None

    try:
        return float(hist.iloc[-1]["Close"])
    except (IndexError, KeyError) as e:
        logger.debug("Failed to read Close from %s data: %s", ticker, e)
        return None


def _find_higher_conviction_signal(
    current_instrument: str,
    pending_signals: List[dict],
) -> Optional[dict]:
    """
    Check if any pending signal is for a DIFFERENT instrument and has
    a composite_score higher than a baseline threshold.

    Returns the highest-scoring pending signal for a different instrument,
    or None if no suitable replacement exists.
    """
    try:
        candidates = [
            s for s in pending_signals
            if s.get("instrument") != current_instrument
            and s.get("composite_score", 0) > 0
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda s: s.get("composite_score", 0))
    except Exception as e:
        logger.debug("Signal comparison failed: %s", e)
        return None


def _build_action(
    pos,
    action: str,
    current_price: float,
    unrealized_pnl_pct: float,
    pnl_dollars: float,
    reason: str,
) -> dict:
    """Build a standardized action dict."""
    return {
        "instrument": pos.instrument,
        "action": action,
        "current_price": current_price,
        "unrealized_pnl_pct": unrealized_pnl_pct,
        "pnl_dollars": pnl_dollars,
        "reason": reason,
    }
