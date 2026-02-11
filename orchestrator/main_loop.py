"""
Strategy orchestrator: the main async loop that runs the full pipeline.

Every ``prediction_interval_minutes`` minutes:
  1. Fetch data for each instrument + context assets
  2. Run LaT-PFN prediction
  3. Generate trading signals
  4. Validate through risk manager
  5. Execute via webhook (PickMyTrade) or Tradovate API
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
from signals.shot_classifier import nearest_tier_above
from signals.confidence import score_confidence
from risk.manager import RiskManager
from risk.apex_compliance import ApexCompliance
from execution.order_manager import OrderManager, Position
from monitoring import dashboard
from monitoring.logger import setup_logging

logger = logging.getLogger(__name__)


def _create_executor(config: dict):
    """Instantiate the execution client based on config['execution']['mode']."""
    mode = config.get("execution", {}).get("mode", "dry_run")

    if mode == "pickmytrade":
        from execution.webhook_client import WebhookClient
        logger.info("Execution mode: PickMyTrade webhook")
        return WebhookClient(config)
    elif mode == "tradovate":
        from execution.tradovate_client import TradovateClient
        logger.info("Execution mode: Tradovate direct API")
        return TradovateClient(config)
    else:
        logger.info("Execution mode: dry_run (predictions only)")
        return None


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
        self.apex = ApexCompliance(config)
        self.executor = _create_executor(config)
        self.order_mgr = OrderManager()

        # State
        self.cycle = 0
        self.account_equity = config.get("execution", {}).get(
            "default_equity", 50000
        )
        self.is_running = False

        # Confirmation mode: require Discord approval before executing
        # Required for PA/Live accounts per Apex rules
        self.confirmation_mode = config.get("execution", {}).get(
            "confirmation_mode", False
        )

        # Contract symbol cache (root → active contract)
        self._contract_cache: dict[str, str] = {}

        # Discord bot (set externally by discord_bot.runner)
        self.discord_bot = None

    async def start(self):
        """Initialize connections and run the main loop."""
        setup_logging(self.config)
        dashboard.print_header(self.config)

        # Connect executor
        if self.executor:
            try:
                await self.executor.connect()
                balance = await self.executor.get_cash_balance()
                if balance > 0:
                    self.account_equity = balance
                self.risk_mgr.set_account_state(
                    starting_equity=self.account_equity,
                    current_equity=self.account_equity,
                    realized_pnl_today=0.0,
                )
                logger.info("Account equity: $%.2f", self.account_equity)
            except Exception as e:
                logger.error("Failed to connect executor: %s", e)
                logger.info("Running in prediction-only mode (no execution)")
                self.executor = None
        else:
            # dry_run mode — still initialize risk manager with default equity
            self.risk_mgr.set_account_state(
                starting_equity=self.account_equity,
                current_equity=self.account_equity,
                realized_pnl_today=0.0,
            )
            logger.info("Dry-run mode — equity: $%.2f", self.account_equity)

        # Resolve contract symbols (only needed for direct Tradovate API)
        if self.executor and hasattr(self.executor, 'find_contract'):
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

            # Apex hard flatten at 4:55 PM ET
            if self.apex.should_flatten_now():
                if self.order_mgr.open_count > 0:
                    logger.warning("APEX FLATTEN: 4:55 PM ET — closing all positions")
                    if self.executor:
                        try:
                            await self.executor.flatten_position()
                        except Exception as e:
                            logger.error("Flatten failed: %s", e)
                    self.order_mgr.close_all()
                    if self.discord_bot:
                        try:
                            await self.discord_bot._signal_channel.send(
                                "@here **APEX AUTO-FLATTEN** — All positions closed (4:55 PM ET cutoff)"
                            )
                        except Exception:
                            pass
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

            # Update trailing drawdown tracking
            dd_status = self.apex.update_balance(self.account_equity)
            if dd_status["at_risk"]:
                logger.warning(
                    "DRAWDOWN WARNING: cushion $%.2f (%.0f%%) — floor $%,.2f",
                    dd_status["cushion"], dd_status["cushion_pct"], dd_status["drawdown_floor"],
                )

            # Dashboard update
            dashboard.print_cycle_summary(
                cycle=self.cycle,
                predictions=predictions,
                positions=self.order_mgr.open_positions,
                account_equity=self.account_equity,
                daily_pnl=self.order_mgr.realized_pnl_today,
            )

            # Discord cycle summary (with drawdown status)
            if self.discord_bot:
                try:
                    await self.discord_bot.post_cycle_summary(
                        cycle=self.cycle,
                        predictions=predictions,
                        positions=self.order_mgr.open_positions,
                        account_equity=self.account_equity,
                        daily_pnl=self.order_mgr.realized_pnl_today,
                        drawdown_status=dd_status,
                    )
                except Exception:
                    pass

            # Discord radar — instruments approaching trade thresholds
            if self.discord_bot:
                try:
                    radar_items = self._build_radar(predictions)
                    if radar_items:
                        await self.discord_bot.post_radar(radar_items)
                except Exception:
                    pass

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
            # Notify Discord of rejection
            if self.discord_bot and signal is not None:
                try:
                    await self.discord_bot.post_risk_rejection(instrument, reason)
                except Exception:
                    pass
            return prediction

        # 5b. Apex compliance checks (5:1 R:R, MAE, correlated instruments, time)
        inst_cfg = self.config["instruments"][instrument]
        apex_ok, apex_reason = self.apex.check_all(
            instrument=instrument,
            direction=signal.direction,
            entry_price=signal.entry_price,
            stop_price=signal.stop_loss,
            target_price=signal.take_profit,
            position_size=signal.position_size,
            contract_size=inst_cfg["contract_size"],
            open_positions=self.order_mgr.open_positions,
        )
        if not apex_ok:
            logger.warning("APEX COMPLIANCE BLOCK %s: %s", instrument, apex_reason)
            dashboard.print_risk_decision(instrument, False, apex_reason)
            if self.discord_bot:
                try:
                    await self.discord_bot.post_risk_rejection(instrument, f"[APEX] {apex_reason}")
                except Exception:
                    pass
            return prediction

        # 5c. Confirmation mode — require Discord approval (PA/Live accounts)
        if self.confirmation_mode and self.discord_bot and self.discord_bot._signal_channel:
            from discord_bot.confirmation import request_confirmation
            timeout = self.config.get("execution", {}).get("confirmation_timeout", 60)
            confirmed = await request_confirmation(
                channel=self.discord_bot._signal_channel,
                instrument=instrument,
                signal=signal,
                prediction=prediction,
                timeout_seconds=timeout,
                alert_role_id=self.discord_bot.alert_role_id or None,
            )
            if not confirmed:
                logger.info("%s: trade not confirmed via Discord", instrument)
                return prediction
        else:
            # Auto-execution mode — still notify Discord of the signal
            if self.discord_bot:
                try:
                    await self.discord_bot.post_signal(instrument, signal, prediction)
                except Exception:
                    pass

        # 6. Execute (if executor is available)
        if not self.executor:
            logger.info("%s: signal approved but no executor (dry_run)", instrument)
            return prediction

        # Resolve symbol: use contract cache if available, else root symbol
        exec_symbol = self._contract_cache.get(
            instrument,
            self.config["instruments"][instrument]["tradovate_symbol"],
        )

        result = await self.executor.place_bracket_order(
            symbol=exec_symbol,
            direction=signal.direction,
            quantity=signal.position_size,
            entry_price=signal.entry_price,
            stop_price=signal.stop_loss,
            target_price=signal.take_profit,
        )

        dashboard.print_order_result(instrument, result)

        # Notify Discord of execution result
        if self.discord_bot:
            try:
                await self.discord_bot.post_execution(instrument, result, signal)
            except Exception:
                pass

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

    def _build_radar(self, predictions: dict) -> list:
        """
        Check predictions for instruments approaching a trade threshold.

        Returns list of radar items for instruments that are:
        - Non-neutral direction
        - Below the lowest enabled tier BUT within 75% of its threshold
        """
        tiers_config = self.config.get("shot_tiers", {})
        radar_items = []

        for inst, pred in predictions.items():
            if pred is None or pred["direction"] == "neutral":
                continue

            # Compute composite confidence (same as signal generator)
            confidence = score_confidence(
                model_confidence=pred["confidence"],
                forecast=pred["forecast_prices"],
                uncertainty=pred["uncertainty"],
                current_price=pred["current_price"],
                regime=pred["regime"],
                signal_config=self.config["signal"],
            )

            # Find nearest tier above this confidence
            tier_name, threshold = nearest_tier_above(confidence, tiers_config)
            if not tier_name or threshold <= 0:
                continue  # already in a tier (signal was generated) or no tiers

            # Only show on radar if within 75% of threshold (not too far away)
            progress = confidence / threshold
            if progress < 0.60:
                continue  # too far from triggering

            forecast_prices = pred.get("forecast_prices", [])
            forecast_end = forecast_prices[-1] if len(forecast_prices) > 0 else pred["current_price"]

            radar_items.append({
                "instrument": inst,
                "direction": pred["direction"],
                "confidence": confidence,
                "nearest_tier": tier_name,
                "tier_threshold": threshold,
                "regime": pred["regime"],
                "current_price": pred["current_price"],
                "forecast_end": forecast_end,
            })

        return radar_items

    async def _resolve_contracts(self):
        """Look up active front-month contract for each instrument."""
        for instrument in self.instruments:
            tv_symbol = self.config["instruments"][instrument]["tradovate_symbol"]
            try:
                contract = await self.executor.find_contract(tv_symbol)
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
        # Weekday check (Mon=0, Sun=6) — futures closed Sat, open Sun evening
        if now.weekday() == 5:  # Saturday
            return False
        t = now.time()
        if start <= end:
            # Same-day window (e.g. 09:30–16:00)
            return start <= t <= end
        else:
            # Overnight window (e.g. 18:00–17:00 wraps past midnight)
            return t >= start or t <= end

    async def shutdown(self):
        """Graceful shutdown."""
        logger.info("Shutting down trading system...")
        self.is_running = False

        # Flatten positions if configured and executor available
        if self.executor and self.config["schedule"].get("flatten_eod"):
            try:
                await self.executor.flatten_position()
                logger.info("All positions flattened")
            except Exception as e:
                logger.error("Failed to flatten positions: %s", e)

        if self.executor:
            await self.executor.disconnect()
        logger.info("Shutdown complete")
