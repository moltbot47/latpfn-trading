"""
Strategy orchestrator: the main async loop that runs the full pipeline.

Every ``prediction_interval_minutes`` minutes:
  1. Fetch data for each instrument + context assets
  2. Run LaT-PFN prediction
  3. Generate trading signals
  4. Validate through risk manager
  5. Execute via Tradovate
  6. Update dashboard
"""

import asyncio
import logging
from datetime import datetime, time as dtime

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

from config import load_config
from market_data.pipeline import DataPipeline
from forecaster.wrapper import LaTPFNPredictor
from signals.generator import SignalGenerator
from risk.manager import RiskManager
from execution.tradovate_client import TradovateClient
from execution.order_manager import OrderManager, Position
from monitoring import dashboard
from monitoring.logger import setup_logging

logger = logging.getLogger(__name__)


class TradingSystem:
    """Top-level trading system orchestrator."""

    def __init__(self, config: dict):
        self.config = config
        self.interval = config["schedule"]["prediction_interval_minutes"]
        self.instruments = list(config["instruments"].keys())

        # Components
        self.data_pipeline = DataPipeline(config)
        self.model = LaTPFNPredictor(config)
        self.signal_gen = SignalGenerator(config)
        self.risk_mgr = RiskManager(config)
        self.tradovate = TradovateClient(config)
        self.order_mgr = OrderManager()

        # State
        self.cycle = 0
        self.account_equity = 0.0
        self.is_running = False

        # Contract symbol cache (root → active contract)
        self._contract_cache: dict[str, str] = {}

    async def start(self):
        """Initialize connections and run the main loop."""
        setup_logging(self.config)
        dashboard.print_header(self.config)

        # Connect to Tradovate
        try:
            await self.tradovate.connect()
            self.account_equity = await self.tradovate.get_cash_balance()
            self.risk_mgr.set_account_state(
                starting_equity=self.account_equity,
                current_equity=self.account_equity,
                realized_pnl_today=0.0,
            )
            logger.info("Account equity: $%.2f", self.account_equity)
        except Exception as e:
            logger.error("Failed to connect to Tradovate: %s", e)
            logger.info("Running in prediction-only mode (no execution)")

        # Resolve contract symbols
        await self._resolve_contracts()

        # Main loop
        self.is_running = True
        try:
            await self._main_loop()
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received")
        finally:
            await self.shutdown()

    async def _main_loop(self):
        while self.is_running:
            if not self._is_market_hours():
                logger.debug("Outside market hours, sleeping 60s")
                await asyncio.sleep(60)
                continue

            self.cycle += 1
            predictions = {}

            for instrument in self.instruments:
                try:
                    pred = await self._process_instrument(instrument)
                    predictions[instrument] = pred
                except Exception as e:
                    logger.error("Error processing %s: %s", instrument, e, exc_info=True)
                    predictions[instrument] = None

            # Dashboard update
            dashboard.print_cycle_summary(
                cycle=self.cycle,
                predictions=predictions,
                positions=self.order_mgr.open_positions,
                account_equity=self.account_equity,
                daily_pnl=self.order_mgr.realized_pnl_today,
            )

            # Wait for next cycle
            logger.info("Next cycle in %d minutes", self.interval)
            await asyncio.sleep(self.interval * 60)

    async def _process_instrument(self, instrument: str) -> dict | None:
        """Full pipeline for one instrument."""
        # 1. Skip if we already have a position
        if self.order_mgr.has_position(instrument):
            logger.info("%s: position already open, skipping", instrument)
            return None

        # 2. Fetch data
        data = self.data_pipeline.get_prediction_data(instrument)

        if len(data["heldout_df"]) < data["n_history"] + data["n_prompt"]:
            logger.warning("%s: insufficient data, skipping", instrument)
            return None

        # 3. Predict
        prediction = self.model.predict(
            heldout_df=data["heldout_df"],
            context_dfs=data["context_dfs"],
        )

        logger.info(
            "%s: direction=%s  confidence=%.3f  regime=%s",
            instrument, prediction["direction"],
            prediction["confidence"], prediction["regime"],
        )

        # 4. Generate signal (includes NBA shot-tier classification)
        signal = self.signal_gen.generate(instrument, prediction)
        dashboard.print_signal(instrument, signal)

        # Annotate prediction with shot type for dashboard display
        if signal is not None:
            prediction["shot_type"] = signal.shot_type
        else:
            prediction["shot_type"] = ""

        if signal is None:
            return prediction

        # 5. Risk validation
        approved, signal, reason = self.risk_mgr.validate(
            signal, self.order_mgr.open_count
        )
        dashboard.print_risk_decision(instrument, approved, reason)

        if not approved or signal is None:
            return prediction

        # 6. Execute
        contract_symbol = self._contract_cache.get(instrument)
        if not contract_symbol:
            logger.error("%s: no contract symbol resolved", instrument)
            return prediction

        result = await self.tradovate.place_bracket_order(
            symbol=contract_symbol,
            direction=signal.direction,
            quantity=signal.position_size,
            entry_price=signal.entry_price,
            stop_price=signal.stop_loss,
            target_price=signal.take_profit,
        )

        dashboard.print_order_result(instrument, result)

        if result and "orderId" in result:
            self.order_mgr.add_position(Position(
                instrument=instrument,
                direction=signal.direction,
                size=signal.position_size,
                entry_price=signal.entry_price,
                stop_loss=signal.stop_loss,
                take_profit=signal.take_profit,
                order_id=result["orderId"],
            ))

        return prediction

    async def _resolve_contracts(self):
        """Look up active front-month contract for each instrument."""
        for instrument in self.instruments:
            tv_symbol = self.config["instruments"][instrument]["tradovate_symbol"]
            try:
                contract = await self.tradovate.find_contract(tv_symbol)
                if contract:
                    self._contract_cache[instrument] = contract
                    logger.info("%s → %s", instrument, contract)
                else:
                    logger.warning("Could not resolve contract for %s", instrument)
            except Exception as e:
                logger.warning("Contract lookup failed for %s: %s", instrument, e)

    def _is_market_hours(self) -> bool:
        """Check if we're within configured trading hours (timezone-aware)."""
        schedule = self.config["schedule"]["market_hours"]
        tz_name = schedule.get("timezone", "America/New_York")
        tz = ZoneInfo(tz_name)
        now = datetime.now(tz)
        start = dtime.fromisoformat(schedule["start"])
        end = dtime.fromisoformat(schedule["end"])
        # Weekday check (Mon=0, Fri=4)
        if now.weekday() > 4:
            return False
        return start <= now.time() <= end

    async def shutdown(self):
        """Graceful shutdown."""
        logger.info("Shutting down trading system...")
        self.is_running = False

        # Flatten positions if configured
        if self.config["schedule"].get("flatten_eod"):
            try:
                await self.tradovate.flatten_position()
                logger.info("All positions flattened")
            except Exception as e:
                logger.error("Failed to flatten positions: %s", e)

        await self.tradovate.disconnect()
        logger.info("Shutdown complete")
