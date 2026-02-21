"""
Position sizing based on account equity and stop distance.

Includes drawdown-aware dynamic sizing that scales risk proportionally
to remaining drawdown cushion — critical for prop firm account survival.

Kelly criterion sizing uses historical win rate and R:R to compute
the mathematically optimal bet size. Uses quarter-Kelly for safety.
"""

import logging
from typing import Optional, Dict

logger = logging.getLogger(__name__)

# Minimum drawdown cushion below which we refuse to trade.
# With a $2,500 trailing drawdown, $750 is 30% — not enough room for even
# a single losing trade at minimum size.
DEFAULT_MIN_CUSHION_TO_TRADE: float = 750.0


def calculate_position_size(
    account_equity: float,
    entry_price: float,
    stop_loss: float,
    contract_size: float,
    max_risk_pct: float,
    max_contracts: int,
    fractional: bool = False,
) -> float:
    """
    Determine how many contracts/units to trade.

    risk_dollars = account_equity x max_risk_pct
    risk_per_contract = |entry - stop| x contract_size
    contracts = floor(risk_dollars / risk_per_contract)

    Args:
        account_equity: Current account value (must be > 0).
        entry_price:    Expected entry price.
        stop_loss:      Stop loss price.
        contract_size:  Dollar value per point (e.g. $5 for YM, 1.0 for crypto).
        max_risk_pct:   Max risk as fraction (e.g. 0.015 for 1.5%).
        max_contracts:  Hard cap on contracts.
        fractional:     If True, return fractional size (for crypto perps).

    Returns:
        Number of contracts/units (>= min_size if trade is viable, 0 if too risky).
    """
    if account_equity <= 0 or contract_size <= 0 or max_risk_pct <= 0:
        logger.warning("Invalid inputs: equity=%.2f contract_size=%.2f risk_pct=%.4f",
                        account_equity, contract_size, max_risk_pct)
        return 0

    price_risk = abs(entry_price - stop_loss)
    if price_risk < 1e-10:  # avoid float division by ~zero
        logger.warning("Stop loss too close to entry (distance=%.8f)", price_risk)
        return 0

    dollar_risk_per_contract = price_risk * contract_size
    max_risk_dollars = account_equity * max_risk_pct

    if fractional:
        # Crypto perps: fractional units (e.g. 0.002 BTC)
        size = max_risk_dollars / dollar_risk_per_contract
        size = min(size, float(max_contracts))
        if size < 1e-8:
            logger.warning(
                "Position size too small ($%.4f risk / $%.2f per unit)",
                max_risk_dollars, dollar_risk_per_contract,
            )
            return 0
        return size
    else:
        # Futures: integer contracts
        contracts = int(max_risk_dollars / dollar_risk_per_contract)
        contracts = min(contracts, max_contracts)
        if contracts < 1:
            logger.warning(
                "Risk per contract ($%.2f) exceeds max risk ($%.2f) — cannot size position",
                dollar_risk_per_contract, max_risk_dollars,
            )
            return 0
        return contracts


