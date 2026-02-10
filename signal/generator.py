"""
Converts model predictions into actionable TradingSignal objects.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import numpy as np

from signal.confidence import score_confidence
from signal.exits import calculate_exits
from signal.shot_classifier import classify as classify_shot, get_tier_color

logger = logging.getLogger(__name__)


@dataclass
class TradingSignal:
    """A fully specified trading signal ready for risk validation."""
    instrument: str
    direction: str                  # 'long' | 'short'
    confidence: float               # 0..1
    entry_price: float
    stop_loss: float
    take_profit: float
    position_size: int              # contracts (preliminary, risk manager adjusts)
    regime: str
    shot_type: str = "no_trade"     # NBA tier: layup, short_range, free_throw, etc.
    size_multiplier: float = 1.0    # from shot tier config (risk manager uses this)
    timestamp: datetime = field(default_factory=datetime.now)


class SignalGenerator:
    """Generates trading signals from LaT-PFN predictions."""

    def __init__(self, config: dict):
        self.config = config
        self.signal_config = config["signal"]
        self.risk_config = config["risk"]
        self.tiers_config = config.get("shot_tiers", {})

    def generate(
        self,
        instrument: str,
        prediction: dict,
    ) -> Optional[TradingSignal]:
        """
        Evaluate a prediction and produce a signal if conditions are met.

        Uses the NBA shot-tier classification to determine trade type,
        exit multipliers, and position size scaling.

        Args:
            instrument: 'YM', 'NQ', or 'GC'.
            prediction: dict from LaTPFNPredictor.predict().

        Returns:
            TradingSignal or None if no trade warranted.
        """
        direction = prediction["direction"]
        if direction == "neutral":
            logger.debug("%s: neutral direction, skipping", instrument)
            return None

        # Composite confidence
        confidence = score_confidence(
            model_confidence=prediction["confidence"],
            forecast=prediction["forecast_prices"],
            uncertainty=prediction["uncertainty"],
            current_price=prediction["current_price"],
            regime=prediction["regime"],
            signal_config=self.signal_config,
        )

        # Absolute floor check
        if confidence < self.signal_config["min_confidence"]:
            logger.debug(
                "%s: confidence %.3f below absolute floor %.3f",
                instrument, confidence, self.signal_config["min_confidence"],
            )
            return None

        # NBA shot-tier classification
        tier_name, tier_params = classify_shot(confidence, self.tiers_config)

        if tier_name == "no_trade":
            logger.debug(
                "%s: confidence %.3f below all enabled tiers",
                instrument, confidence,
            )
            return None

        # Extract tier multipliers
        target_multiplier = tier_params.get("target_multiplier", 1.0)
        stop_multiplier = tier_params.get("stop_multiplier", 1.0)
        size_multiplier = tier_params.get("size_multiplier", 1.0)
        min_rr_override = tier_params.get("min_reward_risk", None)

        # Entry / exit levels (scaled by shot tier)
        entry_price = prediction["current_price"]
        stop_loss, take_profit = calculate_exits(
            entry_price=entry_price,
            direction=direction,
            forecast=prediction["forecast_prices"],
            uncertainty=prediction["uncertainty"],
            risk_config=self.risk_config,
            target_multiplier=target_multiplier,
            stop_multiplier=stop_multiplier,
            min_rr_override=min_rr_override,
        )

        # Preliminary position size (risk manager will refine with size_multiplier)
        position_size = 1

        signal = TradingSignal(
            instrument=instrument,
            direction=direction,
            confidence=confidence,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            position_size=position_size,
            regime=prediction["regime"],
            shot_type=tier_name,
            size_multiplier=size_multiplier,
        )

        logger.info(
            "%s SIGNAL [%s]: %s %d @ %.2f  SL=%.2f  TP=%.2f  "
            "conf=%.3f  regime=%s  size_mult=%.2f",
            instrument, tier_params.get("label", tier_name),
            direction, position_size, entry_price,
            stop_loss, take_profit, confidence,
            prediction["regime"], size_multiplier,
        )

        return signal
