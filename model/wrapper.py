"""
High-level wrapper around the LaT-PFN model.

Exposes a single ``predict()`` method that takes DataFrames and returns
actionable forecast data (prices, uncertainty, direction, confidence, regime).
"""

import sys
import logging
from pathlib import Path
from typing import Dict

import numpy as np
import pandas as pd
import torch

from data.normalizer import NormStats
from model.input_formatter import format_inputs
from model.output_processor import process_forecast

logger = logging.getLogger(__name__)


def _resolve_device(preference: str) -> torch.device:
    """Pick the best available device."""
    if preference == "auto":
        if torch.cuda.is_available():
            return torch.device("cuda")
        if torch.backends.mps.is_available():
            return torch.device("mps")
        return torch.device("cpu")
    return torch.device(preference)


class LaTPFNPredictor:
    """
    Loads the LaT-PFN model and provides a clean prediction interface.
    """

    def __init__(self, config: dict):
        self.config = config
        mcfg = config["model"]
        self.device = _resolve_device(mcfg["device"])
        self.n_history = mcfg["n_history"]
        self.n_prompt = mcfg["n_prompt"]

        # Add repo to path so we can import LaT-PFN internals
        repo_path = str(Path(mcfg["lat_pfn_repo"]).resolve())
        if repo_path not in sys.path:
            sys.path.insert(0, repo_path)

        self.model = self._load_model(mcfg)
        logger.info("LaT-PFN model loaded on %s", self.device)

    # ── Model loading ─────────────────────────────────────────────────

    def _load_model(self, mcfg: dict):
        """Build architecture and load pretrained weights."""
        from util.config_util import dotdict, ShapeConfig
        from initialiser import build_model
        from util.persist import load_model

        # Reconstruct the config the model expects
        lat_config = dotdict(
            shape=ShapeConfig(
                n_context=mcfg["n_context"],
                n_sequence=mcfg["n_history"] + mcfg["n_prompt"],
                n_features=1,
                n_heldout=mcfg["n_heldout"],
                n_prompt=mcfg["n_prompt"],
            ),
            model_size=dotdict(num_layers=3, ff_scale=2, nhead=4, dropout=0.1),
            device=self.device,
            n_domain_params=10,
            masking_type="independent",
            train_noise=0.02,
            ema_decay=0.9952,
            ema_warmup_epochs=95,
            train_length=250,
            mup=True,
            width=8,
        )

        # Build model architecture
        model = build_model(
            width=lat_config.width,
            config=lat_config,
            n_outputs=mcfg["n_bins"],
            use_mup_parametrization=lat_config.mup,
            load_base_shapes=True,
            build_base_shapes=True,
        )

        # Load pretrained weights
        weights_path = Path(mcfg["weights_path"])
        if weights_path.exists():
            model = load_model(str(weights_path), model, self.device)
            logger.info("Loaded weights from %s", weights_path)
        else:
            logger.warning(
                "Weights not found at %s — model will produce random predictions. "
                "Run scripts/download_model.py first.",
                weights_path,
            )
            model.eval()

        return model

    # ── Prediction ────────────────────────────────────────────────────

    def predict(
        self,
        heldout_df: pd.DataFrame,
        context_dfs: Dict[str, pd.DataFrame],
    ) -> dict:
        """
        Run a full prediction cycle.

        Args:
            heldout_df:  Target instrument OHLCV (>= n_history + n_prompt rows).
            context_dfs: {symbol: OHLCV DataFrame} for context assets.

        Returns:
            dict with keys:
                forecast_prices : np.ndarray   (n_prompt,)
                uncertainty     : np.ndarray   (n_prompt,)
                direction       : str          'long' | 'short' | 'neutral'
                confidence      : float        0..1
                regime          : str          'trending' | 'ranging' | 'volatile'
                current_price   : float
                stats           : NormStats
        """
        # Format inputs
        tensors, close_stats = format_inputs(
            heldout_df,
            context_dfs,
            n_history=self.n_history,
            n_prompt=self.n_prompt,
        )

        # Move tensors to device
        device_tensors = {k: v.to(self.device) for k, v in tensors.items()}

        # Run model inference
        with torch.no_grad():
            raw_output = self.model.create_forecast(**device_tensors)

        # Process output → prices and uncertainty
        processed = process_forecast(raw_output, close_stats, heldout_idx=3)

        forecast = processed["forecast_prices"]
        uncertainty = processed["uncertainty"]

        # Current price (last Close in history)
        current_price = float(heldout_df["Close"].iloc[-1])

        # Direction and confidence
        direction, confidence = self._analyze_forecast(
            forecast, uncertainty, current_price
        )

        # Regime detection from forecast characteristics
        regime = self._detect_regime(forecast, uncertainty, current_price)

        return {
            "forecast_prices": forecast,
            "uncertainty": uncertainty,
            "direction": direction,
            "confidence": confidence,
            "regime": regime,
            "current_price": current_price,
            "stats": close_stats,
        }

    # ── Analysis helpers ──────────────────────────────────────────────

    def _analyze_forecast(
        self,
        forecast: np.ndarray,
        uncertainty: np.ndarray,
        current_price: float,
    ) -> tuple[str, float]:
        """Derive directional bias and confidence from the forecast curve."""
        # Expected move over forecast horizon
        end_price = float(np.mean(forecast[-10:]))  # avg of last 10 steps
        move_pct = (end_price - current_price) / current_price

        # Average uncertainty as fraction of price
        avg_unc_pct = float(np.mean(uncertainty)) / current_price

        # Confidence: how large is the expected move relative to uncertainty
        signal_to_noise = abs(move_pct) / (avg_unc_pct + 1e-8)
        confidence = min(signal_to_noise / 2.0, 1.0)  # scale so ~2:1 S/N = 1.0

        # Direction thresholds (require at least 0.05% expected move)
        if move_pct > 0.0005:
            direction = "long"
        elif move_pct < -0.0005:
            direction = "short"
        else:
            direction = "neutral"

        return direction, confidence

    def _detect_regime(
        self,
        forecast: np.ndarray,
        uncertainty: np.ndarray,
        current_price: float,
    ) -> str:
        """Simple regime classification from forecast shape."""
        # Trend strength: R² of a linear fit
        x = np.arange(len(forecast), dtype=np.float64)
        coeffs = np.polyfit(x, forecast, 1)
        fitted = np.polyval(coeffs, x)
        ss_res = np.sum((forecast - fitted) ** 2)
        ss_tot = np.sum((forecast - np.mean(forecast)) ** 2)
        r_squared = 1.0 - (ss_res / (ss_tot + 1e-8))

        # Volatility: average uncertainty relative to price
        avg_unc_pct = float(np.mean(uncertainty)) / current_price

        if avg_unc_pct > 0.01:  # >1% avg uncertainty
            return "volatile"
        elif r_squared > 0.7:  # strong linear trend
            return "trending"
        else:
            return "ranging"
