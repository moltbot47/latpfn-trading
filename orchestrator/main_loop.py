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
import json
import logging
import os
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
from signals.regime import detect_regime
from risk.manager import RiskManager
from risk.apex_compliance import ApexCompliance
from risk.portfolio_exposure import check_exposure_limit, portfolio_exposure
from execution.order_manager import OrderManager, Position
from monitoring import dashboard
from monitoring.logger import setup_logging
from monitoring.trade_logger import TradeLogger
from monitoring.position_monitor import check_position_exits
from signals.signal_ranker import rank_signals
from monitoring.profit_manager import check_profit_actions

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
        self.trade_logger = TradeLogger()
        self.order_mgr = OrderManager(trade_logger=self.trade_logger)

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
        self._discord_fail_count = 0

        # Daily P&L auto-reset tracking
        self._current_trading_date = None

    async def start(self):
        """Initialize connections and run the main loop."""
        setup_logging(self.config)
        dashboard.print_header(self.config)

        # Restore any persisted positions from a previous run
        self.order_mgr.load_state()

        # Restore system state (cycle number) from a previous run
        self._restore_system_state()

        # Restore drawdown floor from previous run (BEFORE main loop, AFTER ApexCompliance init)
        self.apex.load_drawdown_state()

        # Connect executor
        if self.executor:
            try:
                await self.executor.connect()
                balance = await self.executor.get_cash_balance()
                if balance > 0:
                    self.account_equity = balance
                dd_init = self.apex.get_drawdown_status(self.account_equity)
                self.risk_mgr.set_account_state(
                    starting_equity=self.account_equity,
                    current_equity=self.account_equity,
                    realized_pnl_today=0.0,
                    drawdown_cushion=dd_init["cushion"],
                    max_drawdown=self.apex.trailing_drawdown_amount,
                )
                logger.info("Account equity: $%.2f", self.account_equity)
            except Exception as e:
                logger.error("Failed to connect executor: %s", e)
                logger.info("Running in prediction-only mode (no execution)")
                self.executor = None
        else:
            # dry_run mode — still initialize risk manager with default equity
            dd_init = self.apex.get_drawdown_status(self.account_equity)
            self.risk_mgr.set_account_state(
                starting_equity=self.account_equity,
                current_equity=self.account_equity,
                realized_pnl_today=0.0,
                drawdown_cushion=dd_init["cushion"],
                max_drawdown=self.apex.trailing_drawdown_amount,
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
                            result = await self.executor.flatten_position()
                            if result is None:
                                logger.warning(
                                    "Flatten webhook returned None — broker may not have received flatten. "
                                    "Proceeding with local close_all since this is an emergency flatten."
                                )
                        except Exception as e:
                            logger.error("Flatten failed: %s", e)
                    self.order_mgr.close_all()
                    if self.discord_bot:
                        try:
                            await self.discord_bot._signal_channel.send(
                                "@here **APEX AUTO-FLATTEN** — All positions closed (4:55 PM ET cutoff)"
                            )
                            self._discord_fail_count = 0
                        except Exception as e:
                            self._discord_fail_count += 1
                            if self._discord_fail_count <= 3:
                                logger.warning("Discord post failed (%d): %s", self._discord_fail_count, e)
                            elif self._discord_fail_count == 4:
                                logger.error("Discord appears disconnected — alerts not being delivered")
                await asyncio.sleep(60)
                continue

            self.cycle += 1
            self._write_heartbeat("cycle_start")
            predictions = {}

            # Daily P&L auto-reset
            tz_name = self.config["schedule"]["market_hours"].get("timezone", "America/New_York")
            tz = ZoneInfo(tz_name)
            today = datetime.now(tz).date()
            if self._current_trading_date is not None and today != self._current_trading_date:
                logger.info("New trading day %s — resetting daily P&L", today)
                self.order_mgr.reset_daily_pnl()
            self._current_trading_date = today

            # Update trailing drawdown tracking BEFORE processing instruments
            # so the risk manager has the latest cushion data for sizing
            dd_status = self.apex.update_balance(self.account_equity)
            if dd_status["at_risk"]:
                logger.warning(
                    "DRAWDOWN WARNING: cushion $%.2f (%.0f%%) — floor $%,.2f",
                    dd_status["cushion"], dd_status["cushion_pct"], dd_status["drawdown_floor"],
                )

            # Feed drawdown cushion into risk manager for dynamic position sizing
            prop_cfg = self.config.get("risk", {}).get("prop_firm", {})
            self.risk_mgr.set_account_state(
                starting_equity=self.account_equity,
                current_equity=self.account_equity,
                realized_pnl_today=self.order_mgr.realized_pnl_today,
                drawdown_cushion=dd_status["cushion"],
                max_drawdown=prop_cfg.get(
                    "max_total_drawdown_usd",
                    self.apex.trailing_drawdown_amount,
                ),
            )

            # ── Phase 0: Reconcile ghost positions ──
            # Detect positions closed at broker but still in local tracking
            if self.order_mgr.open_count > 0:
                await self._reconcile_positions()

            # ── Phase 1: Scan all instruments for candidate signals ──
            candidates = []
            for instrument in self.instruments:
                try:
                    pred, candidate = await self._scan_instrument(instrument)
                    predictions[instrument] = pred
                    if candidate is not None:
                        candidates.append(candidate)
                except Exception as e:
                    logger.error("Error scanning %s: %s", instrument, e, exc_info=True)
                    predictions[instrument] = None

            # ── Phase 2: Rank candidates and execute the best ones ──
            max_pos = self.config["risk"].get("max_concurrent_positions", 6)
            available_slots = max_pos - self.order_mgr.open_count
            ranked = []
            if candidates and available_slots > 0:
                ranked = rank_signals(
                    candidates=candidates,
                    open_positions=self.order_mgr.open_positions,
                    available_slots=available_slots,
                )
                for cand in ranked:
                    try:
                        await self._execute_signal(
                            instrument=cand["instrument"],
                            signal=cand["signal"],
                            prediction=cand["prediction"],
                            pred_id=cand["pred_id"],
                        )
                    except Exception as e:
                        logger.error(
                            "Error executing %s: %s", cand["instrument"], e, exc_info=True
                        )
            elif candidates:
                logger.info(
                    "All %d position slots full — %d candidate signals skipped",
                    max_pos, len(candidates),
                )

            # ── Phase 3a: Auto profit-taking on open positions ──
            # Uses yfinance delayed data (~10-15 min). Closes at 90%+ TP,
            # notifies at 75%+ TP to tighten stop (can't modify via webhook).
            if self.order_mgr.open_count > 0:
                try:
                    # Build pending signals list for slot-freeing logic
                    ranked_insts = {c["instrument"] for c in ranked}
                    overflow = [c for c in candidates if c["instrument"] not in ranked_insts]
                    pending_for_slots = [
                        {"instrument": c["instrument"], "composite_score": c.get("rank_score", 0)}
                        for c in overflow
                    ] if overflow else None

                    strategy_mode = self.config.get("strategy", {}).get("mode", "standard")
                    scalp_cfg = self.config.get("strategy", {}).get("scalp", {})
                    profit_actions = check_profit_actions(
                        open_positions=self.order_mgr.open_positions,
                        instruments_config=self.config["instruments"],
                        pending_signals=pending_for_slots,
                        strategy_mode=strategy_mode,
                        scalp_config=scalp_cfg if strategy_mode == "scalp" else None,
                    )
                    for pa in profit_actions:
                        inst = pa["instrument"]
                        inst_cfg = self.config["instruments"].get(inst, {})
                        cs = inst_cfg.get("contract_size", 1.0)

                        if pa["action"] == "close":
                            # Close via webhook + track locally
                            # Only remove position from local tracking if webhook succeeds
                            # (or if there's no executor — position monitor inferred exits)
                            webhook_ok = True
                            if self.executor:
                                exec_sym = self._contract_cache.get(inst, inst_cfg.get("tradovate_symbol", inst))
                                close_result = await self.executor.close_position(exec_sym)
                                if close_result is None:
                                    webhook_ok = False
                                    logger.error(
                                        "CLOSE WEBHOOK FAILED for %s — position NOT removed from tracking. "
                                        "Will retry next cycle.",
                                        inst,
                                    )

                            if not webhook_ok:
                                continue  # skip local close — retry next cycle

                            pnl = self.order_mgr.close_position(
                                instrument=inst,
                                exit_price=pa["current_price"],
                                contract_size=cs,
                                exit_reason="auto_profit",
                            )
                            self.apex.update_balance(self.account_equity + pnl)
                            logger.info(
                                "AUTO PROFIT-TAKE %s @ %.2f  Est P&L: $%.2f  (%s)",
                                inst, pa["current_price"], pnl, pa["reason"],
                            )
                            if self.discord_bot:
                                try:
                                    await self.discord_bot._signal_channel.send(
                                        f"\U0001F4B0 **AUTO PROFIT-TAKE** {inst} "
                                        f"@ {pa['current_price']:.2f}  |  "
                                        f"Est. P&L: ${pnl:+.2f}\n"
                                        f"*{pa['reason']}*"
                                    )
                                    self._discord_fail_count = 0
                                except Exception as e:
                                    self._discord_fail_count += 1
                                    if self._discord_fail_count <= 3:
                                        logger.warning("Discord post failed (%d): %s", self._discord_fail_count, e)
                                    elif self._discord_fail_count == 4:
                                        logger.error("Discord appears disconnected — alerts not being delivered")

                        elif pa["action"] == "trailing_stop_close":
                            # Trailing stop triggered — close via webhook
                            webhook_ok = True
                            if self.executor:
                                exec_sym = self._contract_cache.get(inst, inst_cfg.get("tradovate_symbol", inst))
                                close_result = await self.executor.close_position(exec_sym)
                                if close_result is None:
                                    webhook_ok = False
                                    logger.error(
                                        "TRAILING STOP CLOSE WEBHOOK FAILED for %s — will retry next cycle.",
                                        inst,
                                    )

                            if not webhook_ok:
                                continue

                            pnl = self.order_mgr.close_position(
                                instrument=inst,
                                exit_price=pa["current_price"],
                                contract_size=cs,
                                exit_reason="trailing_stop",
                            )
                            self.apex.update_balance(self.account_equity + pnl)
                            logger.info(
                                "TRAILING STOP CLOSE %s @ %.2f  Est P&L: $%.2f  (%s)",
                                inst, pa["current_price"], pnl, pa["reason"],
                            )
                            if self.discord_bot:
                                try:
                                    await self.discord_bot._signal_channel.send(
                                        f"\U0001F3AF **TRAILING STOP** {inst} "
                                        f"@ {pa['current_price']:.2f}  |  "
                                        f"Est. P&L: ${pnl:+.2f}\n"
                                        f"*{pa['reason']}*"
                                    )
                                    self._discord_fail_count = 0
                                except Exception as e:
                                    self._discord_fail_count += 1
                                    if self._discord_fail_count <= 3:
                                        logger.warning("Discord post failed (%d): %s", self._discord_fail_count, e)

                        elif pa["action"] == "tighten_stop":
                            # Can't modify stops via PickMyTrade webhook —
                            # notify user and update local tracking only
                            pos = self.order_mgr.open_positions.get(inst)
                            if pos:
                                pos.stop_loss = pos.entry_price  # breakeven locally
                                self.order_mgr._save_state()
                            logger.info(
                                "TIGHTEN STOP %s → breakeven %.2f  (%s)",
                                inst, pa["current_price"], pa["reason"],
                            )
                            if self.discord_bot:
                                try:
                                    await self.discord_bot._signal_channel.send(
                                        f"\U0001F6E1 **TIGHTEN STOP** {inst} "
                                        f"→ Move stop to breakeven\n"
                                        f"*{pa['reason']}*\n"
                                        f"\u26A0\uFE0F *Manual action needed — "
                                        f"PickMyTrade cannot modify existing stops.*"
                                    )
                                    self._discord_fail_count = 0
                                except Exception as e:
                                    self._discord_fail_count += 1
                                    if self._discord_fail_count <= 3:
                                        logger.warning("Discord post failed (%d): %s", self._discord_fail_count, e)
                                    elif self._discord_fail_count == 4:
                                        logger.error("Discord appears disconnected — alerts not being delivered")
                    # Persist trailing stop state changes even when no close happened
                    if any(pa["action"] not in ("close", "trailing_stop_close") for pa in profit_actions):
                        self.order_mgr._save_state()
                except Exception as e:
                    logger.error("Profit-taking check failed: %s", e)

            # ── Phase 3b: Check open positions for inferred exits ──
            # Check open positions for inferred exits (price-based estimation)
            # NOTE: Only monitors executed positions — see position_monitor.py
            # for full accuracy disclaimers. Results are estimates, not confirmed fills.
            if self.order_mgr.open_count > 0:
                try:
                    inferred_exits = check_position_exits(
                        open_positions=self.order_mgr.open_positions,
                        instruments_config=self.config["instruments"],
                    )
                    for ex in inferred_exits:
                        inst = ex["instrument"]
                        pnl = self.order_mgr.close_position(
                            instrument=inst,
                            exit_price=ex["exit_price"],
                            contract_size=ex["contract_size"],
                            exit_reason=ex["exit_reason"],
                        )
                        # Update drawdown tracker with estimated P&L
                        self.apex.update_balance(self.account_equity + pnl)

                        # Discord notification
                        if self.discord_bot:
                            try:
                                await self.discord_bot._signal_channel.send(
                                    f"**{ex['exit_reason'].upper()}** {inst} "
                                    f"@ {ex['exit_price']:.2f}  |  "
                                    f"Est. P&L: ${pnl:+.2f}\n"
                                    f"*{ex['note']}*"
                                )
                                self._discord_fail_count = 0
                            except Exception as e:
                                self._discord_fail_count += 1
                                if self._discord_fail_count <= 3:
                                    logger.warning("Discord post failed (%d): %s", self._discord_fail_count, e)
                                elif self._discord_fail_count == 4:
                                    logger.error("Discord appears disconnected — alerts not being delivered")
                except Exception as e:
                    logger.error("Position exit check failed: %s", e)

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
                    self._discord_fail_count = 0
                except Exception as e:
                    self._discord_fail_count += 1
                    if self._discord_fail_count <= 3:
                        logger.warning("Discord post failed (%d): %s", self._discord_fail_count, e)
                    elif self._discord_fail_count == 4:
                        logger.error("Discord appears disconnected — alerts not being delivered")

            # Discord radar — instruments approaching trade thresholds
            if self.discord_bot:
                try:
                    radar_items = self._build_radar(predictions)
                    if radar_items:
                        await self.discord_bot.post_radar(radar_items)
                    self._discord_fail_count = 0
                except Exception as e:
                    self._discord_fail_count += 1
                    if self._discord_fail_count <= 3:
                        logger.warning("Discord post failed (%d): %s", self._discord_fail_count, e)
                    elif self._discord_fail_count == 4:
                        logger.error("Discord appears disconnected — alerts not being delivered")

            # Heartbeat at end of cycle
            self._write_heartbeat("cycle_end")

            # Check for stale positions (open > 24 hours)
            await self._check_stale_positions()

            # Wait for next cycle
            logger.info("Next cycle in %d minutes", self.interval)
            await asyncio.sleep(self.interval * 60)

    async def _scan_instrument(self, instrument: str) -> tuple:
        """
        Scan one instrument: fetch data, predict, generate signal.

        Returns:
            (prediction_dict_or_None, candidate_dict_or_None)
            candidate is non-None only if a valid signal was generated.
        """
        # Skip if we already have a position
        if self.order_mgr.has_position(instrument):
            logger.info("%s: position already open, skipping", instrument)
            return None, None

        # Fetch data
        data = self.data_pipeline.get_prediction_data(instrument)

        if len(data["heldout_df"]) < data["n_history"] + data["n_prompt"]:
            logger.warning("%s: insufficient data, skipping", instrument)
            return None, None

        # Predict
        prediction = self.model.predict(
            heldout_df=data["heldout_df"],
            context_dfs=data["context_dfs"],
        )

        logger.info(
            "%s: direction=%s  confidence=%.3f  regime=%s",
            instrument, prediction["direction"],
            prediction["confidence"], prediction["regime"],
        )

        # Market-based regime detection
        vix_df = data["context_dfs"].get("^VIX")
        market_regime = detect_regime(data["heldout_df"], vix_df)
        prediction["market_regime"] = market_regime
        logger.info(
            "%s: market_regime=%s  ADX=%.1f  vol_pctile=%.0f  vix=%s  size_mult=%.2f",
            instrument, market_regime["regime"], market_regime["adx"],
            market_regime["realized_vol_pctile"],
            f'{market_regime["vix_level"]:.1f}' if market_regime["vix_level"] else "N/A",
            market_regime["size_multiplier"],
        )

        # Generate signal (includes NBA shot-tier classification)
        signal = self.signal_gen.generate(instrument, prediction)
        dashboard.print_signal(instrument, signal)

        # EMA trend filter — reject counter-trend signals
        if signal is not None:
            trend_cfg = self.config.get("signal", {}).get("trend_filter", {})
            if trend_cfg.get("enabled", False):
                from signals.trend_filter import compute_trend_bias, check_trend_alignment

                close_prices = data["heldout_df"]["Close"].values
                trend_bias = compute_trend_bias(
                    close_prices,
                    fast_period=trend_cfg.get("fast_ema_period", 50),
                    slow_period=trend_cfg.get("slow_ema_period", 200),
                )
                allowed, reason = check_trend_alignment(signal.direction, trend_bias)
                logger.info(
                    "%s: EMA trend=%s  fast=%.2f  slow=%.2f  price=%.2f  signal=%s  %s",
                    instrument, trend_bias["bias"],
                    trend_bias["fast_ema"], trend_bias["slow_ema"],
                    close_prices[-1], signal.direction,
                    "ALLOWED" if allowed else f"BLOCKED ({reason})",
                )
                if not allowed:
                    signal = None

        # Attach market-based regime size multiplier
        if signal is not None:
            signal.regime_size_mult = market_regime["size_multiplier"]

        # Annotate prediction with shot type for dashboard
        prediction["shot_type"] = signal.shot_type if signal else ""

        # Log prediction to SQLite
        pred_id = self.trade_logger.log_prediction(
            cycle=self.cycle,
            instrument=instrument,
            prediction=prediction,
            composite_confidence=signal.confidence if signal else prediction.get("confidence", 0.0),
            shot_tier=signal.shot_type if signal else "no_trade",
            signal_generated=(signal is not None),
        )

        if signal is None:
            return prediction, None

        # Return as a candidate for ranking
        candidate = {
            "instrument": instrument,
            "signal": signal,
            "prediction": prediction,
            "market_regime": market_regime,
            "pred_id": pred_id,
        }
        return prediction, candidate

    async def _execute_signal(
        self, instrument: str, signal, prediction: dict, pred_id
    ):
        """
        Validate and execute a ranked signal.

        Called only for signals that passed ranking and have an available slot.
        """
        # Risk validation
        approved, signal, reason = self.risk_mgr.validate(
            signal,
            self.order_mgr.open_count,
            open_positions_dict=self.order_mgr.open_positions,
        )
        dashboard.print_risk_decision(instrument, approved, reason)

        if not approved or signal is None:
            if signal is not None:
                dd_status_now = self.apex.get_drawdown_status(self.account_equity)
                self.trade_logger.log_trade(
                    prediction_id=pred_id,
                    instrument=instrument,
                    signal=signal,
                    regime=prediction.get("regime", "unknown"),
                    drawdown_cushion=dd_status_now["cushion"],
                    effective_risk_pct=0.0,
                    execution_status="rejected",
                    rejection_reason=reason,
                )
            if self.discord_bot and signal is not None:
                try:
                    await self.discord_bot.post_risk_rejection(instrument, reason)
                    self._discord_fail_count = 0
                except Exception as e:
                    self._discord_fail_count += 1
                    if self._discord_fail_count <= 3:
                        logger.warning("Discord post failed (%d): %s", self._discord_fail_count, e)
                    elif self._discord_fail_count == 4:
                        logger.error("Discord appears disconnected — alerts not being delivered")
            return

        # Apex compliance
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
                    self._discord_fail_count = 0
                except Exception as e:
                    self._discord_fail_count += 1
                    if self._discord_fail_count <= 3:
                        logger.warning("Discord post failed (%d): %s", self._discord_fail_count, e)
                    elif self._discord_fail_count == 4:
                        logger.error("Discord appears disconnected — alerts not being delivered")
            return

        # Portfolio exposure check
        max_net = self.config.get("risk", {}).get("max_net_mes_equivalent", 6.0)
        max_gross = self.config.get("risk", {}).get("max_gross_mes_equivalent", 10.0)
        exp_ok, exp_reason = check_exposure_limit(
            open_positions=self.order_mgr.open_positions,
            instruments_config=self.config["instruments"],
            new_instrument=instrument,
            new_direction=signal.direction,
            new_quantity=signal.position_size,
            max_net_mes_eq=max_net,
            max_gross_mes_eq=max_gross,
        )
        if not exp_ok:
            logger.warning("PORTFOLIO EXPOSURE BLOCK %s: %s", instrument, exp_reason)
            dashboard.print_risk_decision(instrument, False, exp_reason)
            if self.discord_bot:
                try:
                    await self.discord_bot.post_risk_rejection(instrument, f"[EXPOSURE] {exp_reason}")
                    self._discord_fail_count = 0
                except Exception as e:
                    self._discord_fail_count += 1
                    if self._discord_fail_count <= 3:
                        logger.warning("Discord post failed (%d): %s", self._discord_fail_count, e)
                    elif self._discord_fail_count == 4:
                        logger.error("Discord appears disconnected — alerts not being delivered")
            return

        # Confirmation mode (PA/Live accounts)
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
                return
        else:
            if self.discord_bot:
                try:
                    await self.discord_bot.post_signal(instrument, signal, prediction)
                    self._discord_fail_count = 0
                except Exception as e:
                    self._discord_fail_count += 1
                    if self._discord_fail_count <= 3:
                        logger.warning("Discord post failed (%d): %s", self._discord_fail_count, e)
                    elif self._discord_fail_count == 4:
                        logger.error("Discord appears disconnected — alerts not being delivered")

        # Execute
        if not self.executor:
            logger.info("%s: signal approved but no executor (dry_run)", instrument)
            dd_status_now = self.apex.get_drawdown_status(self.account_equity)
            inst_cfg_log = self.config["instruments"][instrument]
            risk_pts = abs(signal.entry_price - signal.stop_loss)
            eff_risk_pct = (
                (risk_pts * inst_cfg_log["contract_size"] * signal.position_size)
                / self.account_equity * 100
            ) if self.account_equity > 0 else 0.0
            signal.contract_size = inst_cfg_log["contract_size"]
            self.trade_logger.log_trade(
                prediction_id=pred_id,
                instrument=instrument,
                signal=signal,
                regime=prediction.get("regime", "unknown"),
                drawdown_cushion=dd_status_now["cushion"],
                effective_risk_pct=eff_risk_pct,
                execution_status="dry_run",
            )
            return

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

        if self.discord_bot:
            try:
                await self.discord_bot.post_execution(instrument, result, signal)
                self._discord_fail_count = 0
            except Exception as e:
                self._discord_fail_count += 1
                if self._discord_fail_count <= 3:
                    logger.warning("Discord post failed (%d): %s", self._discord_fail_count, e)
                elif self._discord_fail_count == 4:
                    logger.error("Discord appears disconnected — alerts not being delivered")

        # Log trade
        dd_status_now = self.apex.get_drawdown_status(self.account_equity)
        inst_cfg_log = self.config["instruments"][instrument]
        risk_pts = abs(signal.entry_price - signal.stop_loss)
        eff_risk_pct = (
            (risk_pts * inst_cfg_log["contract_size"] * signal.position_size)
            / self.account_equity * 100
        ) if self.account_equity > 0 else 0.0
        signal.contract_size = inst_cfg_log["contract_size"]

        trade_log_id = self.trade_logger.log_trade(
            prediction_id=pred_id,
            instrument=instrument,
            signal=signal,
            regime=prediction.get("regime", "unknown"),
            drawdown_cushion=dd_status_now["cushion"],
            effective_risk_pct=eff_risk_pct,
            execution_status="executed" if result and "orderId" in result else "dry_run",
        )

        if result and "orderId" in result:
            self.order_mgr.add_position(Position(
                instrument=instrument,
                direction=signal.direction,
                size=signal.position_size,
                entry_price=signal.entry_price,
                stop_loss=signal.stop_loss,
                take_profit=signal.take_profit,
                order_id=result["orderId"],
                trade_log_id=trade_log_id,
                max_hold_minutes=getattr(signal, "max_hold_minutes", 0),
            ))

    def _save_system_state(self):
        """Persist system state to data/system_state.json for crash recovery."""
        state_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "data", "system_state.json",
        )
        try:
            os.makedirs(os.path.dirname(state_path), exist_ok=True)
            payload = {
                "cycle": self.cycle,
                "daily_pnl": self.order_mgr.realized_pnl_today,
                "current_trading_date": str(self._current_trading_date) if self._current_trading_date else None,
                "timestamp": datetime.now().isoformat(timespec="seconds"),
            }
            tmp_path = state_path + ".tmp"
            with open(tmp_path, "w") as f:
                json.dump(payload, f, indent=2)
            os.replace(tmp_path, state_path)
            logger.info("System state saved: cycle=%d, daily_pnl=%.2f", self.cycle, self.order_mgr.realized_pnl_today)
        except Exception as e:
            logger.warning("Failed to save system state: %s", e)

    def _restore_system_state(self):
        """Restore cycle number from data/system_state.json if it exists."""
        state_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "data", "system_state.json",
        )
        if not os.path.exists(state_path):
            logger.info("No system_state.json found — starting from cycle 0")
            return
        try:
            with open(state_path, "r") as f:
                data = json.load(f)
            restored_cycle = data.get("cycle", 0)
            self.cycle = restored_cycle
            logger.info(
                "Restored system state: cycle=%d (saved at %s)",
                restored_cycle, data.get("timestamp", "unknown"),
            )
        except Exception as e:
            logger.warning("Failed to restore system state: %s", e)

    async def _reconcile_positions(self):
        """Detect and remove ghost positions that the broker closed but we missed.

        Three detection layers:
          A) Price crossed past SL or TP — broker filled the exit order
          B) Position survived past Apex flatten time — broker auto-closed it
          C) Position older than 8 hours — almost certainly stale
        """
        import yfinance as yf

        et = ZoneInfo("America/New_York")
        now_et = datetime.now(et)
        now_local = datetime.now()
        to_remove = []  # list of (instrument, exit_price, exit_reason, reason_detail)

        for inst, pos in list(self.order_mgr.open_positions.items()):
            inst_cfg = self.config["instruments"].get(inst, {})
            ticker = inst_cfg.get("yfinance_ticker")
            contract_size = inst_cfg.get("contract_size", 1.0)
            entry_time = getattr(pos, "entry_time", None)
            age_hours = (now_local - entry_time).total_seconds() / 3600.0 if entry_time else 999

            # Layer A: Check if price crossed past SL/TP
            if ticker:
                try:
                    tf = yf.Ticker(ticker)
                    hist = tf.history(period="1d", interval="1m")
                    if hist is not None and not hist.empty:
                        bar_high = float(hist.iloc[-1]["High"])
                        bar_low = float(hist.iloc[-1]["Low"])
                        bar_close = float(hist.iloc[-1]["Close"])
                        pos.current_price = bar_close

                        # Check SL breach with 0.1% tolerance
                        sl_tol = abs(pos.stop_loss) * 0.001
                        tp_tol = abs(pos.take_profit) * 0.001

                        if pos.direction == "long":
                            if bar_low <= pos.stop_loss + sl_tol:
                                to_remove.append((inst, pos.stop_loss, "ghost_sl",
                                    f"Price low {bar_low:.2f} breached SL {pos.stop_loss:.2f}"))
                                continue
                            if bar_high >= pos.take_profit - tp_tol:
                                to_remove.append((inst, pos.take_profit, "ghost_tp",
                                    f"Price high {bar_high:.2f} breached TP {pos.take_profit:.2f}"))
                                continue
                        else:  # short
                            if bar_high >= pos.stop_loss - sl_tol:
                                to_remove.append((inst, pos.stop_loss, "ghost_sl",
                                    f"Price high {bar_high:.2f} breached SL {pos.stop_loss:.2f}"))
                                continue
                            if bar_low <= pos.take_profit + tp_tol:
                                to_remove.append((inst, pos.take_profit, "ghost_tp",
                                    f"Price low {bar_low:.2f} breached TP {pos.take_profit:.2f}"))
                                continue
                except Exception as e:
                    logger.debug("Ghost reconcile price check failed for %s: %s", inst, e)

            # Layer B: Post-flatten cleanup
            # If position was opened before today's flatten (4:55 PM ET) and
            # the flatten window has passed, broker closed it
            if entry_time:
                entry_et = entry_time.astimezone(et) if entry_time.tzinfo else entry_time.replace(tzinfo=et)
                flatten_today = now_et.replace(hour=16, minute=55, second=0, microsecond=0)

                # Position from a previous calendar day = definitely flattened
                if entry_et.date() < now_et.date():
                    exit_price = pos.current_price if pos.current_price else pos.entry_price
                    to_remove.append((inst, exit_price, "ghost_flatten",
                        f"Position from {entry_et.date()} — previous session, broker flattened"))
                    continue

                # Position from today but flatten time has passed
                if entry_et < flatten_today and now_et.time() >= dtime(17, 0):
                    exit_price = pos.current_price if pos.current_price else pos.entry_price
                    to_remove.append((inst, exit_price, "ghost_flatten",
                        f"Opened before 4:55 PM ET and market closed — broker flattened"))
                    continue

            # Layer C: Max age (8 hours)
            if age_hours > 8:
                exit_price = pos.current_price if pos.current_price else pos.entry_price
                to_remove.append((inst, exit_price, "ghost_stale",
                    f"Position open {age_hours:.1f} hours — exceeds 8h max"))
                continue

        # Process removals
        for inst, exit_price, exit_reason, detail in to_remove:
            inst_cfg = self.config["instruments"].get(inst, {})
            cs = inst_cfg.get("contract_size", 1.0)

            pnl = self.order_mgr.close_position(
                instrument=inst,
                exit_price=exit_price,
                contract_size=cs,
                exit_reason=exit_reason,
            )
            self.apex.update_balance(self.account_equity + pnl)

            logger.warning(
                "GHOST POSITION REMOVED: %s  exit=%.2f  reason=%s  est_pnl=$%.2f  (%s)",
                inst, exit_price, exit_reason, pnl, detail,
            )
            if self.discord_bot:
                try:
                    await self.discord_bot._signal_channel.send(
                        f"\U0001F47B **GHOST POSITION REMOVED** — {inst}\n"
                        f"Reason: {detail}\n"
                        f"Est. P&L: ${pnl:+.2f} ({exit_reason})\n"
                        f"*Position was closed at broker but local tracking wasn't updated.*"
                    )
                    self._discord_fail_count = 0
                except Exception as e:
                    self._discord_fail_count += 1
                    if self._discord_fail_count <= 3:
                        logger.warning("Discord post failed (%d): %s", self._discord_fail_count, e)

    async def _check_stale_positions(self):
        """Auto-remove positions that have been open for more than 24 hours."""
        now = datetime.now()
        stale_threshold_hours = 24
        for inst, pos in list(self.order_mgr.open_positions.items()):
            entry_time = getattr(pos, "entry_time", None)
            if entry_time is None:
                continue
            age_hours = (now - entry_time).total_seconds() / 3600.0
            if age_hours > stale_threshold_hours:
                inst_cfg = self.config["instruments"].get(inst, {})
                cs = inst_cfg.get("contract_size", 1.0)
                exit_price = pos.current_price if pos.current_price else pos.entry_price

                pnl = self.order_mgr.close_position(
                    instrument=inst,
                    exit_price=exit_price,
                    contract_size=cs,
                    exit_reason="stale_24h",
                )
                self.apex.update_balance(self.account_equity + pnl)

                logger.warning(
                    "STALE POSITION AUTO-REMOVED: %s open %.1f hours  est_pnl=$%.2f",
                    inst, age_hours, pnl,
                )
                if self.discord_bot:
                    try:
                        await self.discord_bot._signal_channel.send(
                            f"\U0001F47B **STALE POSITION AUTO-REMOVED** — {inst}\n"
                            f"Open for {age_hours:.1f} hours (since {entry_time.strftime('%Y-%m-%d %H:%M')})\n"
                            f"Est. P&L: ${pnl:+.2f}"
                        )
                        self._discord_fail_count = 0
                    except Exception as e:
                        self._discord_fail_count += 1
                        if self._discord_fail_count <= 3:
                            logger.warning("Discord post failed (%d): %s", self._discord_fail_count, e)
                        elif self._discord_fail_count == 4:
                            logger.error("Discord appears disconnected — alerts not being delivered")

    def _write_heartbeat(self, status: str):
        """Write a heartbeat file for external monitoring."""
        heartbeat_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "data", "heartbeat.json",
        )
        try:
            os.makedirs(os.path.dirname(heartbeat_path), exist_ok=True)
            payload = {
                "cycle": self.cycle,
                "status": status,
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "instruments": len(self.instruments),
            }
            tmp_path = heartbeat_path + ".tmp"
            with open(tmp_path, "w") as f:
                json.dump(payload, f)
            os.replace(tmp_path, heartbeat_path)
        except Exception as e:
            logger.warning("Failed to write heartbeat: %s", e)

    def _build_radar(self, predictions: dict) -> list:
        """
        Check predictions for instruments approaching a trade threshold.

        Returns list of radar items for instruments that are:
        - Non-neutral direction
        - Below the lowest enabled tier BUT within 75% of its threshold
        """
        if self.config.get("strategy", {}).get("mode") == "scalp":
            tiers_config = self.config.get("scalp_tiers", self.config.get("shot_tiers", {}))
        else:
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
        """Graceful shutdown with state persistence."""
        logger.info("Shutting down trading system...")
        self.is_running = False

        # Save system state for recovery on restart
        self._save_system_state()

        # Flatten positions if configured and executor available
        if self.executor and self.config["schedule"].get("flatten_eod"):
            try:
                await self.executor.flatten_position()
                logger.info("All positions flattened")
            except Exception as e:
                logger.error("Failed to flatten positions: %s", e)

        if self.executor:
            await self.executor.disconnect()
        self.trade_logger.close()
        logger.info("Shutdown complete")