def calculate_drawdown_aware_size(
    account_equity: float,
    entry_price: float,
    stop_loss: float,
    contract_size: float,
    base_risk_pct: float,
    max_contracts: int,
    drawdown_cushion: float,
    max_drawdown: float,
    min_cushion_to_trade: float = DEFAULT_MIN_CUSHION_TO_TRADE,
    fractional: bool = False,
) -> tuple[float, float]:
    """
    Drawdown-aware dynamic position sizing.

    Scales the base risk percentage proportionally to how much drawdown
    cushion remains.  When the cushion is full (e.g. $2,500 on a $50k
    Apex account), trade at full ``base_risk_pct``.  When the cushion
    is half-gone ($1,250), trade at half risk.  Below
    ``min_cushion_to_trade`` ($750 default), return 0 contracts — stop
    trading entirely to protect the account.

    Formula:
        effective_risk_pct = base_risk_pct * (drawdown_cushion / max_drawdown)

    Args:
        account_equity:       Current account value.
        entry_price:          Expected entry price.
        stop_loss:            Stop loss price.
        contract_size:        Dollar value per point.
        base_risk_pct:        Base risk as fraction (e.g. 0.02 for 2%).
        max_contracts:        Hard cap on contracts.
        drawdown_cushion:     Dollars remaining before drawdown floor is hit.
        max_drawdown:         Maximum trailing drawdown amount (e.g. 2500).
        min_cushion_to_trade: Refuse to trade below this cushion (default $750).

    Returns:
        (contracts, effective_risk_pct) — contracts may be 0 if cushion is
        too thin or risk per contract exceeds the scaled risk budget.
    """
    # Guard: refuse to trade if cushion is critically low
    if drawdown_cushion <= min_cushion_to_trade:
        logger.warning(
            "DRAWDOWN GUARD: cushion $%.2f <= min $%.2f — refusing to trade",
            drawdown_cushion, min_cushion_to_trade,
        )
        return 0, 0.0

    if max_drawdown <= 0:
        logger.warning("Invalid max_drawdown=%.2f, falling back to base risk", max_drawdown)
        effective_risk_pct = base_risk_pct
    else:
        # Scale risk linearly with remaining cushion
        cushion_ratio = drawdown_cushion / max_drawdown
        # Clamp to [0, 1] — cushion can exceed max_drawdown if account is in profit
        cushion_ratio = min(max(cushion_ratio, 0.0), 1.0)
        effective_risk_pct = base_risk_pct * cushion_ratio

    logger.info(
        "Drawdown-aware sizing: cushion=$%.2f / max=$%.2f → "
        "effective_risk=%.4f (base=%.4f, ratio=%.2f%%)",
        drawdown_cushion, max_drawdown, effective_risk_pct,
        base_risk_pct, (effective_risk_pct / base_risk_pct * 100) if base_risk_pct > 0 else 0,
    )

    # Delegate to standard sizer with the scaled risk percentage
    contracts = calculate_position_size(
        account_equity=account_equity,
        entry_price=entry_price,
        stop_loss=stop_loss,
        contract_size=contract_size,
        max_risk_pct=effective_risk_pct,
        max_contracts=max_contracts,
        fractional=fractional,
    )

    return contracts, effective_risk_pct


def kelly_risk_pct(
    tier: str,
    tier_edge_stats: Dict[str, Dict],
    base_risk_pct: float = 0.02,
    min_trades: int = 20,
) -> float:
    """
    Compute Kelly-optimal risk percentage for a given tier.

    Uses quarter-Kelly (f* × 0.25) for safety on small accounts.
    Falls back to base_risk_pct if insufficient historical data.

    Args:
        tier: Shot tier name.
        tier_edge_stats: Output from TradeLogger.get_tier_edge_stats().
        base_risk_pct: Fallback risk percentage (default 2%).
        min_trades: Minimum trades required for Kelly to activate.

    Returns:
        Risk percentage as decimal (e.g. 0.015 for 1.5%).
    """
    if not tier_edge_stats or tier not in tier_edge_stats:
        return base_risk_pct

    stats = tier_edge_stats[tier]
    if stats["count"] < min_trades:
        logger.debug(
            "Kelly: %s has only %d trades (need %d), using base risk %.1f%%",
            tier, stats["count"], min_trades, base_risk_pct * 100,
        )
        return base_risk_pct

    kelly_q = stats.get("kelly_quarter", 0.0)
    if kelly_q <= 0:
        # Negative or zero Kelly = no edge, use minimum risk
        logger.info(
            "Kelly: %s has no edge (kelly=%.3f, WR=%.1f%%, avg_win=$%.2f, avg_loss=$%.2f). "
            "Using minimum risk.",
            tier, stats["kelly_fraction"], stats["win_rate"] * 100,
            stats["avg_win"], stats["avg_loss"],
        )
        return base_risk_pct * 0.5  # half the base as a safety minimum

    # Clamp Kelly between 0.5% and 5% (never go above 5% on small account)
    risk = max(0.005, min(kelly_q, 0.05))

    logger.info(
        "Kelly: %s → risk=%.2f%% (full_kelly=%.2f%%, quarter=%.2f%%, WR=%.0f%%, %d trades)",
        tier, risk * 100, stats["kelly_fraction"] * 100, kelly_q * 100,
        stats["win_rate"] * 100, stats["count"],
    )

    return risk
