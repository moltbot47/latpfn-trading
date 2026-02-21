"""
Turbo Crypto Scalper — fast continuous loop trading 5-min and 15-min
Up/Down binary markets on Polymarket (BTC, ETH, SOL, XRP).

Uses short-term momentum analysis to identify directional edge:
  1. Fetch real-time crypto prices (CoinGecko free API)
  2. Compute momentum signals (1m, 3m, 5m price changes)
  3. When momentum is strong in one direction, bet that direction
  4. Auto-resolve positions when windows close
  5. Repeat every tick (5-second polling)

These markets are NOT in the Gamma /markets endpoint — they use the
/events?slug={asset}-updown-{tf}-{timestamp} discovery pattern.
"""

import asyncio
import json
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import requests

from monitoring.turbo_analytics import TurboAnalytics
from polymarket.edge_engine import AdaptiveEdgeEngine
from polymarket.positions import PolyPosition

logger = logging.getLogger(__name__)

GAMMA_URL = "https://gamma-api.polymarket.com"

# Asset configs with CoinGecko IDs
ASSETS = {
    "btc": {"name": "Bitcoin", "coingecko_id": "bitcoin"},
    "eth": {"name": "Ethereum", "coingecko_id": "ethereum"},
    "sol": {"name": "Solana", "coingecko_id": "solana"},
    "xrp": {"name": "XRP", "coingecko_id": "ripple"},
}

TIMEFRAMES = {
    "5m": 300,
    "15m": 900,
}


@dataclass
class TurboWindow:
    """A single Up/Down trading window."""
    asset: str
    timeframe: str  # "5m" or "15m"
    slug: str
    start_ts: int
    end_ts: int
    condition_id: str
    up_token_id: str
    down_token_id: str
    up_price: float = 0.5
    down_price: float = 0.5
    traded: bool = False
    trade_direction: str = ""  # "Up" or "Down"
    trade_entry_price: float = 0.0
    trade_shares: float = 0.0
    trade_token_id: str = ""
    trade_size_usdc: float = 0.0
    resolved: bool = False


@dataclass
class PricePoint:
    """A timestamped price observation."""
    ts: float
    price: float


