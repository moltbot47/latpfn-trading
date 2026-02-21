"""
Correlation-adjusted portfolio exposure management.

Converts all positions into MES-equivalent notional to enforce
portfolio-level directional exposure limits. Prevents the scenario
where 3-4 correlated equity index futures all go the same direction
and a single market move wipes out the entire drawdown budget.

MES-equivalent: normalize each instrument's dollar-per-point so that
1 MES-equivalent = $5/point (the MES contract size).
"""

import logging

logger = logging.getLogger(__name__)

# Dollar-per-point for MES equivalence conversion
# MES = $5/pt, so MES_EQ = contract_size / 5.0
# 1 MNQ ($2/pt) = 0.4 MES-eq, 1 MYM ($0.50/pt) = 0.1 MES-eq, etc.
MES_DOLLAR_PER_POINT = 5.0


def mes_equivalent(contract_size: float, quantity: int = 1) -> float:
    """Convert a position to MES-equivalent exposure."""
    return (contract_size / MES_DOLLAR_PER_POINT) * quantity


def portfolio_exposure(
    open_positions: dict,
    instruments_config: dict,
) -> dict:
    """
    Calculate current portfolio exposure in MES-equivalents.

    Returns:
        {
            "net_mes_eq": float,       # net directional (long positive, short negative)
            "gross_mes_eq": float,     # total absolute exposure
            "long_mes_eq": float,      # total long exposure
            "short_mes_eq": float,     # total short exposure
            "by_instrument": dict,     # per-instrument MES-eq breakdown
        }
    """
    long_eq = 0.0
    short_eq = 0.0
    by_instrument = {}

    for inst, pos in open_positions.items():
        inst_cfg = instruments_config.get(inst, {})
        cs = inst_cfg.get("contract_size", MES_DOLLAR_PER_POINT)
        eq = mes_equivalent(cs, pos.size)

        by_instrument[inst] = {
            "mes_eq": eq,
            "direction": pos.direction,
            "signed_eq": eq if pos.direction == "long" else -eq,
        }

        if pos.direction == "long":
            long_eq += eq
        else:
            short_eq += eq

    return {
        "net_mes_eq": long_eq - short_eq,
        "gross_mes_eq": long_eq + short_eq,
        "long_mes_eq": long_eq,
        "short_mes_eq": short_eq,
        "by_instrument": by_instrument,
    }


def check_exposure_limit(
    open_positions: dict,
    instruments_config: dict,
    new_instrument: str,
    new_direction: str,
    new_quantity: int,
    max_net_mes_eq: float = 3.0,
    max_gross_mes_eq: float = 5.0,
) -> tuple[bool, str]:
    """
    Check if adding a new position would exceed portfolio exposure limits.

    Args:
        open_positions:    Current open positions dict.
        instruments_config: Config for all instruments.
        new_instrument:    Proposed new instrument.
        new_direction:     'long' or 'short'.
        new_quantity:      Number of contracts.
        max_net_mes_eq:    Max net directional exposure in MES-equivalents.
        max_gross_mes_eq:  Max gross (total) exposure in MES-equivalents.

    Returns:
        (allowed, reason_string)
    """
    current = portfolio_exposure(open_positions, instruments_config)

    new_cfg = instruments_config.get(new_instrument, {})
    new_cs = new_cfg.get("contract_size", MES_DOLLAR_PER_POINT)
    new_eq = mes_equivalent(new_cs, new_quantity)
    new_signed = new_eq if new_direction == "long" else -new_eq

    projected_net = current["net_mes_eq"] + new_signed
    projected_gross = current["gross_mes_eq"] + new_eq

    # Net directional limit
    if abs(projected_net) > max_net_mes_eq:
        return False, (
            f"Portfolio exposure limit: adding {new_quantity} {new_instrument} "
            f"{new_direction.upper()} would bring net exposure to "
            f"{projected_net:+.1f} MES-eq (limit: {max_net_mes_eq:.1f}). "
            f"Current: {current['net_mes_eq']:+.1f} MES-eq"
        )

    # Gross exposure limit
    if projected_gross > max_gross_mes_eq:
        return False, (
            f"Portfolio gross exposure limit: adding {new_quantity} {new_instrument} "
            f"would bring total exposure to {projected_gross:.1f} MES-eq "
            f"(limit: {max_gross_mes_eq:.1f}). "
            f"Current: {current['gross_mes_eq']:.1f} MES-eq"
        )

    return True, (
        f"Exposure OK: net={projected_net:+.1f} gross={projected_gross:.1f} MES-eq"
    )


