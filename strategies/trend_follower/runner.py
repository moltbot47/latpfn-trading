"""Trend follower runner — 5-second polling loop with TradersPost execution.

Two loops in one:
  - Slow (5 min): fetch OHLCV bars, compute indicators, scan for Donchian breakout entries
  - Fast (5 sec): poll current prices, manage ATR trailing stops, execute exits

Usage:
    python -m strategies.trend_follower.runner
    python -m strategies.trend_follower.runner --dry-run
"""

import asyncio
import json
import logging
import os
import signal as _signal
import sys
import time
from datetime import datetime, time as dtime
from pathlib import Path

import yaml

# Ensure project root on sys.path for standalone execution
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from strategies.trend_follower.price_feed import PriceFeed  # noqa: E402
from strategies.trend_follower.strategy import TrendStrategy  # noqa: E402
from strategies.trend_follower.trail_manager import TrailManager, TrailState  # noqa: E402
from execution.traderspost_client import TradersPostClient  # noqa: E402
from risk.apex_compliance import ApexCompliance  # noqa: E402

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo  # type: ignore[no-redef]

try:
    from polymarket.platform_emitter import get_emitter
except ImportError:
    get_emitter = None  # type: ignore[assignment]

logger = logging.getLogger("trend_follower")

ET = ZoneInfo("America/New_York")
FLATTEN_TIME = dtime(16, 55)
NO_NEW_TRADES = dtime(16, 45)
MARKET_CLOSE = dtime(17, 0)
MARKET_REOPEN = dtime(18, 0)


