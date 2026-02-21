"""
Dynamic pair scanner for Hyperliquid.

Discovers top tradeable pairs using a multi-factor edge score that combines
volume, momentum, funding rate dislocation, and volatility. Refreshes hourly.

Single API call (meta_and_asset_ctxs) returns all data for every pair on
the exchange — no per-pair queries needed.
"""

import logging
import time
from typing import List, Dict, Optional

from hyperliquid.info import Info
from hyperliquid.utils import constants

logger = logging.getLogger(__name__)

# Minimum 24h volume to consider a pair (filter dust/dead pairs)
MIN_VOLUME_USD = 500_000

# Always include these pairs regardless of edge score (most liquid)
CORE_PAIRS = {"BTC", "ETH", "SOL"}


class PairScanner:
    """Discover and rank Hyperliquid perpetual futures by edge opportunity."""

    def __init__(self, network: str = "mainnet", top_n: int = 25):
        base_url = (
            constants.MAINNET_API_URL
            if network == "mainnet"
            else constants.TESTNET_API_URL
        )
        self._info = Info(base_url, skip_ws=True)
        self.top_n = top_n

        # Cache
        self._ranked_pairs: List[Dict] = []
        self._asset_contexts: Dict[str, Dict] = {}
        self._last_scan: float = 0
        self._scan_interval: float = 3600  # refresh ranking every hour

    def scan(self, force: bool = False) -> List[Dict]:
        """
        Fetch and rank all Hyperliquid perps by edge opportunity.

        Uses a multi-factor score:
          - Volume (40%): liquidity ensures clean entry/exit
          - Momentum (25%): recent price movement = directional opportunity
          - Funding dislocation (20%): extreme funding = mean-reversion edge
          - OI concentration (15%): high OI relative to volume = crowded trade

        Returns top_n pairs with metadata and edge scores.
        """
        now = time.time()
        if not force and self._ranked_pairs and (now - self._last_scan) < self._scan_interval:
            return self._ranked_pairs

        try:
            data = self._info.meta_and_asset_ctxs()
            universe = data[0]["universe"]
            contexts = data[1]

            pairs = []
            self._asset_contexts = {}

            for asset, ctx in zip(universe, contexts):
                coin = asset["name"]
                volume = float(ctx.get("dayNtlVlm", 0))
                mid_price = float(ctx.get("midPx", 0) or 0)
                oi = float(ctx.get("openInterest", 0))
                funding = float(ctx.get("funding", 0))
                prev_price = float(ctx.get("prevDayPx", 0) or 0)
                price_change = ((mid_price - prev_price) / prev_price * 100) if prev_price > 0 else 0

                if volume < MIN_VOLUME_USD or mid_price <= 0:
                    continue

                pair_data = {
                    "coin": coin,
                    "volume_24h": volume,
                    "open_interest": oi,
                    "funding_rate": funding,
                    "mid_price": mid_price,
                    "prev_day_price": prev_price,
                    "price_change_pct": price_change,
                    "sz_decimals": asset.get("szDecimals", 3),
                    "max_leverage": asset.get("maxLeverage", 50),
                }
                pairs.append(pair_data)
                self._asset_contexts[coin] = pair_data

            # Compute edge scores
            self._compute_edge_scores(pairs)

            # Sort by edge score descending
            pairs.sort(key=lambda x: x.get("edge_score", 0), reverse=True)

            # Ensure core pairs are always included
            selected = []
            selected_coins = set()
            # First pass: add core pairs
            for p in pairs:
                if p["coin"] in CORE_PAIRS:
                    selected.append(p)
                    selected_coins.add(p["coin"])
            # Second pass: fill remaining slots with highest edge score
            for p in pairs:
                if len(selected) >= self.top_n:
                    break
                if p["coin"] not in selected_coins:
                    selected.append(p)
                    selected_coins.add(p["coin"])

            # Re-sort final selection by edge score
            selected.sort(key=lambda x: x.get("edge_score", 0), reverse=True)

            self._ranked_pairs = selected
            self._last_scan = now

            logger.info(
                "Pair scan: %d pairs above $%dk volume, top %d selected. "
                "Top 5: %s",
                len(pairs),
                MIN_VOLUME_USD // 1000,
                len(self._ranked_pairs),
                ", ".join(
                    f"{p['coin']}(edge={p.get('edge_score', 0):.2f})"
                    for p in self._ranked_pairs[:5]
                ),
            )

            return self._ranked_pairs

        except Exception as e:
            logger.error("Pair scan failed: %s", e)
            return self._ranked_pairs  # return stale data on error

    def _compute_edge_scores(self, pairs: List[Dict]):
        """
        Compute multi-factor edge score for each pair.

        Components (all normalized 0-1, then weighted):
          - volume_score (40%): log-scaled 24h volume
          - momentum_score (25%): absolute price change % (capped at 20%)
          - funding_score (20%): absolute funding rate annualized (extreme = edge)
          - crowding_score (15%): OI/volume ratio inversion (high OI = crowded)
        """
        if not pairs:
            return

        # Collect raw values for normalization
        volumes = [p["volume_24h"] for p in pairs]
        max_vol = max(volumes) if volumes else 1

        for p in pairs:
            # 1. Volume score (log-scaled, normalized to max)
            import math
            vol_log = math.log10(p["volume_24h"] + 1)
            max_vol_log = math.log10(max_vol + 1) if max_vol > 0 else 1
            volume_score = vol_log / max_vol_log if max_vol_log > 0 else 0

            # 2. Momentum score — bigger price moves = more directional opportunity
            # Cap at 20% to avoid overweighting extreme outliers
            abs_change = min(abs(p["price_change_pct"]), 20.0)
            momentum_score = abs_change / 20.0

            # 3. Funding dislocation — extreme funding = mean-reversion or carry edge
            # Annualize: rate * 3 * 365 (funding every 8h)
            funding_annual = abs(p["funding_rate"]) * 3 * 365
            # Cap at 100% annualized
            funding_score = min(funding_annual, 1.0)

            # 4. Crowding score — high OI relative to volume = overcrowded, invert
            # OI/volume > 1 means positions are sticky (less edge)
            oi_vol_ratio = (p["open_interest"] / p["volume_24h"]) if p["volume_24h"] > 0 else 0
            # Invert: low ratio = good (not crowded)
            crowding_score = 1.0 / (1.0 + oi_vol_ratio)

            # Weighted composite
            edge_score = (
                0.40 * volume_score
                + 0.25 * momentum_score
                + 0.20 * funding_score
                + 0.15 * crowding_score
            )

            p["edge_score"] = edge_score
            p["volume_score"] = volume_score
            p["momentum_score"] = momentum_score
            p["funding_score"] = funding_score
            p["crowding_score"] = crowding_score

    def has_momentum(self, coin: str, min_change_pct: float = 0.3) -> bool:
        """
        Quick check if a pair has enough recent momentum to justify model inference.

        Use this to skip running the expensive LaT-PFN model on flat pairs.
        A pair with <0.3% price change in 24h is unlikely to produce a tradeable signal.

        Core pairs (BTC, ETH, SOL) always pass — we always want model predictions on them.
        """
        if coin in CORE_PAIRS:
            return True
        ctx = self._asset_contexts.get(coin)
        if not ctx:
            return False
        return abs(ctx.get("price_change_pct", 0)) >= min_change_pct

    def get_context(self, coin: str) -> Optional[Dict]:
        """Get cached funding/OI/volume context for a specific coin."""
        return self._asset_contexts.get(coin)

    def get_funding_rate(self, coin: str) -> float:
        """Get current funding rate for a coin. Positive = longs pay shorts."""
        ctx = self._asset_contexts.get(coin)
        return ctx["funding_rate"] if ctx else 0.0

    def get_open_interest(self, coin: str) -> float:
        """Get open interest in USD for a coin."""
        ctx = self._asset_contexts.get(coin)
        return ctx["open_interest"] if ctx else 0.0

    def get_edge_summary(self) -> str:
        """Format a compact edge summary for logging/Discord."""
        if not self._ranked_pairs:
            return "No pairs scanned"
        lines = []
        for p in self._ranked_pairs[:10]:
            funding_dir = "+" if p["funding_rate"] > 0 else ""
            lines.append(
                f"{p['coin']:6s} edge={p.get('edge_score', 0):.2f} "
                f"vol=${p['volume_24h']/1e6:.0f}M "
                f"chg={p['price_change_pct']:+.1f}% "
                f"fund={funding_dir}{p['funding_rate']*100:.4f}%"
            )
        return "\n".join(lines)

    def generate_instruments_config(self) -> Dict[str, Dict]:
        """
        Generate instruments config dict from scanned pairs.

        Compatible with the orchestrator's config["instruments"] format.
        """
        if not self._ranked_pairs:
            self.scan()

        instruments = {}
        for pair in self._ranked_pairs:
            coin = pair["coin"]
            price = pair["mid_price"]

            # Allow all tiers for HL scalping — position sizing handles risk
            vol = pair["volume_24h"]
            if vol > 100_000_000:  # >$100M — highly liquid
                allowed_tiers = ["layup", "short_range", "free_throw", "three_pointer", "half_court"]
            elif vol > 10_000_000:  # >$10M
                allowed_tiers = ["layup", "short_range", "free_throw", "three_pointer", "half_court"]
            else:  # <$10M — thinner but still tradeable with small size
                allowed_tiers = ["layup", "short_range", "free_throw", "three_pointer"]

            instruments[coin] = {
                "name": f"{coin} Perpetual",
                "contract_size": 1.0,
                "tick_size": _tick_size_for_price(price),
                "allowed_tiers": allowed_tiers,
                "context_assets": ["^VIX"],
                "yfinance_ticker": f"{coin}-USD",
                "sz_decimals": pair["sz_decimals"],
                "max_leverage": pair["max_leverage"],
            }

        return instruments


def _tick_size_for_price(price: float) -> float:
    """Determine appropriate tick size based on asset price."""
    if price >= 10000:
        return 0.1
    elif price >= 100:
        return 0.01
    elif price >= 1:
        return 0.001
    elif price >= 0.01:
        return 0.00001
    else:
        return 0.0000001
