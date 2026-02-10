"""
Position sizing based on account equity and stop distance.
"""

import logging

logger = logging.getLogger(__name__)


def calculate_position_size(
    account_equity: float,
    entry_price: float,
    stop_loss: float,
    contract_size: float,
    max_risk_pct: float,
    max_contracts: int,
) -> int:
    """
    Determine how many contracts to trade.

    risk_dollars = account_equity x max_risk_pct
    risk_per_contract = |entry - stop| x contract_size
    contracts = floor(risk_dollars / risk_per_contract)

    Args:
        account_equity: Current account value (must be > 0).
        entry_price:    Expected entry price.
        stop_loss:      Stop loss price.
        contract_size:  Dollar value per point (e.g. $5 for YM).
        max_risk_pct:   Max risk as fraction (e.g. 0.015 for 1.5%).
        max_contracts:  Hard cap on contracts.

    Returns:
        Number of contracts (>= 1 if trade is viable, 0 if too risky).
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

    contracts = int(max_risk_dollars / dollar_risk_per_contract)
    contracts = min(contracts, max_contracts)

    if contracts < 1:
        logger.warning(
            "Risk per contract ($%.2f) exceeds max risk ($%.2f) — cannot size position",
            dollar_risk_per_contract, max_risk_dollars,
        )
        return 0

    return contracts
