"""
Sniper Mode — on-demand scan and aggressive entry for manual trade management.

When the user triggers /sniper, this module:
  1. Scans top N edge-ranked pairs via the model
  2. Generates candidates with widened stops (user controls the exit)
  3. Ranks by |confidence| × edge_score
  4. Returns the top picks ready for execution

Sniper mode intentionally bypasses:
  - EMA trend filter (user is making the directional call)
  - Shot-tier classification (not needed for manual exits)
  - Min confidence floor (lowered to 0.15 vs standard 0.25)
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import List, Optional

import numpy as np

from signals.confidence import score_confidence
from signals.exits import calculate_exits
from signals.regime import detect_regime

logger = logging.getLogger(__name__)

# Sniper mode configuration
SNIPER_MIN_CONFIDENCE = 0.15   # Lower bar — user controls risk
SNIPER_STOP_MULTIPLIER = 2.5   # 2.5x wider stops than standard
SNIPER_TP_PCT = 0.06           # 6% take-profit (wide, user exits before)
SNIPER_MIN_RR = 0.5            # Low min R:R (wide stops, tight TP)
SNIPER_MAX_POSITIONS = 2       # Max simultaneous sniper entries
SNIPER_RISK_PER_TRADE_PCT = 0.03  # 3% risk per trade (aggressive)
SNIPER_SCAN_TOP_N = 10         # Scan top 10 edge-ranked pairs


@dataclass
class SniperCandidate:
    """A sniper mode trade candidate."""
    instrument: str
    direction: str
    confidence: float
    entry_price: float
    stop_loss: float
    take_profit: float
    position_size: float       # coin size for Hyperliquid
    regime: str
    edge_score: float
    sniper_score: float        # combined ranking score
    funding_rate: float
    price_change_pct: float
    risk_usd: float
    reward_usd: float


async def scan_sniper_candidates(
    trading_system,
    top_n: int = SNIPER_SCAN_TOP_N,
) -> List[SniperCandidate]:
    """
    Scan top edge-ranked pairs and generate sniper candidates.

    Runs model inference on top_n pairs in parallel, then filters
    and ranks by sniper_score = |confidence| × edge_score.

    Args:
        trading_system: The TradingSystem instance (has model, pipeline, scanner).
        top_n: Number of pairs to scan.

    Returns:
        List of SniperCandidate sorted by sniper_score descending.
    """
    ts = trading_system

    if not ts._pair_scanner:
        logger.error("Sniper mode requires PairScanner (Hyperliquid mode only)")
        return []

    # Get top edge-ranked pairs
    ranked_pairs = ts._pair_scanner.scan(force=True)[:top_n]

    if not ranked_pairs:
        logger.warning("No pairs available for sniper scan")
        return []

    # Get current account equity
    equity = ts.account_equity
    if ts.executor:
        try:
            balance = await ts.executor.get_cash_balance()
            if balance > 0:
                equity = balance
        except Exception:
            pass

    # Scan each pair in parallel
    async def _scan_one(pair_data: dict) -> Optional[SniperCandidate]:
        coin = pair_data["coin"]
        try:
            # Skip if already holding a position
            if ts.order_mgr.has_position(coin):
                return None

            # Fetch candle data
            data = ts.data_pipeline.get_prediction_data(coin)
            if len(data["heldout_df"]) < data["n_history"] + data["n_prompt"]:
                return None

            # Run model prediction
            prediction = ts.model.predict(
                heldout_df=data["heldout_df"],
                context_dfs=data["context_dfs"],
            )

            # Attach microstructure data
            prediction["funding_rate"] = data.get("funding_rate", 0.0)
            prediction["open_interest"] = data.get("open_interest", 0.0)

            direction = prediction["direction"]
            if direction == "neutral":
                return None

            # Score confidence (with funding rate boost)
            confidence = score_confidence(
                model_confidence=prediction["confidence"],
                forecast=prediction["forecast_prices"],
                uncertainty=prediction["uncertainty"],
                current_price=prediction["current_price"],
                regime=prediction["regime"],
                signal_config=ts.config["signal"],
                funding_rate=prediction.get("funding_rate", 0.0),
                open_interest=prediction.get("open_interest", 0.0),
                direction=direction,
            )

            # Sniper floor check (lower than standard)
            if confidence < SNIPER_MIN_CONFIDENCE:
                return None

            # Calculate exits with widened stops
            entry_price = prediction["current_price"]
            stop_loss, take_profit = calculate_exits(
                entry_price=entry_price,
                direction=direction,
                forecast=prediction["forecast_prices"],
                uncertainty=prediction["uncertainty"],
                risk_config=ts.config["risk"],
                target_multiplier=1.0,
                stop_multiplier=SNIPER_STOP_MULTIPLIER,
                min_rr_override=SNIPER_MIN_RR,
            )

            # Override TP with percentage-based wide target
            if direction == "long":
                pct_tp = entry_price * (1 + SNIPER_TP_PCT)
                take_profit = max(take_profit, pct_tp)
            else:
                pct_tp = entry_price * (1 - SNIPER_TP_PCT)
                take_profit = min(take_profit, pct_tp)

            # Position sizing — aggressive but bounded
            stop_distance = abs(entry_price - stop_loss)
            if stop_distance <= 0:
                return None

            risk_budget = equity * SNIPER_RISK_PER_TRADE_PCT
            # For Hyperliquid: size in coin units
            # risk_budget / stop_distance gives us the coin amount
            position_size = risk_budget / stop_distance

            # Cap by leverage
            hl_cfg = ts.config.get("hyperliquid", {})
            max_leverage = hl_cfg.get("default_leverage", 5)
            max_notional = equity * max_leverage
            max_size_by_leverage = max_notional / entry_price
            position_size = min(position_size, max_size_by_leverage)

            # Round to exchange precision
            sz_decimals = pair_data.get("sz_decimals", 3)
            position_size = round(position_size, sz_decimals)

            if position_size <= 0:
                return None

            # Risk/reward in USD
            risk_usd = stop_distance * position_size
            reward_usd = abs(take_profit - entry_price) * position_size

            # Sniper score = |confidence| × edge_score
            edge_score = pair_data.get("edge_score", 0.5)
            sniper_score = confidence * edge_score

            return SniperCandidate(
                instrument=coin,
                direction=direction,
                confidence=confidence,
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                position_size=position_size,
                regime=prediction["regime"],
                edge_score=edge_score,
                sniper_score=sniper_score,
                funding_rate=prediction.get("funding_rate", 0.0),
                price_change_pct=pair_data.get("price_change_pct", 0.0),
                risk_usd=risk_usd,
                reward_usd=reward_usd,
            )

        except Exception as e:
            logger.warning("Sniper scan failed for %s: %s", coin, e)
            return None

    # Run all scans in parallel
    results = await asyncio.gather(*[_scan_one(p) for p in ranked_pairs])

    # Filter None and sort by sniper_score
    candidates = [c for c in results if c is not None]
    candidates.sort(key=lambda c: c.sniper_score, reverse=True)

    logger.info(
        "Sniper scan: %d/%d pairs produced candidates. Top: %s",
        len(candidates),
        len(ranked_pairs),
        ", ".join(f"{c.instrument}({c.sniper_score:.3f})" for c in candidates[:5]),
    )

    return candidates