# ── Crypto correlation clusters ─────────────────────────────────
# Coins within the same cluster are highly correlated (>0.85) and should
# be treated as a single position for risk purposes.
CRYPTO_CORRELATION_CLUSTERS = {
    "majors": {"BTC", "ETH"},
    "l1_alt": {"SOL", "AVAX", "SUI", "APT", "SEI", "TIA"},
    "l2": {"ARB", "OP", "STRK", "MANTA", "BLAST"},
    "meme": {"DOGE", "SHIB", "PEPE", "WIF", "BONK", "FLOKI"},
    "defi": {"AAVE", "UNI", "MKR", "CRV", "PENDLE", "JUP"},
    "ai": {"FET", "RNDR", "TAO", "NEAR", "AR"},
}

# Max same-direction positions per correlation cluster
MAX_PER_CLUSTER = 2


def _get_cluster(coin: str) -> str | None:
    """Find which correlation cluster a coin belongs to."""
    for cluster_name, coins in CRYPTO_CORRELATION_CLUSTERS.items():
        if coin in coins:
            return cluster_name
    return None


def check_correlation_limit(
    open_positions: dict,
    new_instrument: str,
    new_direction: str,
    max_per_cluster: int = MAX_PER_CLUSTER,
) -> tuple[bool, str]:
    """
    Check if adding a new crypto position would create excessive correlation risk.

    Coins in the same cluster (e.g. BTC and ETH in "majors") are highly correlated.
    If we already hold max_per_cluster same-direction positions in a cluster,
    block the new entry.

    Args:
        open_positions:   Dict of instrument → Position objects.
        new_instrument:   Proposed new coin (e.g. 'SOL').
        new_direction:    'long' or 'short'.
        max_per_cluster:  Max same-direction positions per cluster (default 2).

    Returns:
        (allowed, reason_string)
    """
    new_cluster = _get_cluster(new_instrument)
    if new_cluster is None:
        # Coin not in any cluster — no correlation limit
        return True, f"{new_instrument} not in any correlation cluster"

    # Count same-direction positions in the same cluster
    same_dir_count = 0
    same_dir_coins = []
    for inst, pos in open_positions.items():
        if _get_cluster(inst) == new_cluster and pos.direction == new_direction:
            same_dir_count += 1
            same_dir_coins.append(inst)

    if same_dir_count >= max_per_cluster:
        return False, (
            f"Correlation limit: {new_instrument} is in the '{new_cluster}' cluster "
            f"with {same_dir_coins}. Already {same_dir_count} {new_direction} "
            f"positions in this cluster (max {max_per_cluster}). "
            f"Adding another correlated {new_direction} increases concentration risk."
        )

    return True, (
        f"Correlation OK: {new_instrument} [{new_cluster}] — "
        f"{same_dir_count}/{max_per_cluster} same-direction in cluster"
    )


def select_best_signals(
    signals: dict,
    open_positions: dict,
    instruments_config: dict,
    max_net_mes_eq: float = 3.0,
    max_gross_mes_eq: float = 5.0,
) -> list[str]:
    """
    When multiple instruments signal the same direction, select the
    highest-confidence subset that fits within exposure limits.

    Args:
        signals: {instrument: (confidence, direction, quantity)} for pending signals
        open_positions: Current open positions
        instruments_config: Config for all instruments

    Returns:
        List of instrument names to trade (sorted by confidence, descending).
    """
    if not signals:
        return []

    # Sort by confidence descending
    ranked = sorted(signals.items(), key=lambda x: x[1][0], reverse=True)

    selected = []
    # Work with a copy of positions to simulate additions
    simulated_positions = dict(open_positions)

    for inst, (confidence, direction, quantity) in ranked:
        allowed, _ = check_exposure_limit(
            simulated_positions,
            instruments_config,
            inst,
            direction,
            quantity,
            max_net_mes_eq,
            max_gross_mes_eq,
        )
        if allowed:
            selected.append(inst)
            # Simulate adding this position for next check
            # Use a simple mock object for the simulation
            class _MockPos:
                def __init__(self, d, s):
                    self.direction = d
                    self.size = s
            simulated_positions[inst] = _MockPos(direction, quantity)

    return selected
