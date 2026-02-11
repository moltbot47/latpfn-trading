"""
Price-based position exit monitor (estimation tool).

Checks open positions against the latest available price data each cycle
and infers whether a bracket order's stop loss or take profit has been hit.

!! IMPORTANT ACCURACY DISCLAIMERS !!
-------------------------------------
This monitor is an ESTIMATION TOOL, not a source of truth. Results are
labeled "inferred" in the trade log for the following reasons:

1. FILL PRICES DIFFER: PickMyTrade sends bracket orders as market orders
   on trigger. Actual fills may differ from our SL/TP levels due to
   slippage, partial fills, or market gaps. Especially during fast moves,
   the actual fill can be several ticks (or points) away from the order
   level.

2. ENTRY PRICES DIFFER: Our signal's entry_price is the price at signal
   generation time. The actual market order fill when PickMyTrade executes
   may be higher or lower. So the real entry != our logged entry.

3. DATA IS DELAYED: yfinance futures data (YM=F, NQ=F, etc.) is delayed
   ~10-15 minutes for CME products. A position may have already been
   closed by the time we detect it.

4. GAP RISK: During the daily 5-6 PM ET close or on Sunday open, price
   can gap through SL/TP. The actual fill would be at the gap price,
   not our order level, but we record it at SL/TP.

5. REJECTED TRADES: Only positions that were actually sent to PickMyTrade
   (execution_status='executed') are monitored. Rejected and dry_run
   trades are never tracked here since no broker order exists.

6. DUAL-BAR AMBIGUITY: If both SL and TP could have been hit within the
   same price bar, we conservatively assume the STOP LOSS was hit first
   (pessimistic P&L). The actual result may have been a win.

For accurate P&L reconciliation, always cross-reference with:
- PickMyTrade dashboard (Alert & Orders sections)
- Tradovate account statement
- Apex Trader Funding performance dashboard

All exits from this monitor are tagged exit_reason='inferred_sl' or
'inferred_tp' in the trade log so they can be identified and corrected.
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import yfinance as yf

logger = logging.getLogger(__name__)


def check_position_exits(
    open_positions: Dict,
    instruments_config: dict,
) -> List[dict]:
    """
    Check open positions against latest prices and infer exits.

    Only call this for positions that have actually been sent to the broker
    (execution_status='executed'). Do NOT call for dry_run or rejected trades.

    Args:
        open_positions:     Dict of instrument -> Position objects from OrderManager.
        instruments_config: The config['instruments'] dict with yfinance_ticker, etc.

    Returns:
        List of exit dicts, each containing:
            instrument:  str
            exit_price:  float  (SL or TP level — NOT actual fill price)
            exit_reason: str    ('inferred_sl' or 'inferred_tp')
            pnl_points:  float  (estimated, based on our entry — NOT actual)
            pnl_dollars: float  (estimated, based on our entry — NOT actual)
            note:        str    (accuracy disclaimer)
    """
    if not open_positions:
        return []

    exits: List[dict] = []

    for instrument, pos in list(open_positions.items()):
        inst_cfg = instruments_config.get(instrument)
        if inst_cfg is None:
            continue

        ticker = inst_cfg.get("yfinance_ticker")
        if not ticker:
            continue

        try:
            result = _check_single_position(pos, ticker, inst_cfg)
            if result is not None:
                exits.append(result)
        except Exception as e:
            logger.debug("Exit check failed for %s: %s", instrument, e)

    return exits


def _check_single_position(
    pos,
    ticker: str,
    inst_cfg: dict,
) -> Optional[dict]:
    """
    Check one position against yfinance price data.

    Uses the most recent 1-minute bar's high/low to determine if
    SL or TP was breached. Falls back to last close if intraday
    data is unavailable.
    """
    # Fetch recent 1-minute bars (last 1 day covers current session)
    try:
        tf = yf.Ticker(ticker)
        hist = tf.history(period="1d", interval="1m")
    except Exception as e:
        logger.debug("yfinance fetch failed for %s: %s", ticker, e)
        return None

    if hist is None or hist.empty:
        return None

    # Use the latest bar's high and low for breach detection
    latest = hist.iloc[-1]
    bar_high = float(latest["High"])
    bar_low = float(latest["Low"])
    bar_close = float(latest["Close"])

    contract_size = inst_cfg.get("contract_size", 1.0)
    sl = pos.stop_loss
    tp = pos.take_profit

    sl_hit = False
    tp_hit = False

    if pos.direction == "long":
        sl_hit = bar_low <= sl
        tp_hit = bar_high >= tp
    else:  # short
        sl_hit = bar_high >= sl
        tp_hit = bar_low <= tp

    if not sl_hit and not tp_hit:
        # Update current price on the position for unrealized P&L tracking
        pos.current_price = bar_close
        return None

    # If both could have triggered, conservatively assume SL hit first
    if sl_hit and tp_hit:
        logger.warning(
            "%s: both SL and TP could have been hit in same bar "
            "(high=%.2f low=%.2f SL=%.2f TP=%.2f) — assuming SL (conservative)",
            pos.instrument, bar_high, bar_low, sl, tp,
        )
        exit_price = sl
        exit_reason = "inferred_sl"
    elif sl_hit:
        exit_price = sl
        exit_reason = "inferred_sl"
    else:
        exit_price = tp
        exit_reason = "inferred_tp"

    # Estimated P&L (based on OUR entry price, not actual fill)
    pnl_points = exit_price - pos.entry_price
    if pos.direction == "short":
        pnl_points = -pnl_points
    pnl_dollars = pnl_points * contract_size * pos.size

    logger.info(
        "INFERRED EXIT %s: %s @ %.2f → %.2f (%s)  est_pnl=%.2f pts ($%.2f)  "
        "[NOTE: estimated — actual fill may differ]",
        pos.instrument, pos.direction, pos.entry_price, exit_price,
        exit_reason, pnl_points, pnl_dollars,
    )

    return {
        "instrument": pos.instrument,
        "exit_price": exit_price,
        "exit_reason": exit_reason,
        "pnl_points": pnl_points,
        "pnl_dollars": pnl_dollars,
        "contract_size": contract_size,
        "note": (
            "ESTIMATED — actual broker fill price may differ due to slippage, "
            "gaps, or execution timing. Cross-reference with PickMyTrade "
            "dashboard and Tradovate statement for accurate P&L."
        ),
    }
