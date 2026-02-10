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
    timestamp: datetime = field(default_factory=datetime.now)


class SignalGenerator:
    """Generates trading signals from LaT-PFN predictions."""

    def __init__(self, config: dict):
        self.config = config
        self.signal_config = config["signal"]
        self.risk_config = config["risk"]

    def generate(
        self,
        instrument: str,
        prediction: dict,
    ) -> Optional[TradingSignal]:
        """
        Evaluate a prediction and produce a signal if conditions are met.

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

        if confidence < self.signal_config["min_confidence"]:
            logger.debug(
                "%s: confidence %.3f below threshold %.3f",
                instrument, confidence, self.signal_config["min_confidence"],
            )
            return None

        # Entry / exit levels
        entry_price = prediction["current_price"]
        stop_loss, take_profit = calculate_exits(
            entry_price=entry_price,
            direction=direction,
            forecast=prediction["forecast_prices"],
            uncertainty=prediction["uncertainty"],
            risk_config=self.risk_config,
        )

        # Preliminary position size (risk manager will refine)
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
        )

        logger.info(
            "%s SIGNAL: %s %d @ %.2f  SL=%.2f  TP=%.2f  conf=%.3f  regime=%s",
            instrument, direction, position_size, entry_price,
            stop_loss, take_profit, confidence, prediction["regime"],
        )

        return signal
