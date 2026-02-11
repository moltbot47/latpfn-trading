"""
Shared fixtures for latpfn-trading unit tests.

Provides a mock config dict that mirrors the structure in config/settings.yaml
but uses test-friendly values (small numbers, predictable thresholds).
"""

import pytest


@pytest.fixture
def mock_config() -> dict:
    """
    Minimal config dict matching the shape expected by all modules under test.

    Values are chosen for easy mental arithmetic in assertions:
      - Account equity: $50,000
      - Max risk per trade: 2% ($1,000)
      - Daily loss cap: 3% or $1,000 USD
      - Max drawdown: 10% or $2,500 USD
      - Max concurrent positions: 3
    """
    return {
        "risk": {
            "max_risk_per_trade_pct": 2.0,
            "max_position_size_contracts": 5,
            "max_daily_loss_pct": 3.0,       # 3% of starting equity
            "max_drawdown_pct": 10.0,         # 10% from peak
            "max_concurrent_positions": 3,
            "stop_loss_atr_multiplier": 1.5,
            "min_reward_risk_ratio": 1.5,
            "trailing_stop_activation_pct": 2.0,
            "trailing_stop_distance_pct": 1.0,
            "prop_firm": {
                "starting_balance": 50000,
                "max_daily_loss_usd": 1000,
                "max_total_drawdown_usd": 2500,
                "profit_target_usd": 3000,
                "flatten_eod": True,
                "flatten_time": "16:55",
                "no_new_trades_after": "16:45",
                "max_risk_reward_ratio": 5.0,
                "mae_pct": 0.30,
                "consistency_pct": 0.30,
            },
        },
        "signal": {
            "min_confidence": 0.25,
            "regime_multipliers": {
                "trending": 1.15,
                "ranging": 0.95,
                "volatile": 0.75,
            },
            "weights": {
                "model_confidence": 0.4,
                "trend_clarity": 0.3,
                "uncertainty_inverse": 0.3,
            },
        },
        "shot_tiers": {
            "layup": {
                "label": "Layup",
                "confidence_min": 0.60,
                "target_multiplier": 0.4,
                "stop_multiplier": 0.8,
                "size_multiplier": 1.0,
                "min_reward_risk": 1.0,
                "enabled": True,
            },
            "short_range": {
                "label": "Short Range",
                "confidence_min": 0.52,
                "target_multiplier": 0.6,
                "stop_multiplier": 0.9,
                "size_multiplier": 1.0,
                "min_reward_risk": 1.2,
                "enabled": True,
            },
            "free_throw": {
                "label": "Free Throw",
                "confidence_min": 0.45,
                "target_multiplier": 0.8,
                "stop_multiplier": 1.0,
                "size_multiplier": 0.75,
                "min_reward_risk": 1.5,
                "enabled": True,
            },
            "three_pointer": {
                "label": "3-Pointer",
                "confidence_min": 0.38,
                "target_multiplier": 1.2,
                "stop_multiplier": 1.2,
                "size_multiplier": 0.5,
                "min_reward_risk": 2.0,
                "enabled": True,
            },
            "half_court": {
                "label": "Half Court",
                "confidence_min": 0.32,
                "target_multiplier": 2.0,
                "stop_multiplier": 1.5,
                "size_multiplier": 0.25,
                "min_reward_risk": 3.0,
                "enabled": False,
            },
            "hail_mary": {
                "label": "Hail Mary",
                "confidence_min": 0.25,
                "target_multiplier": 3.5,
                "stop_multiplier": 1.5,
                "size_multiplier": 0.15,
                "min_reward_risk": 5.0,
                "enabled": False,
            },
        },
        "execution": {
            "mode": "dry_run",
            "default_equity": 50000,
        },
    }


@pytest.fixture
def signal_config(mock_config) -> dict:
    """Shortcut to the signal sub-config."""
    return mock_config["signal"]


@pytest.fixture
def tiers_config(mock_config) -> dict:
    """Shortcut to the shot_tiers sub-config."""
    return mock_config["shot_tiers"]