class TrendFollowerRunner:
    """Main runner for the trend-following strategy.

    Slow loop (5 min): fetch bars → compute indicators → scan for entries.
    Fast loop (5 sec): poll prices → manage trailing stops → execute exits.
    """

    def __init__(self, config: dict, dry_run: bool = False):
        self.config = config
        self.dry_run = dry_run
        tf_cfg = config.get("trend_follower", {})

        # Instruments
        self.instruments = tf_cfg.get("instruments", ["MNQ", "MYM", "MES", "MBT"])

        # Components
        self.strategy = TrendStrategy(config)
        self.trail_mgr = TrailManager(
            trail_multiplier=tf_cfg.get("trail_atr_multiplier", 3.0)
        )
        self.price_feed = PriceFeed(self.instruments)
        self.executor = TradersPostClient(config)
        self.apex = ApexCompliance(config)

        # Timing
        self.scan_interval = tf_cfg.get("scan_interval_seconds", 300)
        self.poll_interval = tf_cfg.get("poll_interval_seconds", 5)

        # State
        self.running = False
        self.open_positions: dict[str, dict] = {}
        self.equity = config.get("execution", {}).get("default_equity", 50000)
        self.realized_pnl_today = 0.0
        self._last_scan_time = 0.0
        self._last_heartbeat = 0.0
        self._today: str = ""

        # Agent platform emitter
        self.emitter = get_emitter() if get_emitter else None
        self.agent_name = "trend-follower-cme"

        # State persistence
        self.state_file = tf_cfg.get("state_file", "data/trend_positions.json")

        logger.info(
            "TrendFollower init: instruments=%s scan=%ds poll=%ds dry_run=%s",
            self.instruments,
            self.scan_interval,
            self.poll_interval,
            self.dry_run,
        )

    # ── Lifecycle ─────────────────────────────────────────────────

    async def start(self):
        """Start the trend follower."""
        self.running = True

        if not self.dry_run:
            await self.executor.connect()

        self._load_state()
        self.apex.load_drawdown_state()

        logger.info("=" * 60)
        logger.info("TREND FOLLOWER STARTED")
        logger.info("Mode: %s", "DRY RUN" if self.dry_run else "LIVE")
        logger.info("Instruments: %s", ", ".join(self.instruments))
        logger.info("Positions: %d open", len(self.open_positions))
        logger.info("=" * 60)

        if self.emitter:
            self.emitter.heartbeat()

        try:
            await self._main_loop()
        finally:
            if not self.dry_run:
                await self.executor.disconnect()
            self._save_state()

    async def stop(self):
        logger.info("Stopping trend follower...")
        self.running = False

    # ── Main loop ─────────────────────────────────────────────────

    async def _main_loop(self):
        while self.running:
            now = time.time()
            now_et = datetime.now(ET)
            t = now_et.time()

            # Daily P&L reset
            today_str = now_et.strftime("%Y-%m-%d")
            if today_str != self._today:
                if self._today:
                    logger.info(
                        "New trading day — resetting daily P&L (was $%.2f)",
                        self.realized_pnl_today,
                    )
                self._today = today_str
                self.realized_pnl_today = 0.0

            # Market closed (5:00–6:00 PM ET daily break)
            if MARKET_CLOSE <= t < MARKET_REOPEN:
                logger.debug("Market break — sleeping 60s")
                await asyncio.sleep(60)
                continue

            # EOD flatten at 4:55 PM ET
            if FLATTEN_TIME <= t < MARKET_CLOSE and self.open_positions:
                await self._flatten_all("EOD flatten 4:55 PM ET")
                await asyncio.sleep(60)
                continue

            # Slow cycle: scan for entries
            if now - self._last_scan_time >= self.scan_interval:
                await self._scan_cycle()
                self._last_scan_time = now

            # Fast cycle: manage trailing stops
            if self.open_positions:
                await self._trail_cycle()

            # Heartbeat every 60s
            if self.emitter and now - self._last_heartbeat >= 60:
                self.emitter.heartbeat()
                self._last_heartbeat = now

            await asyncio.sleep(self.poll_interval)

    # ── Scan cycle (entries) ──────────────────────────────────────

    async def _scan_cycle(self):
        logger.info("--- Scan cycle (%d open positions) ---", len(self.open_positions))

        t = datetime.now(ET).time()
        if t >= NO_NEW_TRADES:
            logger.info("No new trades after 4:45 PM ET")
            return

        # Max concurrent positions
        max_positions = self.config.get("risk", {}).get("max_concurrent_positions", 6)
        if len(self.open_positions) >= max_positions:
            logger.info("At max positions (%d) — skipping scan", max_positions)
            return

        bars_dict = self.price_feed.full_bars(days=5, interval="5m")

        for inst in self.instruments:
            if inst in self.open_positions:
                continue
            if len(self.open_positions) >= max_positions:
                break

            bars = bars_dict.get(inst)
            if bars is None or bars.empty:
                continue

            signal = self.strategy.scan(inst, bars)
            if signal is None:
                if self.emitter:
                    self.emitter.signal_check(inst, "5m", None, None, "no_breakout")
                continue

            # Apex compliance
            inst_cfg = self.config.get("instruments", {}).get(inst, {})
            contract_size = inst_cfg.get("contract_size", 1.0)
            target_price = (
                signal.entry_price + 3 * signal.atr
                if signal.direction == "long"
                else signal.entry_price - 3 * signal.atr
            )
            ok, reason = self.apex.check_all(
                instrument=inst,
                direction=signal.direction,
                entry_price=signal.entry_price,
                stop_price=signal.stop_price,
                target_price=target_price,
                position_size=1,
                contract_size=contract_size,
                open_positions=self._positions_for_apex(),
            )
            if not ok:
                logger.info("Apex blocked %s %s: %s", signal.direction, inst, reason)
                continue

            # Size the position
            signal.position_size = self.strategy.size_position(
                signal, self.equity, contract_size
            )

            await self._enter_position(signal)

    # ── Trail cycle (exits) ───────────────────────────────────────

    async def _trail_cycle(self):
        snapshots = self.price_feed.snapshot()
        if not snapshots:
            return

        actions = self.trail_mgr.update_all(snapshots)

        for inst, action in actions:
            trail = self.trail_mgr.get_state(inst)
            snap = snapshots.get(inst)
            if not trail or not snap:
                continue

            if action == "stop_hit":
                logger.info(
                    "TRAIL STOP HIT: %s %s @ %.2f (stop=%.2f, best=%.2f, R=%.1f)",
                    trail.direction.upper(),
                    inst,
                    snap.price,
                    trail.current_stop,
                    trail.best_price,
                    trail.unrealized_r,
                )
                await self._exit_position(inst, snap.price, "trailing_stop")

            elif action == "scale_out":
                logger.info(
                    "SCALE OUT: %s %s @ %.2f (1.5R target=%.2f)",
                    trail.direction.upper(),
                    inst,
                    snap.price,
                    trail.scale_out_target,
                )
                if trail.current_size > 1:
                    exit_qty = trail.current_size // 2
                    trail.current_size -= exit_qty
                    trail.current_stop = trail.entry_price  # move stop to breakeven
                    await self._partial_exit(inst, snap.price, exit_qty, "scale_out")

    # ── Entry execution ───────────────────────────────────────────

    async def _enter_position(self, signal):
        logger.info(
            "ENTRY: %s %s %d @ %.2f  stop=%.2f  ATR=%.2f  ADX=%.1f  conf=%.2f",
            signal.direction.upper(),
            signal.instrument,
            signal.position_size,
            signal.entry_price,
            signal.stop_price,
            signal.atr,
            signal.adx,
            signal.confidence,
        )

        if not self.dry_run:
            # Wide TP — trailing stop handles actual exit
            wide_target = (
                signal.entry_price + 10 * signal.atr
                if signal.direction == "long"
                else signal.entry_price - 10 * signal.atr
            )
            result = await self.executor.place_bracket_order(
                symbol=signal.instrument,
                direction=signal.direction,
                quantity=signal.position_size,
                entry_price=signal.entry_price,
                stop_price=signal.stop_price,
                target_price=wide_target,
            )
            if result is None:
                logger.error("Entry execution failed for %s", signal.instrument)
                return

        # Track position
        self.open_positions[signal.instrument] = {
            "instrument": signal.instrument,
            "direction": signal.direction,
            "size": signal.position_size,
            "entry_price": signal.entry_price,
            "entry_time": time.time(),
            "atr": signal.atr,
        }

        # Set up trailing stop
        self.trail_mgr.add_trail(
            instrument=signal.instrument,
            direction=signal.direction,
            entry_price=signal.entry_price,
            atr=signal.atr,
            position_size=signal.position_size,
            stop_multiplier=self.strategy.stop_atr_mult,
        )

        self._save_state()

        # Emit to agent platform
        if self.emitter:
            inst_cfg = self.config.get("instruments", {}).get(signal.instrument, {})
            contract_size = inst_cfg.get("contract_size", 1.0)
            risk_usd = abs(signal.entry_price - signal.stop_price) * contract_size * signal.position_size
            self.emitter.strategy_trade(
                strategy=self.agent_name,
                question=f"{signal.direction.upper()} {signal.instrument} breakout",
                direction=signal.direction,
                entry_price=signal.entry_price,
                size_usdc=risk_usd,
                reason=f"Donchian breakout ADX={signal.adx:.1f} conf={signal.confidence:.2f}",
            )

    # ── Exit execution ────────────────────────────────────────────

    async def _exit_position(self, instrument: str, exit_price: float, reason: str):
        pos = self.open_positions.get(instrument)
        if not pos:
            return

        inst_cfg = self.config.get("instruments", {}).get(instrument, {})
        contract_size = inst_cfg.get("contract_size", 1.0)
        if pos["direction"] == "long":
            pnl = (exit_price - pos["entry_price"]) * contract_size * pos["size"]
        else:
            pnl = (pos["entry_price"] - exit_price) * contract_size * pos["size"]

        self.realized_pnl_today += pnl

        logger.info(
            "EXIT: %s %s @ %.2f -> %.2f  P&L=$%.2f  reason=%s  day_pnl=$%.2f",
            pos["direction"].upper(),
            instrument,
            pos["entry_price"],
            exit_price,
            pnl,
            reason,
            self.realized_pnl_today,
        )

        if not self.dry_run:
            await self.executor.close_position(instrument)

        del self.open_positions[instrument]
        self.trail_mgr.remove(instrument)
        self._save_state()

        self.equity += pnl
        self.apex.update_balance(self.equity)

        if self.emitter:
            self.emitter.strategy_exit(
                strategy=self.agent_name,
                question=f"{pos['direction'].upper()} {instrument}",
                pnl=pnl,
                reason=reason,
                exit_price=exit_price,
            )

    async def _partial_exit(
        self, instrument: str, price: float, qty: int, reason: str
    ):
        pos = self.open_positions.get(instrument)
        if not pos:
            return

        inst_cfg = self.config.get("instruments", {}).get(instrument, {})
        contract_size = inst_cfg.get("contract_size", 1.0)
        if pos["direction"] == "long":
            pnl = (price - pos["entry_price"]) * contract_size * qty
        else:
            pnl = (pos["entry_price"] - price) * contract_size * qty

        self.realized_pnl_today += pnl
        pos["size"] -= qty

        logger.info(
            "PARTIAL EXIT: %s %s %d @ %.2f  P&L=$%.2f  remaining=%d",
            pos["direction"].upper(),
            instrument,
            qty,
            price,
            pnl,
            pos["size"],
        )
        self._save_state()

    async def _flatten_all(self, reason: str):
        if not self.open_positions:
            return
        logger.info("FLATTEN ALL: %s (%d positions)", reason, len(self.open_positions))
        snapshots = self.price_feed.snapshot()
        for inst in list(self.open_positions.keys()):
            snap = snapshots.get(inst)
            price = snap.price if snap else self.open_positions[inst]["entry_price"]
            await self._exit_position(inst, price, reason)

        if self.apex.drawdown_type == "eod":
            self.apex.update_eod_balance(self.equity)

    # ── Helpers ───────────────────────────────────────────────────

    def _positions_for_apex(self):
        """Convert open positions to format expected by Apex compliance."""

        class _PosProxy:
            def __init__(self, direction):
                self.direction = direction

        return {
            inst: _PosProxy(pos["direction"])
            for inst, pos in self.open_positions.items()
        }

    def get_status(self) -> dict:
        """Return current strategy status for display."""
        trails = {}
        for inst, trail in self.trail_mgr.trails.items():
            trails[inst] = {
                "direction": trail.direction,
                "entry": trail.entry_price,
                "stop": trail.current_stop,
                "best": trail.best_price,
                "r_multiple": round(trail.unrealized_r, 2),
                "atr": trail.atr,
            }
        return {
            "agent": self.agent_name,
            "mode": "dry_run" if self.dry_run else "live",
            "instruments": self.instruments,
            "positions": len(self.open_positions),
            "equity": self.equity,
            "daily_pnl": self.realized_pnl_today,
            "trails": trails,
        }

    # ── State persistence ─────────────────────────────────────────

    def _save_state(self):
        try:
            d = os.path.dirname(self.state_file)
            if d:
                os.makedirs(d, exist_ok=True)
            tmp = self.state_file + ".tmp"
            with open(tmp, "w") as f:
                json.dump(
                    {
                        "positions": self.open_positions,
                        "trails": {
                            inst: t.to_dict()
                            for inst, t in self.trail_mgr.trails.items()
                        },
                        "equity": self.equity,
                        "realized_pnl_today": self.realized_pnl_today,
                        "updated": datetime.now().isoformat(),
                    },
                    f,
                    indent=2,
                )
            os.replace(tmp, self.state_file)
        except Exception as e:
            logger.error("Failed to save trend state: %s", e)

    def _load_state(self):
        if not os.path.exists(self.state_file):
            return
        try:
            with open(self.state_file) as f:
                state = json.load(f)

            self.open_positions = state.get("positions", {})
            self.equity = state.get("equity", self.equity)
            self.realized_pnl_today = state.get("realized_pnl_today", 0.0)

            for inst, td in state.get("trails", {}).items():
                self.trail_mgr.trails[inst] = TrailState.from_dict(td)

            logger.info(
                "State restored: %d positions, equity=$%,.2f",
                len(self.open_positions),
                self.equity,
            )
        except Exception as e:
            logger.error("Failed to load trend state: %s", e)


# ── Entry point ───────────────────────────────────────────────────


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Trend Follower Strategy")
    parser.add_argument("--dry-run", action="store_true", help="No live execution")
    parser.add_argument(
        "--config", default="config/settings.yaml", help="Config file path"
    )
    args = parser.parse_args()

    with open(args.config) as f:
        config = yaml.safe_load(f)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    runner = TrendFollowerRunner(config, dry_run=args.dry_run)

    loop = asyncio.new_event_loop()
    for sig in (_signal.SIGINT, _signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.ensure_future(runner.stop()))

    try:
        loop.run_until_complete(runner.start())
    except KeyboardInterrupt:
        loop.run_until_complete(runner.stop())
    finally:
        loop.close()


if __name__ == "__main__":
    main()