class TurboStrategy:
    """Fast-loop crypto Up/Down scalper with momentum analysis."""

    def __init__(self, client, position_mgr, risk, claimer, config: dict):
        self.client = client
        self.positions = position_mgr
        self.risk = risk
        self.claimer = claimer
        self.config = config

        pm_cfg = config.get("polymarket", {})
        tc = pm_cfg.get("turbo", {})

        self.enabled = tc.get("enabled", False)
        self.poll_seconds = tc.get("poll_seconds", 5)
        self.bet_size = tc.get("bet_size_usdc", 1.0)
        self.enabled_assets = tc.get("assets", ["btc", "eth", "sol", "xrp"])
        self.enabled_timeframes = tc.get("timeframes", ["5m", "15m"])
        self.max_positions = tc.get("max_positions", 50)
        self.momentum_threshold = tc.get("momentum_threshold", 0.0003)  # 0.03% min move
        self.min_seconds_left = tc.get("min_seconds_left", 30)
        self.max_seconds_left = tc.get("max_seconds_left", 240)
        self.min_entry_edge = tc.get("min_entry_edge", 0.02)  # Buy when price < 0.52
        self.cooldown_windows = tc.get("cooldown_windows", 0)
        self.claim_interval_seconds = tc.get("claim_interval_seconds", 300)

        # State
        self._windows: Dict[str, TurboWindow] = {}  # key -> window
        self._price_history: Dict[str, deque] = {}  # asset -> deque of PricePoint
        self._last_trade_window: Dict[str, int] = {}  # "asset_tf" -> start_ts
        self._session = requests.Session()
        self._last_claim_time = 0.0
        self._last_price_fetch = 0.0

        # Stats
        self.is_running = False
        self.cycle = 0
        self.total_trades = 0
        self.total_wins = 0
        self.total_losses = 0
        self.session_pnl = 0.0
        self._bot = None
        self.analytics = TurboAnalytics()

        # Intel from other agents (updated by Polymarket agent)
        self._intel = {
            "fear_greed": None,       # {value: 0-100, sentiment: str, ts: float}
            "regime": {},             # {asset: {regime: str, adx: float, ts: float}}
            "hl_bias": {},            # {asset: {direction: str, ts: float}}
            "risk_alert": False,      # True = circuit breaker active
            "convergence": 0.0,       # 0.0-1.0 combined intel strength
            "bet_multiplier": 1.0,    # Final computed multiplier (0.5-2.0)
            "last_update": 0.0,
        }

        # Rolling win-rate throttle: track last N outcomes for adaptive sizing
        self._recent_outcomes: deque = deque(maxlen=20)  # True=win, False=loss

        # Adaptive edge engine — self-adjusting trade filter
        self.edge_engine = AdaptiveEdgeEngine()

        # Message bus for cross-platform feedback (set externally)
        self._message_bus = None

        # Initialize price history deques (keep 5 min of data at 5s intervals)
        for asset in self.enabled_assets:
            self._price_history[asset] = deque(maxlen=60)

    def set_bot(self, bot):
        self._bot = bot

    # ── Agent Intel ─────────────────────────────────────────────────

    def update_intel(self, intel: dict):
        """Receive filtered intel from Polymarket agent. Same event loop = safe."""
        now = time.time()

        if "fear_greed" in intel:
            self._intel["fear_greed"] = {**intel["fear_greed"], "ts": now}

        if "regime" in intel:
            for asset, data in intel["regime"].items():
                self._intel["regime"][asset] = {**data, "ts": now}

        if "hl_bias" in intel:
            for asset, direction in intel["hl_bias"].items():
                self._intel["hl_bias"][asset] = {"direction": direction, "ts": now}

        if "risk_alert" in intel:
            self._intel["risk_alert"] = intel["risk_alert"]

        # Layer 2: HL funding rates → turbo directional bias
        if "funding_rates" in intel:
            self._intel["funding_rates"] = intel["funding_rates"]

        # Layer 2: HL position manager status
        if "position_manager" in intel:
            self._intel["hl_position_manager"] = intel["position_manager"]

        # Layer 2: HL per-asset WR (reverse feedback)
        if "hl_asset_wr" in intel:
            self._intel["hl_asset_wr"] = intel["hl_asset_wr"]

        self._intel["convergence"] = self._compute_convergence()
        self._intel["bet_multiplier"] = self._compute_bet_multiplier()
        self._intel["last_update"] = now

    def _compute_convergence(self) -> float:
        """Score 0.0-1.0: how many intel sources are active (any regime counts)."""
        now = time.time()
        score = 0.0

        # Fear & Greed: extreme values = stronger signal (0.25 max)
        fg = self._intel.get("fear_greed")
        if fg and (now - fg.get("ts", 0)) < 3600:
            value = fg.get("value", 50)
            extremity = abs(value - 50) / 50.0
            score += 0.25 * extremity

        # Regime: ANY fresh regime data = intel is active (0.25 max)
        regimes = self._intel.get("regime", {})
        fresh_regimes = sum(
            1 for data in regimes.values()
            if (now - data.get("ts", 0)) < 600
        )
        if fresh_regimes > 0:
            score += 0.25 * min(fresh_regimes / 3.0, 1.0)

        # HL bias: having a direction = one more signal (0.25 max)
        biases = self._intel.get("hl_bias", {})
        active_biases = sum(1 for b in biases.values()
                            if (now - b.get("ts", 0)) < 300)
        if active_biases > 0:
            score += 0.25 * min(active_biases / 2.0, 1.0)

        # Risk alert: always counts if active (0.25)
        if self._intel.get("risk_alert"):
            score += 0.25

        return min(score, 1.0)

    def _compute_bet_multiplier(self) -> float:
        """Bet size multiplier from intel. CAPPED at 1.0.

        Data insight: trades with multiplier >1.0x had 29.1% WR (-$199).
        Trades with <1.0x had 36.2% WR (+$26). The intel multiplier was
        INVERSELY correlated with performance. So we only allow it to
        REDUCE bet size, never increase it.
        """
        multiplier = 1.0
        now = time.time()

        # Risk alert = circuit breaker (always active)
        if self._intel.get("risk_alert"):
            multiplier *= 0.5

        # Regime: ALWAYS apply when fresh — no convergence gate
        # Trending = reduce (contrarian is bad in trends)
        regimes = self._intel.get("regime", {})
        trending_count = 0
        volatile_count = 0
        for data in regimes.values():
            if (now - data.get("ts", 0)) < 600:
                r = data.get("regime", "")
                adx = data.get("adx", 0)
                if r == "trending" and adx > 25:
                    trending_count += 1
                elif r == "volatile":
                    volatile_count += 1

        if trending_count >= 2:
            multiplier *= 0.4    # Multiple trending — aggressive cut
        elif trending_count >= 1:
            multiplier *= 0.6    # Single trending — reduce size
        elif volatile_count >= 1:
            multiplier *= 0.7    # Volatile — cautious
        # NOTE: ranging bonus REMOVED — data shows it hurt, not helped

        # Rolling win-rate throttle: if last 20 trades < 30% WR, cut size
        rolling_wr = self._get_rolling_win_rate()
        if rolling_wr is not None:
            if rolling_wr < 0.20:
                multiplier *= 0.3   # Severe cold streak — minimal bets
            elif rolling_wr < 0.30:
                multiplier *= 0.5   # Below breakeven — half size

        # NEVER exceed 1.0 — data shows higher multiplier = worse results
        return max(0.3, min(multiplier, 1.0))

    def _get_rolling_win_rate(self) -> Optional[float]:
        """Return win rate of last 20 trades, or None if < 10 trades."""
        if len(self._recent_outcomes) < 10:
            return None
        return sum(self._recent_outcomes) / len(self._recent_outcomes)

    def _run_claim_sync(self) -> list:
        """Run the async claimer in a thread-safe way (web3 is synchronous)."""
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(
                self.claimer.claim_resolved_positions(
                    self.positions, override_interval=self.claim_interval_seconds
                )
            )
        finally:
            loop.close()

    # ── Main Loop ────────────────────────────────────────────────────

    async def run_loop(self):
        """Main turbo loop — runs until stopped."""
        self.is_running = True
        logger.info(
            "[TURBO] Starting: assets=%s, timeframes=%s, poll=%ds, bet=$%.2f, "
            "momentum=%.4f, timing=%d-%ds",
            self.enabled_assets, self.enabled_timeframes, self.poll_seconds,
            self.bet_size, self.momentum_threshold,
            self.min_seconds_left, self.max_seconds_left,
        )

        while self.is_running:
            try:
                await self._tick()
            except Exception as e:
                logger.error("[TURBO] Tick error: %s", e, exc_info=True)
            await asyncio.sleep(self.poll_seconds)

        logger.info(
            "[TURBO] Stopped: %d trades, %d W / %d L, PnL=$%.2f",
            self.total_trades, self.total_wins, self.total_losses,
            self.session_pnl,
        )

    async def stop(self):
        self.is_running = False

    async def _tick(self):
        """One iteration: fetch prices, discover windows, check signals, resolve."""
        self.cycle += 1
        now = time.time()

        # ── 1. Fetch crypto prices (every 10s to avoid rate limits) ──
        if now - self._last_price_fetch >= 10:
            try:
                await asyncio.wait_for(
                    asyncio.to_thread(self._fetch_prices), timeout=10
                )
                self._last_price_fetch = now
            except asyncio.TimeoutError:
                logger.warning("[TURBO] Price fetch timed out (10s)")
            except Exception as e:
                logger.warning("[TURBO] Price fetch error: %s", e)

        # ── 2. Discover/refresh/resolve windows (BEFORE claims) ──────
        for asset in self.enabled_assets:
            for tf in self.enabled_timeframes:
                try:
                    await asyncio.wait_for(
                        self._manage_window(asset, tf), timeout=15
                    )
                except asyncio.TimeoutError:
                    logger.warning("[TURBO] Window %s_%s timed out (15s)", asset, tf)
                except Exception as e:
                    logger.warning("[TURBO] Window %s_%s error: %s", asset, tf, e)

        # ── 3. Auto-claim (AFTER resolutions so W/L tracked first) ──
        # NOTE: Claimer uses synchronous web3 — run in thread to avoid
        # blocking the turbo event loop.
        if now - self._last_claim_time >= self.claim_interval_seconds:
            try:
                claims = await asyncio.wait_for(
                    asyncio.to_thread(self._run_claim_sync),
                    timeout=60,
                )
                self._last_claim_time = now
                if claims:
                    balance = self.client.get_balance()
                    if balance > 0:
                        self.risk.update_budget(balance)
                    logger.info("[TURBO] Claimed %d positions", len(claims))
            except asyncio.TimeoutError:
                logger.warning("[TURBO] Claim timed out (60s)")
                self._last_claim_time = now
            except Exception as e:
                logger.warning("[TURBO] Claim error: %s", e)
                self._last_claim_time = now

        # ── 4. Log periodic status ───────────────────────────────────
        if self.cycle % 60 == 1:  # Every ~5 minutes
            turbo_count = len(self.positions.get_positions_by_strategy("turbo"))
            conv = self._intel.get("convergence", 0)
            mult = self._intel.get("bet_multiplier", 1.0)
            rolling_wr = self._get_rolling_win_rate()
            wr_str = f"{rolling_wr:.0%}" if rolling_wr is not None else "n/a"
            em = self.edge_engine.get_metrics()
            logger.info(
                "[TURBO] Status: cycle=%d, positions=%d, trades=%d, "
                "W/L=%d/%d, PnL=$%.2f, intel=%.2f/%.1fx, rolling_wr=%s, "
                "edge=%d/100, blocked=%s/%s/hr%s, band=$%.2f-$%.2f",
                self.cycle, turbo_count, self.total_trades,
                self.total_wins, self.total_losses, self.session_pnl,
                conv, mult, wr_str,
                em.edge_score,
                em.blocked_assets or "none",
                em.blocked_directions or "none",
                em.blocked_hours or "none",
                em.optimal_floor, em.optimal_ceiling,
            )

    # ── Window Management ────────────────────────────────────────────

    async def _manage_window(self, asset: str, tf: str):
        """Discover, trade, and resolve a single asset/timeframe window."""
        key = f"{asset}_{tf}"
        interval = TIMEFRAMES[tf]
        now = time.time()
        now_int = int(now)
        current_ts = now_int - (now_int % interval)

        existing = self._windows.get(key)

        # ── Resolve expired window ───────────────────────────────
        if existing and now > existing.end_ts + 10:
            logger.info(
                "[TURBO] Resolving %s_%s (end=%d, now=%d, traded=%s)",
                asset, tf, existing.end_ts, int(now), existing.traded,
            )
            await self._resolve_window(existing)
            self._windows.pop(key, None)
            existing = None
        elif existing and existing.start_ts != current_ts:
            # Window from a previous period but not yet expired — force resolve
            logger.info(
                "[TURBO] Stale window %s_%s (start=%d, current=%d, traded=%s) — resolving",
                asset, tf, existing.start_ts, current_ts, existing.traded,
            )
            await self._resolve_window(existing)
            self._windows.pop(key, None)
            existing = None

        # ── Discover new window if needed ────────────────────────
        if not existing or existing.start_ts != current_ts:
            window = await asyncio.to_thread(
                self._discover_window, asset, tf, current_ts
            )
            if window:
                self._windows[key] = window
                existing = window

        if not existing:
            return

        # ── Refresh market prices ────────────────────────────────
        await asyncio.to_thread(self._refresh_prices, existing)

        # ── Check for trade signal ───────────────────────────────
        conv = self._intel.get("convergence", 0)
        mult = self._intel.get("bet_multiplier", 1.0)

        if existing.traded:
            # Still compute a shadow signal for analytics
            shadow_signal, _, shadow_momentum = self._check_signal(existing)
            self.analytics.log_signal_check(
                asset=asset, tf=tf, window=existing,
                momentum=shadow_momentum, signal=None,
                skip_reason="already_traded",
                shadow_signal=shadow_signal,
                intel_convergence=conv, intel_multiplier=mult,
            )
            return

        signal, skip_reason, momentum = self._check_signal(existing)

        # Log every evaluation (traded or not)
        self.analytics.log_signal_check(
            asset=asset, tf=tf, window=existing,
            momentum=momentum, signal=signal,
            skip_reason=skip_reason,
            intel_convergence=conv, intel_multiplier=mult,
        )

        if signal:
            await self._execute_trade(existing, signal)

    def _discover_window(self, asset: str, tf: str, window_ts: int) -> Optional[TurboWindow]:
        """Fetch window from Gamma events API."""
        interval = TIMEFRAMES[tf]
        slug = f"{asset}-updown-{tf}-{window_ts}"
        try:
            resp = self._session.get(
                f"{GAMMA_URL}/events",
                params={"slug": slug},
                timeout=5,
            )
            events = resp.json() if resp.status_code == 200 else []
            if not events:
                return None

            event = events[0]
            markets = event.get("markets", [])
            if not markets:
                return None

            market = markets[0]
            for fld in ("clobTokenIds", "outcomePrices", "outcomes"):
                if isinstance(market.get(fld), str):
                    try:
                        market[fld] = json.loads(market[fld])
                    except (json.JSONDecodeError, TypeError):
                        pass

            tokens = market.get("clobTokenIds", [])
            prices = market.get("outcomePrices", [])
            if len(tokens) < 2:
                return None

            return TurboWindow(
                asset=asset,
                timeframe=tf,
                slug=slug,
                start_ts=window_ts,
                end_ts=window_ts + interval,
                condition_id=market.get("conditionId", ""),
                up_token_id=tokens[0],
                down_token_id=tokens[1],
                up_price=float(prices[0]) if prices else 0.5,
                down_price=float(prices[1]) if len(prices) > 1 else 0.5,
            )
        except Exception as e:
            logger.debug("[TURBO] Window discovery failed %s/%s: %s", asset, tf, e)
            return None

    def _refresh_prices(self, window: TurboWindow):
        """Refresh market prices from CLOB midpoint."""
        try:
            mid = self.client.get_midpoint(window.up_token_id)
            if mid > 0:
                window.up_price = mid
                window.down_price = 1.0 - mid
        except Exception:
            pass

    # ── Price Data ───────────────────────────────────────────────────

    def _fetch_prices(self):
        """Fetch current crypto prices from CoinGecko (free, no key)."""
        ids = ",".join(
            ASSETS[a]["coingecko_id"] for a in self.enabled_assets if a in ASSETS
        )
        try:
            resp = self._session.get(
                "https://api.coingecko.com/api/v3/simple/price",
                params={"ids": ids, "vs_currencies": "usd"},
                timeout=5,
            )
            if resp.status_code != 200:
                return

            data = resp.json()
            now = time.time()
            for asset in self.enabled_assets:
                cg_id = ASSETS.get(asset, {}).get("coingecko_id")
                if cg_id and cg_id in data:
                    price = data[cg_id].get("usd", 0)
                    if price > 0:
                        self._price_history[asset].append(
                            PricePoint(ts=now, price=price)
                        )
        except Exception as e:
            logger.debug("[TURBO] Price fetch error: %s", e)

    def _compute_momentum(self, asset: str) -> Dict:
        """
        Compute momentum signals from price history.

        Returns dict with:
          - direction: "Up" or "Down" or None
          - strength: magnitude of momentum (0-1)
          - pct_change_1m: 1-minute price change
          - pct_change_3m: 3-minute price change
        """
        history = self._price_history.get(asset)
        if not history or len(history) < 3:
            return {"direction": None, "strength": 0, "pct_change_1m": 0, "pct_change_3m": 0}

        now = time.time()
        current_price = history[-1].price

        # Find prices at various lookbacks
        price_1m = None
        price_3m = None
        for pt in reversed(history):
            age = now - pt.ts
            if price_1m is None and age >= 10:  # At least 10s old
                price_1m = pt.price
            if price_3m is None and age >= 60:  # At least 60s old
                price_3m = pt.price
            if price_1m and price_3m:
                break

        if price_1m is None:
            price_1m = history[0].price
        if price_3m is None:
            price_3m = history[0].price

        pct_1m = (current_price - price_1m) / price_1m if price_1m else 0
        pct_3m = (current_price - price_3m) / price_3m if price_3m else 0

        # Weighted momentum: 60% recent (1m), 40% trend (3m)
        combined = pct_1m * 0.6 + pct_3m * 0.4

        if abs(combined) < self.momentum_threshold:
            direction = None
        else:
            direction = "Up" if combined > 0 else "Down"

        strength = min(abs(combined) / 0.005, 1.0)  # Normalize: 0.5% move = max strength

        return {
            "direction": direction,
            "strength": strength,
            "pct_change_1m": pct_1m,
            "pct_change_3m": pct_3m,
        }

    # ── Signal Detection ─────────────────────────────────────────────

    def _check_signal(
        self, window: TurboWindow
    ) -> Tuple[Optional[Dict], str, Dict]:
        """
        Check if we should trade this window.

        Returns:
            (signal_dict | None, skip_reason, momentum_dict)

        Strategy: combine momentum analysis with market price.
        - If momentum says "Up" and Up price is below 0.55, buy Up
        - If market already prices one side > 0.60, follow the market
        - Don't trade if no clear signal
        """
        now = time.time()
        seconds_left = window.end_ts - now

        # Always compute momentum so we can log it
        momentum = self._compute_momentum(window.asset)
        # Attach current crypto price for analytics
        history = self._price_history.get(window.asset)
        if history:
            momentum["_current_price"] = history[-1].price

        # Timing check
        if seconds_left < self.min_seconds_left:
            return None, "too_late", momentum
        if seconds_left > self.max_seconds_left:
            return None, "too_early", momentum

        # Cooldown check
        cooldown_key = f"{window.asset}_{window.timeframe}"
        last_ts = self._last_trade_window.get(cooldown_key, 0)
        interval = TIMEFRAMES[window.timeframe]
        if window.start_ts - last_ts < interval * self.cooldown_windows:
            if last_ts > 0:
                return None, "cooldown", momentum

        # Position limit check
        turbo_count = len(self.positions.get_positions_by_strategy("turbo"))
        if turbo_count >= self.max_positions:
            return None, "position_limit", momentum

        mom_dir = momentum["direction"]
        mom_strength = momentum["strength"]

        # Decision logic — HYBRID STRATEGY (contrarian + market_lean)
        #
        # Data analysis (554 trades):
        #   contrarian: 29.8% WR, -$234 (LOSING)
        #   market_lean: 77.8% WR, +$3.45 (WINNING, small sample)
        #   after_win: 53.2% WR — wins cluster
        #   after_loss: 21.8% WR — losses cluster
        #
        # New approach:
        #   1. When momentum CONFIRMS market lean → buy cheap side (contrarian)
        #      (market is overreacting, momentum is fading = mean reversion)
        #   2. When momentum CONFIRMS expensive side → buy expensive side (lean)
        #      (market + momentum agree = high probability)
        #   3. When on a win streak → trust contrarian more aggressively
        #   4. When cold → only take high-confidence setups
        direction = None
        entry_price = None
        reason = ""
        signal_type = "contrarian"

        # Determine market lean
        market_up_lean = window.up_price >= 0.60 and window.up_price <= 0.85
        market_down_lean = window.down_price >= 0.60 and window.down_price <= 0.85

        # MODE 1: Market lean WITH momentum confirmation → follow the market
        # (market_lean signal type: 77.8% WR in data)
        if market_up_lean and mom_dir == "Up" and mom_strength > 0.2:
            # Market says Up + momentum says Up → bet Up (follow market)
            direction = "Up"
            entry_price = window.up_price
            reason = f"market_lean_up (mkt={window.up_price:.2f}, mom={mom_strength:.2f})"
            signal_type = "market_lean"

        elif market_down_lean and mom_dir == "Down" and mom_strength > 0.2:
            # Market says Down + momentum says Down → bet Down (follow market)
            direction = "Down"
            entry_price = window.down_price
            reason = f"market_lean_down (mkt={window.down_price:.2f}, mom={mom_strength:.2f})"
            signal_type = "market_lean"

        # MODE 2: Contrarian — buy cheap side when momentum is fading/neutral
        # Only when momentum does NOT strongly oppose (filtered below)
        elif market_up_lean:
            direction = "Down"
            entry_price = window.down_price
            reason = f"contrarian_down (market_up={window.up_price:.2f})"
            signal_type = "contrarian"

        elif market_down_lean:
            direction = "Up"
            entry_price = window.up_price
            reason = f"contrarian_up (market_down={window.down_price:.2f})"
            signal_type = "contrarian"

        if not direction or not entry_price:
            return None, "no_signal", momentum

        # ── Momentum confirmation filter ─────────────────────────────
        # Data insight: pure contrarian gets 29.8% WR (losing).
        # When momentum STRONGLY contradicts our direction, the market
        # is pricing correctly and contrarian is wrong.
        # Block trades where momentum is strongly AGAINST our direction.
        if mom_dir is not None and mom_strength > 0.3:
            # Strong momentum exists — check if it contradicts our bet
            if (direction == "Up" and mom_dir == "Down") or \
               (direction == "Down" and mom_dir == "Up"):
                return None, "momentum_conflict", momentum

        # ── Adaptive Edge Engine gate ──────────────────────────────
        # Replaces static entry band + daily loss limit with data-driven
        # filters across asset, direction, hour, price bucket, and
        # circuit breakers (hourly drawdown, loss streaks, edge decay).
        allowed, edge_reason = self.edge_engine.should_trade(
            asset=window.asset, direction=direction, entry_price=entry_price,
        )
        if not allowed:
            return None, f"edge_{edge_reason}", momentum

        # Tag HL direction conflict (informational — for analytics, doesn't block)
        if direction and self._intel.get("convergence", 0) >= 0.5:
            hl_bias = self._intel.get("hl_bias", {}).get(window.asset, {})
            if hl_bias and (time.time() - hl_bias.get("ts", 0)) < 300:
                hl_dir = hl_bias.get("direction", "")
                if (hl_dir == "long" and direction == "Down") or \
                   (hl_dir == "short" and direction == "Up"):
                    reason += " [HL_conflict]"

        token_id = window.up_token_id if direction == "Up" else window.down_token_id
        edge_pct = (1.0 - entry_price) / entry_price * 100 if entry_price > 0 else 0

        signal = {
            "direction": direction,
            "token_id": token_id,
            "price": entry_price,
            "edge_pct": edge_pct,
            "seconds_left": seconds_left,
            "reason": reason,
            "momentum": momentum,
            "signal_type": signal_type,
        }
        return signal, "", momentum

    # ── Execution ────────────────────────────────────────────────────

    async def _execute_trade(self, window: TurboWindow, signal: Dict):
        """Place a turbo trade — bet size adjusted by streak + edge data."""
        price = signal["price"]
        direction = signal["direction"]
        token_id = signal["token_id"]

        # Calculate shares: streak multiplier is primary (data-driven),
        # intel multiplier is CAPPED at 1.0 (data shows >1.0 = worse WR)
        streak_mult = self.edge_engine.get_streak_multiplier()
        intel_mult = min(self._intel.get("bet_multiplier", 1.0), 1.0)
        adjusted_bet = self.bet_size * streak_mult * intel_mult
        shares = adjusted_bet / price if price > 0 else 0
        if shares < 5:
            # Polymarket minimum 5 shares
            cost = 5 * price
            if cost > 5:  # Don't spend more than $5 on minimum share bump
                logger.debug("[TURBO] Skip: min share cost $%.2f > $5", cost)
                return
            shares = 5
            size_usdc = cost
        else:
            size_usdc = self.bet_size

        # Risk check
        can_trade, reason = self.risk.can_trade(strategy="turbo")
        if not can_trade:
            logger.info("[TURBO] Risk blocked: %s (shares=%.1f, cost=$%.2f)", reason, shares, size_usdc)
            return

        try:
            result = self.client.buy_limit(
                token_id=token_id,
                price=price,
                size=shares,
            )
        except Exception as e:
            logger.error("[TURBO] Trade failed: %s", e)
            return

        order_id = result.get("orderID", "")
        if not order_id:
            logger.error("[TURBO] Missing orderID: %s", result)
            return

        # Mark window as traded (store trade details for W/L tracking)
        window.traded = True
        window.trade_direction = direction
        window.trade_entry_price = price
        window.trade_shares = shares
        window.trade_token_id = token_id
        window.trade_size_usdc = size_usdc
        cooldown_key = f"{window.asset}_{window.timeframe}"
        self._last_trade_window[cooldown_key] = window.start_ts

        # Record position
        pos = PolyPosition(
            market_id=window.condition_id,
            token_id=token_id,
            question=f"{window.asset.upper()} Up/Down {window.timeframe} ({direction})",
            strategy="turbo",
            direction=direction,
            entry_price=price,
            size_usdc=size_usdc,
            shares=shares,
            target_exit=1.0,
            expected_pnl_pct=signal["edge_pct"],
            resolution_date=time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime(window.end_ts)
            ),
            market_probability=price,
            order_id=order_id,
            metadata={
                "reason": signal["reason"],
                "momentum_1m": signal["momentum"]["pct_change_1m"],
                "momentum_3m": signal["momentum"]["pct_change_3m"],
                "seconds_left": signal["seconds_left"],
                "timeframe": window.timeframe,
            },
        )
        key = self.positions.open_position(pos)
        self.total_trades += 1

        # Log trade execution to analytics DB
        self.analytics.log_trade_execution(
            asset=window.asset, tf=window.timeframe,
            window_start_ts=window.start_ts,
            entry_price=price, shares=shares,
            size_usdc=size_usdc, order_id=order_id,
        )

        logger.info(
            "[TURBO] TRADE: %s %s %s @ %.2f | $%.2f (streak=%.2fx) | %ds left | %s",
            window.asset.upper(), window.timeframe, direction, price,
            size_usdc, streak_mult, signal["seconds_left"], signal["reason"],
        )

        # Discord notification
        if self._bot:
            try:
                await self._bot.post_poly_trade({
                    "position_key": key,
                    "order_id": order_id,
                    "question": pos.question,
                    "strategy": "turbo",
                    "direction": direction,
                    "entry_price": price,
                    "size_usdc": size_usdc,
                    "divergence": 0,
                    "market_price": price,
                })
            except Exception:
                pass

    # ── Resolution ───────────────────────────────────────────────────

    async def _resolve_window(self, window: TurboWindow):
        """Resolve a traded window and track W/L.

        Uses trade details stored on the window object so resolution works
        even if the orchestrator's claimer already removed the position
        from the tracker.
        """
        if not window.traded or window.resolved:
            return

        window.resolved = True

        # Get final price for the traded token (in thread to avoid blocking)
        try:
            mid = await asyncio.wait_for(
                asyncio.to_thread(
                    self.client.get_midpoint, window.trade_token_id
                ),
                timeout=10,
            )
            if mid <= 0:
                mid = 0.5  # Unknown — assume push
        except (asyncio.TimeoutError, Exception):
            mid = 0.5

        # Final price should be ~1.0 (win) or ~0.0 (loss)
        outcome_price = round(mid)  # 0 or 1
        pnl = (outcome_price - window.trade_entry_price) * window.trade_shares

        # Also resolve in position tracker if still present
        for key, pos in list(self.positions.get_open_positions().items()):
            if pos.strategy == "turbo" and pos.market_id == window.condition_id:
                self.positions.resolve_position(key, outcome_price)

        if outcome_price > 0.5:
            self.total_wins += 1
            result_str = "WIN"
            self._recent_outcomes.append(True)
            self.edge_engine.record_outcome(is_win=True, pnl=pnl)
        else:
            self.total_losses += 1
            result_str = "LOSS"
            self._recent_outcomes.append(False)
            self.edge_engine.record_outcome(is_win=False, pnl=pnl)

        self.session_pnl += pnl
        self.risk.record_pnl(pnl)

        # Recompute bet multiplier with fresh rolling WR
        self._intel["bet_multiplier"] = self._compute_bet_multiplier()

        # Log resolution to analytics DB (updates traded + shadow rows)
        self.analytics.log_resolution(
            asset=window.asset, tf=window.timeframe,
            window_start_ts=window.start_ts,
            outcome=outcome_price, pnl=pnl,
        )

        question = (
            f"{window.asset.upper()} Up/Down {window.timeframe} "
            f"({window.trade_direction})"
        )
        logger.info(
            "[TURBO] RESOLVED: %s → %s | PnL=$%.2f (total: $%.2f)",
            question, result_str, pnl, self.session_pnl,
        )

        # Discord notification
        if self._bot:
            try:
                await self._bot.post_poly_exit({
                    "key": f"turbo_{window.slug}",
                    "strategy": "turbo",
                    "question": question,
                    "exit_price": outcome_price,
                    "pnl": pnl,
                    "reason": result_str,
                })
            except Exception:
                pass

        # Publish performance feedback to HL agent (Layer 2 — bidirectional)
        await self._publish_perf_feedback(window.asset, window.trade_direction, outcome_price > 0.5)

    async def _publish_perf_feedback(self, asset: str, direction: str, won: bool):
        """Publish per-trade performance feedback to message bus for HL agent."""
        bus = getattr(self, '_message_bus', None)
        if not bus:
            return

        # Compute per-asset WR from analytics DB
        try:
            asset_wr = {}
            for a in self.enabled_assets:
                stats = self.edge_engine._metrics.asset_stats.get(a)
                if stats and stats.total >= 5:
                    asset_wr[a] = stats.wins / stats.total

            # Overall WR
            total_resolved = self.total_wins + self.total_losses
            overall_wr = self.total_wins / total_resolved if total_resolved > 0 else 0

            # Streak state
            streak_mult = self.edge_engine.get_streak_multiplier()
            metrics = self.edge_engine.get_metrics()
            if metrics.cooldown_active:
                streak_state = f"cool:{metrics.cooldown_remaining:.0f}s"
            elif metrics.win_streak_active:
                streak_state = f"hot:{metrics.consecutive_wins}W"
            else:
                streak_state = "neutral"

            from agents.message_bus import AgentMessage, MessageType
            payload = {
                "source": "turbo",
                "asset_wr": asset_wr,
                "overall_wr": overall_wr,
                "streak_state": streak_state,
                "streak_mult": streak_mult,
                "last_result": {
                    "asset": asset,
                    "direction": direction,
                    "won": won,
                },
                "total_trades": total_resolved,
            }
            await bus.publish(AgentMessage(
                msg_type=MessageType.PERF_FEEDBACK,
                sender="turbo",
                payload=payload,
            ))
        except Exception as e:
            logger.debug("Turbo feedback publish failed: %s", e)

    # ── Status ───────────────────────────────────────────────────────

    def get_status(self) -> Dict:
        """Get turbo strategy status."""
        turbo_pos = self.positions.get_positions_by_strategy("turbo")
        deployed = sum(p.size_usdc for p in turbo_pos.values())
        windows = {}
        for key, w in self._windows.items():
            secs = max(0, w.end_ts - time.time())
            windows[key] = {
                "up": w.up_price, "down": w.down_price,
                "seconds_left": int(secs), "traded": w.traded,
            }
        # Win rate
        total_resolved = self.total_wins + self.total_losses
        win_rate = self.total_wins / total_resolved if total_resolved > 0 else 0

        return {
            "running": self.is_running,
            "cycle": self.cycle,
            "positions": len(turbo_pos),
            "max_positions": self.max_positions,
            "deployed": round(deployed, 2),
            "session_trades": self.total_trades,
            "session_wins": self.total_wins,
            "session_losses": self.total_losses,
            "win_rate": round(win_rate, 3),
            "session_pnl": round(self.session_pnl, 4),
            "bet_size": self.bet_size,
            "active_windows": windows,
            "price_data": {
                asset: len(hist)
                for asset, hist in self._price_history.items()
            },
            "intel": {
                "convergence": round(self._intel.get("convergence", 0), 2),
                "bet_multiplier": round(self._intel.get("bet_multiplier", 1.0), 2),
                "fear_greed": self._intel.get("fear_greed", {}).get("value") if self._intel.get("fear_greed") else None,
                "risk_alert": self._intel.get("risk_alert", False),
                "last_update_age": round(time.time() - self._intel.get("last_update", 0)) if self._intel.get("last_update") else None,
            },
            "edge_engine": {
                "score": self.edge_engine.get_metrics().edge_score,
                "blocked_assets": self.edge_engine.get_metrics().blocked_assets,
                "blocked_directions": self.edge_engine.get_metrics().blocked_directions,
                "blocked_hours": self.edge_engine.get_metrics().blocked_hours,
                "band": (self.edge_engine.get_metrics().optimal_floor,
                         self.edge_engine.get_metrics().optimal_ceiling),
                "edge_decay": round(self.edge_engine.get_metrics().edge_decay, 3),
                "edge_decaying": self.edge_engine.get_metrics().edge_decaying,
            },
        }
