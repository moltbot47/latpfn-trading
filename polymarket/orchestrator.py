"""
Polymarket trading orchestrator — independent event loop that runs
both strategies (Resolution Sniping + LLM Superforecaster).

Can run standalone (python -m polymarket) or alongside the Hyperliquid
trading system in the same asyncio loop.
"""

import asyncio
import logging
import time
from typing import Dict, List, Optional

from polymarket.claimer import PositionClaimer
from polymarket.client import PolymarketClient
from polymarket.crypto_scalper import CryptoScalper
from polymarket.llm_forecaster import LLMForecaster
from polymarket.max_concurrent import MaxConcurrentStrategy
from polymarket.positions import PositionManager
from polymarket.resolution_sniper import ResolutionSniper
from polymarket.risk import PolymarketRisk
from polymarket.scanner import MarketScanner
from polymarket.superforecaster import SuperforecasterStrategy
from polymarket.turbo_strategy import TurboStrategy

logger = logging.getLogger(__name__)


class PolymarketOrchestrator:
    """Runs both Polymarket strategies in an async event loop."""

    def __init__(self, config: dict):
        self.config = config
        pm_cfg = config.get("polymarket", {})
        self.cycle_minutes = pm_cfg.get("cycle_minutes", 10)
        self.enabled = pm_cfg.get("enabled", True)
        self.is_running = False
        self.cycle = 0

        # Components (initialized in start())
        self.client = PolymarketClient(config)
        self.positions = PositionManager()
        self.risk = PolymarketRisk(config, self.positions)
        self.scanner = MarketScanner(self.client, config)
        self.forecaster = LLMForecaster(config)
        self.sniper = ResolutionSniper(
            self.client, self.scanner, self.positions, config
        )
        self.superforecaster = SuperforecasterStrategy(
            self.client, self.scanner, self.forecaster, self.positions, config
        )
        self.max_concurrent_strategy = MaxConcurrentStrategy(
            self.client, self.scanner, self.forecaster, self.positions, config
        )
        self.scalper = CryptoScalper(self.client, self.positions, config)
        self.claimer = PositionClaimer(config)
        self.turbo = TurboStrategy(
            self.client, self.positions, self.risk, self.claimer, config,
        )

        # Last scan results (for Discord commands)
        self.last_scan: Optional[Dict] = None
        self.last_scan_time: float = 0
        self._bot = None  # Set by runner for Discord notifications
        self._scalper_task: Optional[asyncio.Task] = None
        self._turbo_task: Optional[asyncio.Task] = None

    def set_bot(self, bot):
        """Attach Discord bot for trade notifications."""
        self._bot = bot
        self.scalper.set_bot(bot)
        self.turbo.set_bot(bot)

    async def start(self):
        """Connect to Polymarket and start the scanning loop."""
        if not self.enabled:
            logger.info("Polymarket orchestrator disabled in config")
            return

        logger.info("Starting Polymarket orchestrator...")
        await self.client.connect()

        # Update budget from live balance (Bug 2 fix: sync all components)
        balance = self.client.get_balance()
        if balance > 0:
            self.risk.update_budget(balance)
            self.sniper.budget = balance
            self.superforecaster.budget = balance
            mc_cfg = self.config.get("polymarket", {}).get("max_concurrent", {})
            self.max_concurrent_strategy.budget = balance * mc_cfg.get("budget_pct", 0.35)
            logger.info("Polymarket balance: $%.2f (MC budget: $%.2f)",
                        balance, self.max_concurrent_strategy.budget)

        self.is_running = True

        # Start crypto scalper as a separate fast loop (1-second ticks)
        scalper_cfg = self.config.get("polymarket", {}).get("scalper", {})
        if scalper_cfg.get("enabled", False):
            self.scalper.budget = self.risk.budget
            self._scalper_task = asyncio.create_task(self.scalper.run_loop())
            logger.info("Crypto scalper started (1-second loop)")

        # Start turbo strategy as a separate fast loop (60-second cycles)
        turbo_cfg = self.config.get("polymarket", {}).get("turbo", {})
        if turbo_cfg.get("enabled", False):
            self._turbo_task = asyncio.create_task(self.turbo.run_loop())
            logger.info("Turbo strategy started (%ds poll)", self.turbo.poll_seconds)

        logger.info(
            "Polymarket orchestrator running (cycle=%dmin, budget=$%.2f)",
            self.cycle_minutes, self.risk.budget,
        )

        while self.is_running:
            try:
                await self._scan_cycle()
            except Exception as e:
                logger.error("Polymarket cycle error: %s", e, exc_info=True)

            await asyncio.sleep(self.cycle_minutes * 60)

    async def shutdown(self):
        """Stop the orchestrator gracefully."""
        self.is_running = False
        if self._scalper_task and not self._scalper_task.done():
            self._scalper_task.cancel()
        if self._turbo_task and not self._turbo_task.done():
            await self.turbo.stop()
            self._turbo_task.cancel()
        await self.client.disconnect()
        logger.info("Polymarket orchestrator shut down")

    async def _scan_cycle(self, execute: bool = True, max_trades: int = 4):
        """
        Run one full scan + optional trade cycle.

        Args:
            execute:    If False, scan only — do not place trades.
            max_trades: Max trades to execute per cycle.
        """
        self.cycle += 1
        logger.info("=== Polymarket cycle %d (execute=%s) ===", self.cycle, execute)

        # ── Auto-claim resolved positions (frees up USDC) ────────
        # NOTE: Claimer uses synchronous web3 internally.  Run in a thread
        # so it doesn't block the event loop (turbo + scalper tasks starve).
        claims = []
        try:
            claims = await asyncio.wait_for(
                asyncio.to_thread(self._run_claim_sync),
                timeout=90,
            )
            if claims:
                # Refresh balance after claims returned USDC to Safe
                balance = self.client.get_balance()
                if balance > 0:
                    self.risk.update_budget(balance)
                    self.sniper.budget = balance
                    self.superforecaster.budget = balance
                    mc_cfg = self.config.get("polymarket", {}).get("max_concurrent", {})
                    self.max_concurrent_strategy.budget = balance * mc_cfg.get("budget_pct", 0.35)
                    logger.info(
                        "Post-claim balance: $%.2f (MC budget: $%.2f)",
                        balance, self.max_concurrent_strategy.budget,
                    )
        except asyncio.TimeoutError:
            logger.warning("Auto-claim timed out (90s)")
        except Exception as e:
            logger.error("Auto-claim error: %s", e)

        # Fetch markets once (shared by both strategies) — in thread to avoid blocking
        try:
            markets = await asyncio.wait_for(
                asyncio.to_thread(self.scanner.scan_markets), timeout=120
            )
        except asyncio.TimeoutError:
            logger.warning("Market scan timed out (120s) — using empty list")
            markets = []

        result = {
            "cycle": self.cycle,
            "markets_scanned": len(markets),
            "snipe_candidates": [],
            "divergence_candidates": [],
            "mc_candidates": [],
            "executed": [],
            "exits": [],
            "claims": claims,
            "errors": [],
        }

        # ── Check existing positions for exits ──────────────────────
        if execute:
            exits = await self._check_exits()
            result["exits"] = exits

        # ── Strategy 1: Resolution Sniping ──────────────────────────
        try:
            snipe_candidates = self.sniper.find_candidates(markets)
            # Evaluate all candidates for sizing info (Bug 8 fix)
            for c in snipe_candidates[:5]:
                self.sniper.evaluate(c)
            result["snipe_candidates"] = snipe_candidates[:5]

            if execute:
                can_trade, reason = self.risk.can_trade()
                if not can_trade:
                    result["blocked_reason"] = reason
                else:
                    trades_placed = 0
                    for candidate in snipe_candidates:
                        if trades_placed >= max_trades:
                            break
                        if candidate.get("size_usdc", 0) < 1.0:
                            continue

                        approved, msg = self.risk.validate_trade(
                            "resolution_snipe",
                            candidate["size_usdc"],
                            candidate["yes_price"],
                            candidate["market_id"],
                        )
                        if not approved:
                            logger.info("Snipe rejected: %s", msg)
                            continue

                        trade = await self.sniper.execute(candidate)
                        if trade:
                            result["executed"].append(trade)
                            trades_placed += 1
        except Exception as e:
            logger.error("Resolution sniper error: %s", e, exc_info=True)
            result["errors"].append(f"sniper: {e}")

        # ── Strategy 2: LLM Superforecaster ─────────────────────────
        forecaster_cfg = self.config.get("polymarket", {}).get("forecaster", {})
        if not forecaster_cfg.get("enabled", True):
            logger.debug("Superforecaster disabled in config")
        else:
          try:
            div_candidates = await self.superforecaster.find_candidates(markets)
            result["divergence_candidates"] = div_candidates[:5]

            if execute:
                can_trade, reason = self.risk.can_trade()
                trades_placed = sum(1 for t in result["executed"])
                if can_trade:
                    for candidate in div_candidates:
                        if trades_placed >= max_trades:
                            break
                        if candidate.get("size_usdc", 0) < 1.0:
                            continue

                        approved, msg = self.risk.validate_trade(
                            "superforecaster",
                            candidate["size_usdc"],
                            candidate["entry_price"],
                            candidate["market_id"],
                        )
                        if not approved:
                            logger.info("Divergence trade rejected: %s", msg)
                            continue

                        trade = await self.superforecaster.execute(candidate)
                        if trade:
                            result["executed"].append(trade)
                            trades_placed += 1
          except Exception as e:
            logger.error("Superforecaster error: %s", e, exc_info=True)
            result["errors"].append(f"superforecaster: {e}")

        # ── Re-evaluate existing superforecaster positions ──────────
        if execute and forecaster_cfg.get("enabled", True):
            try:
                flips = await self.superforecaster.re_evaluate_positions()
                for flip in flips:
                    self.risk.record_pnl(flip.get("pnl", 0))
                    result["exits"].append(flip)
            except Exception as e:
                logger.error("Re-evaluation error: %s", e)

        # ── Strategy 3: Max Concurrent ─────────────────────────────
        mc_cfg = self.config.get("polymarket", {}).get("max_concurrent", {})
        if mc_cfg.get("enabled", False):
            try:
                mc_candidates = await self.max_concurrent_strategy.find_candidates(markets)
                result["mc_candidates"] = mc_candidates[:10]

                if execute:
                    can_trade, reason = self.risk.can_trade(strategy="max_concurrent")
                    trades_placed = sum(1 for t in result["executed"])
                    mc_max = mc_cfg.get("max_trades_per_cycle", 20)
                    if can_trade:
                        mc_trades = 0
                        for candidate in mc_candidates:
                            if mc_trades >= mc_max:
                                break
                            if candidate.get("size_usdc", 0) < 0.50:
                                continue

                            approved, msg = self.risk.validate_trade(
                                "max_concurrent",
                                candidate["size_usdc"],
                                candidate["entry_price"],
                                candidate["market_id"],
                            )
                            if not approved:
                                logger.info("MC trade rejected: %s", msg)
                                continue

                            trade = await self.max_concurrent_strategy.execute(candidate)
                            if trade:
                                result["executed"].append(trade)
                                mc_trades += 1
            except Exception as e:
                logger.error("Max concurrent error: %s", e, exc_info=True)
                result["errors"].append(f"max_concurrent: {e}")

        self.last_scan = result
        self.last_scan_time = time.time()

        logger.info(
            "Cycle %d complete: %d markets, %d snipes, %d divergences, %d mc, %d executed, %d exits",
            self.cycle, len(markets),
            len(result["snipe_candidates"]),
            len(result["divergence_candidates"]),
            len(result["mc_candidates"]),
            len(result["executed"]),
            len(result["exits"]),
        )

        # ── Discord notifications ─────────────────────────────────
        if self._bot:
            try:
                for claim in result.get("claims", []):
                    await self._bot.post_poly_claim(claim)
                for trade in result.get("executed", []):
                    await self._bot.post_poly_trade(trade)
                for exit_info in result.get("exits", []):
                    await self._bot.post_poly_exit(exit_info)
                if execute and (result.get("executed") or result.get("exits")):
                    await self._bot.post_poly_scan_summary(result)
            except Exception as e:
                logger.error("Discord notification error: %s", e)

        # ── Agent post-cycle hook ─────────────────────────────
        if hasattr(self, '_agent') and self._agent:
            try:
                await self._agent.post_cycle_hook(result)
            except Exception as e:
                logger.debug("Agent post-cycle hook: %s", e)

        return result

    def _run_claim_sync(self) -> list:
        """Run the async claimer in a thread-safe way (web3 is synchronous)."""
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(
                self.claimer.claim_resolved_positions(self.positions)
            )
        finally:
            loop.close()

    async def _check_exits(self) -> List[Dict]:
        """Check all open positions for exit conditions."""
        exits = []
        open_positions = self.positions.get_open_positions()

        for key, pos in open_positions.items():
            try:
                # Get current price
                mid = self.client.get_midpoint(pos.token_id)
                if mid <= 0:
                    continue

                if pos.strategy == "resolution_snipe":
                    result = await self.sniper.check_and_exit(key, mid)
                elif pos.strategy == "superforecaster":
                    # For superforecaster, we need the YES price
                    if pos.direction == "YES":
                        yes_price = mid
                    else:
                        yes_price = 1 - mid
                    result = await self.superforecaster.check_and_exit(key, yes_price)
                elif pos.strategy == "max_concurrent":
                    if pos.direction == "YES":
                        yes_price = mid
                    else:
                        yes_price = 1 - mid
                    result = await self.max_concurrent_strategy.check_and_exit(key, yes_price)
                elif pos.strategy == "turbo":
                    # Turbo handles its own exits in its fast loop
                    continue
                else:
                    continue

                if result:
                    self.risk.record_pnl(result.get("pnl", 0))
                    exits.append(result)
            except Exception as e:
                logger.error("Exit check failed for %s: %s", key, e)

        return exits

    # ── On-demand methods (called by Discord commands) ───────────────

    async def force_scan(self) -> Dict:
        """Read-only scan — no execution (triggered by /poly_scan)."""
        return await self._scan_cycle(execute=False)

    async def force_execute(self, max_trades: int = 4) -> Dict:
        """Scan and execute immediately (triggered by /poly_go)."""
        return await self._scan_cycle(execute=True, max_trades=max_trades)

    def get_status(self) -> Dict:
        """Get orchestrator status for /poly_status."""
        risk_status = self.risk.get_status()
        forecast_stats = self.forecaster.get_forecast_stats()

        mc_count = len(self.positions.get_positions_by_strategy("max_concurrent"))
        turbo_status = self.turbo.get_status()
        return {
            "running": self.is_running,
            "cycle": self.cycle,
            "last_scan_age": (
                f"{(time.time() - self.last_scan_time) / 60:.0f}min"
                if self.last_scan_time > 0 else "never"
            ),
            **risk_status,
            "mc_positions": mc_count,
            "mc_budget": self.max_concurrent_strategy.budget,
            "turbo": turbo_status,
            "forecast_stats": forecast_stats,
        }
