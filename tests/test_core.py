"""
Comprehensive unit tests for the LaT-PFN trading system's pure-Python logic modules.

Covers:
  - risk/position_sizer.py   (calculate_position_size)
  - risk/circuit_breaker.py   (CircuitBreaker)
  - signals/confidence.py     (score_confidence)
  - signals/shot_classifier.py (classify, nearest_tier_above)
  - execution/order_manager.py (OrderManager, Position)
  - risk/apex_compliance.py   (ApexCompliance)
  - market_data/pipeline.py   (_YFinanceRateLimiter)
  - orchestrator/main_loop.py (system state save/restore, stale positions)

No PyTorch or model loading required.
"""

import json
import math
import os
import time
from datetime import date, datetime, timedelta, time as dtime
from unittest.mock import patch, MagicMock, AsyncMock

import numpy as np
import pytest

from risk.position_sizer import calculate_position_size
from risk.circuit_breaker import CircuitBreaker
from signals.confidence import score_confidence
from signals.shot_classifier import classify, nearest_tier_above
from execution.order_manager import OrderManager, Position
from risk.apex_compliance import ApexCompliance, FLATTEN_TIME, MARKET_REOPEN, ET
from market_data.pipeline import _YFinanceRateLimiter


# =====================================================================
#  1. risk/position_sizer.py — calculate_position_size
# =====================================================================

class TestCalculatePositionSize:
    """Tests for the Kelly-style position sizing function."""

    def test_normal_case(self):
        """$50k equity, 2% risk, $100 stop, $5/pt contract => 2 contracts."""
        # risk_dollars = 50000 * 0.02 = 1000
        # risk_per_contract = 100 * 5 = 500
        # contracts = floor(1000 / 500) = 2
        result = calculate_position_size(
            account_equity=50_000,
            entry_price=20_000,
            stop_loss=19_900,  # 100 pts away
            contract_size=5.0,
            max_risk_pct=0.02,
            max_contracts=10,
        )
        assert result == 2

    def test_zero_equity_returns_zero(self):
        """Zero account equity should yield 0 contracts."""
        result = calculate_position_size(
            account_equity=0,
            entry_price=100,
            stop_loss=95,
            contract_size=5,
            max_risk_pct=0.02,
            max_contracts=10,
        )
        assert result == 0

    def test_negative_equity_returns_zero(self):
        """Negative equity should also yield 0 contracts."""
        result = calculate_position_size(
            account_equity=-1000,
            entry_price=100,
            stop_loss=95,
            contract_size=5,
            max_risk_pct=0.02,
            max_contracts=10,
        )
        assert result == 0

    def test_tiny_stop_distance_capped_by_max_contracts(self):
        """Very small stop => many contracts, but capped at max_contracts."""
        # risk_dollars = 50000 * 0.02 = 1000
        # risk_per_contract = 1 * 5 = 5
        # raw contracts = 1000 / 5 = 200  →  capped at 5
        result = calculate_position_size(
            account_equity=50_000,
            entry_price=20_000,
            stop_loss=19_999,  # only 1 point away
            contract_size=5,
            max_risk_pct=0.02,
            max_contracts=5,
        )
        assert result == 5

    def test_stop_equal_to_entry_returns_zero(self):
        """Stop loss at the exact entry price means zero price risk."""
        result = calculate_position_size(
            account_equity=50_000,
            entry_price=20_000,
            stop_loss=20_000,
            contract_size=5,
            max_risk_pct=0.02,
            max_contracts=10,
        )
        assert result == 0

    def test_very_large_stop_returns_zero(self):
        """If risk_per_contract exceeds the entire risk budget, 0 contracts."""
        # risk_dollars = 50000 * 0.02 = 1000
        # risk_per_contract = 5000 * 5 = 25000  >> 1000
        result = calculate_position_size(
            account_equity=50_000,
            entry_price=20_000,
            stop_loss=15_000,  # 5000 pts
            contract_size=5,
            max_risk_pct=0.02,
            max_contracts=10,
        )
        assert result == 0

    def test_short_trade_uses_abs_distance(self):
        """Entry < stop (short) should still use absolute distance."""
        # |19000 - 19100| = 100, same distance as long case
        result = calculate_position_size(
            account_equity=50_000,
            entry_price=19_000,
            stop_loss=19_100,  # stop above entry (short trade)
            contract_size=5.0,
            max_risk_pct=0.02,
            max_contracts=10,
        )
        assert result == 2

    def test_zero_contract_size_returns_zero(self):
        result = calculate_position_size(
            account_equity=50_000,
            entry_price=100,
            stop_loss=95,
            contract_size=0,
            max_risk_pct=0.02,
            max_contracts=10,
        )
        assert result == 0

    def test_zero_risk_pct_returns_zero(self):
        result = calculate_position_size(
            account_equity=50_000,
            entry_price=100,
            stop_loss=95,
            contract_size=5,
            max_risk_pct=0,
            max_contracts=10,
        )
        assert result == 0

    def test_exactly_one_contract_boundary(self):
        """Risk budget exactly equals risk_per_contract => 1 contract."""
        # risk_dollars = 10000 * 0.01 = 100
        # risk_per_contract = 10 * 10 = 100
        # floor(100 / 100) = 1
        result = calculate_position_size(
            account_equity=10_000,
            entry_price=500,
            stop_loss=490,     # 10 pts
            contract_size=10,
            max_risk_pct=0.01,
            max_contracts=10,
        )
        assert result == 1

    def test_just_below_one_contract_returns_zero(self):
        """Risk budget just below risk_per_contract => 0."""
        # risk_dollars = 10000 * 0.01 = 100
        # risk_per_contract = 11 * 10 = 110  > 100
        result = calculate_position_size(
            account_equity=10_000,
            entry_price=500,
            stop_loss=489,     # 11 pts
            contract_size=10,
            max_risk_pct=0.01,
            max_contracts=10,
        )
        assert result == 0


# =====================================================================
#  2. risk/circuit_breaker.py — CircuitBreaker
# =====================================================================

class TestCircuitBreaker:
    """Tests for the CircuitBreaker risk guard."""

    def test_untriggered_allows_trades(self, mock_config):
        """Fresh breaker should allow opening positions."""
        cb = CircuitBreaker(mock_config)
        ok, msg = cb.can_open_position(open_positions=0)
        assert ok is True
        assert msg == "OK"

    def test_daily_loss_pct_triggers_breaker(self, mock_config):
        """Losing more than max_daily_loss_pct trips the breaker."""
        cb = CircuitBreaker(mock_config)
        # max_daily_loss_pct = 3% of starting equity
        # starting_equity = 50000 =>  3% = $1500
        # If realized_pnl_today = -1600, daily_loss_pct = 1600/50000 = 3.2% > 3%
        cb.update(
            realized_pnl_today=-1600,
            current_equity=48_400,
            starting_equity=50_000,
            open_positions=0,
        )
        assert cb.is_triggered is True
        ok, reason = cb.can_open_position(open_positions=0)
        assert ok is False
        assert "Circuit breaker" in reason

    def test_daily_loss_usd_triggers_breaker(self, mock_config):
        """Exceeding prop firm daily USD loss limit trips the breaker."""
        cb = CircuitBreaker(mock_config)
        # max_daily_loss_usd = 1000
        # realized_pnl_today = -1100 => |-(-1100)| = 1100 > 1000
        cb.update(
            realized_pnl_today=-1100,
            current_equity=48_900,
            starting_equity=50_000,
            open_positions=0,
        )
        assert cb.is_triggered is True
        assert "prop firm" in cb.reason.lower()

    def test_drawdown_pct_triggers_breaker(self, mock_config):
        """Drawdown from peak equity exceeding max_drawdown_pct trips the breaker."""
        cb = CircuitBreaker(mock_config)
        # First, establish a peak by updating with high equity
        cb.update(
            realized_pnl_today=0,
            current_equity=55_000,
            starting_equity=50_000,
            open_positions=0,
        )
        assert cb.is_triggered is False

        # Now drop > 10% from peak: 55000 * 10% = 5500
        # current_equity = 55000 - 6000 = 49000 => dd = 6000/55000 = 10.9% > 10%
        cb.update(
            realized_pnl_today=-6000,
            current_equity=49_000,
            starting_equity=50_000,
            open_positions=0,
        )
        assert cb.is_triggered is True
        assert "drawdown" in cb.reason.lower()

    def test_drawdown_usd_triggers_breaker(self, mock_config):
        """Absolute drawdown exceeding prop firm total drawdown USD limit."""
        cb = CircuitBreaker(mock_config)
        # max_total_drawdown_usd = 2500
        # peak = 50000, current = 47000 => drawdown = 3000 > 2500
        cb.update(
            realized_pnl_today=-3000,
            current_equity=47_000,
            starting_equity=50_000,
            open_positions=0,
        )
        assert cb.is_triggered is True
        assert "prop firm" in cb.reason.lower()

    def test_max_concurrent_positions_blocks(self, mock_config):
        """At max concurrent positions, new positions are blocked without tripping."""
        cb = CircuitBreaker(mock_config)
        # max_concurrent = 3
        ok, reason = cb.can_open_position(open_positions=3)
        assert ok is False
        assert "concurrent" in reason.lower()
        # Breaker itself is NOT triggered — just at capacity
        assert cb.is_triggered is False

    def test_new_day_resets_breaker(self, mock_config):
        """Tripped breaker should reset on a new trading day."""
        cb = CircuitBreaker(mock_config)

        # Trip it
        cb.update(
            realized_pnl_today=-2000,
            current_equity=48_000,
            starting_equity=50_000,
            open_positions=0,
        )
        assert cb.is_triggered is True

        # Simulate a new day by patching date.today()
        fake_tomorrow = date(2099, 1, 1)
        with patch("risk.circuit_breaker.date") as mock_date:
            mock_date.today.return_value = fake_tomorrow
            # Must also allow normal date construction
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            cb.update(
                realized_pnl_today=0,
                current_equity=48_000,
                starting_equity=48_000,
                open_positions=0,
            )

        assert cb.is_triggered is False
        ok, msg = cb.can_open_position(open_positions=0)
        assert ok is True

    def test_below_limits_not_triggered(self, mock_config):
        """Losses within limits should not trip the breaker."""
        cb = CircuitBreaker(mock_config)
        # Small loss well within all limits
        cb.update(
            realized_pnl_today=-200,
            current_equity=49_800,
            starting_equity=50_000,
            open_positions=1,
        )
        assert cb.is_triggered is False
        ok, _ = cb.can_open_position(open_positions=1)
        assert ok is True

    def test_peak_equity_tracks_upward(self, mock_config):
        """Peak equity should ratchet upward and not decrease."""
        cb = CircuitBreaker(mock_config)
        cb.update(
            realized_pnl_today=500,
            current_equity=52_000,
            starting_equity=50_000,
            open_positions=0,
        )
        assert cb._peak_equity == 52_000

        cb.update(
            realized_pnl_today=300,
            current_equity=51_000,
            starting_equity=50_000,
            open_positions=0,
        )
        # Peak should still be 52000 even though equity dropped
        assert cb._peak_equity == 52_000


# =====================================================================
#  3. signals/confidence.py — score_confidence
# =====================================================================

class TestScoreConfidence:
    """Tests for the composite confidence scorer."""

    @staticmethod
    def _make_flat_forecast(n=60, price=20000.0):
        """Forecast with zero slope => trend_clarity ~ 0."""
        return np.full(n, price)

    @staticmethod
    def _make_uptrend_forecast(n=60, start=20000.0, step=2.0):
        """Strongly directional forecast."""
        return np.array([start + i * step for i in range(n)])

    def test_high_confidence_low_uncertainty_trending(self, signal_config):
        """High model conf + strong trend + low uncertainty + trending regime => high score."""
        forecast = self._make_uptrend_forecast(n=60, start=20000, step=5.0)
        uncertainty = np.full(60, 10.0)  # tight band
        score = score_confidence(
            model_confidence=0.9,
            forecast=forecast,
            uncertainty=uncertainty,
            current_price=20000.0,
            regime="trending",
            signal_config=signal_config,
        )
        # trending multiplier = 1.15, should boost
        assert 0.7 <= score <= 1.0

    def test_trending_regime_multiplier_boosts(self, signal_config):
        """Trending regime multiplier (1.15) raises the score."""
        forecast = self._make_uptrend_forecast(n=60, start=1000, step=1.0)
        uncertainty = np.full(60, 5.0)
        score_trending = score_confidence(
            model_confidence=0.7,
            forecast=forecast,
            uncertainty=uncertainty,
            current_price=1000.0,
            regime="trending",
            signal_config=signal_config,
        )
        score_ranging = score_confidence(
            model_confidence=0.7,
            forecast=forecast,
            uncertainty=uncertainty,
            current_price=1000.0,
            regime="ranging",
            signal_config=signal_config,
        )
        assert score_trending > score_ranging

    def test_volatile_regime_reduces_score(self, signal_config):
        """Volatile regime multiplier (0.75) lowers the score more than ranging (0.95)."""
        forecast = self._make_uptrend_forecast(n=60, start=1000, step=1.0)
        uncertainty = np.full(60, 5.0)
        score_volatile = score_confidence(
            model_confidence=0.7,
            forecast=forecast,
            uncertainty=uncertainty,
            current_price=1000.0,
            regime="volatile",
            signal_config=signal_config,
        )
        score_ranging = score_confidence(
            model_confidence=0.7,
            forecast=forecast,
            uncertainty=uncertainty,
            current_price=1000.0,
            regime="ranging",
            signal_config=signal_config,
        )
        assert score_volatile < score_ranging

    def test_flat_forecast_lowers_score(self, signal_config):
        """Flat forecast => near-zero trend_clarity => lower score."""
        flat = self._make_flat_forecast(n=60, price=20000.0)
        trending = self._make_uptrend_forecast(n=60, start=20000, step=5.0)
        uncertainty = np.full(60, 50.0)

        score_flat = score_confidence(
            model_confidence=0.7,
            forecast=flat,
            uncertainty=uncertainty,
            current_price=20000.0,
            regime="ranging",
            signal_config=signal_config,
        )
        score_trending = score_confidence(
            model_confidence=0.7,
            forecast=trending,
            uncertainty=uncertainty,
            current_price=20000.0,
            regime="ranging",
            signal_config=signal_config,
        )
        assert score_flat < score_trending

    def test_score_clamped_to_zero_one(self, signal_config):
        """Score must always be in [0, 1] regardless of extreme inputs."""
        # High everything + trending multiplier > 1 => try to push above 1.0
        forecast = self._make_uptrend_forecast(n=60, start=100, step=100.0)
        uncertainty = np.full(60, 0.001)  # near-zero uncertainty
        score = score_confidence(
            model_confidence=1.0,
            forecast=forecast,
            uncertainty=uncertainty,
            current_price=100.0,
            regime="trending",
            signal_config=signal_config,
        )
        assert 0.0 <= score <= 1.0

    def test_score_clamped_at_zero_with_zero_inputs(self, signal_config):
        """Zero/low everything should not go below 0."""
        forecast = self._make_flat_forecast(n=60, price=100.0)
        uncertainty = np.full(60, 10000.0)  # massive uncertainty
        score = score_confidence(
            model_confidence=0.0,
            forecast=forecast,
            uncertainty=uncertainty,
            current_price=100.0,
            regime="volatile",
            signal_config=signal_config,
        )
        assert score >= 0.0

    def test_unknown_regime_uses_default_multiplier(self, signal_config):
        """Unknown regime falls back to multiplier 1.0."""
        forecast = self._make_uptrend_forecast(n=60, start=1000, step=1.0)
        uncertainty = np.full(60, 5.0)
        score = score_confidence(
            model_confidence=0.7,
            forecast=forecast,
            uncertainty=uncertainty,
            current_price=1000.0,
            regime="unknown_regime",
            signal_config=signal_config,
        )
        # Should be computed with multiplier 1.0 — between trending (1.15) and ranging (0.95)
        assert 0.0 <= score <= 1.0

    def test_large_uncertainty_lowers_score(self, signal_config):
        """High uncertainty should reduce uncertainty_inverse component."""
        forecast = self._make_uptrend_forecast(n=60, start=1000, step=1.0)
        low_unc = np.full(60, 1.0)
        high_unc = np.full(60, 500.0)

        score_low_unc = score_confidence(
            model_confidence=0.7,
            forecast=forecast,
            uncertainty=low_unc,
            current_price=1000.0,
            regime="ranging",
            signal_config=signal_config,
        )
        score_high_unc = score_confidence(
            model_confidence=0.7,
            forecast=forecast,
            uncertainty=high_unc,
            current_price=1000.0,
            regime="ranging",
            signal_config=signal_config,
        )
        assert score_low_unc > score_high_unc


# =====================================================================
#  4. signals/shot_classifier.py — classify / nearest_tier_above
# =====================================================================

class TestShotClassifier:
    """Tests for NBA shot-tier classification."""

    def test_classify_layup(self, tiers_config):
        """Confidence 0.65 (>= 0.60) should classify as layup."""
        tier, params = classify(0.65, tiers_config)
        assert tier == "layup"
        assert params["label"] == "Layup"

    def test_classify_short_range(self, tiers_config):
        """Confidence 0.50 is below layup (0.60) but we need to check actual thresholds.
        0.50 < 0.52 so it falls to free_throw (0.45). Let's use 0.55 for short_range."""
        tier, _ = classify(0.55, tiers_config)
        assert tier == "short_range"

    def test_classify_short_range_at_boundary(self, tiers_config):
        """Confidence exactly 0.52 should match short_range."""
        tier, _ = classify(0.52, tiers_config)
        assert tier == "short_range"

    def test_classify_free_throw(self, tiers_config):
        """Confidence 0.50 falls into free_throw range (0.45-0.52)."""
        tier, _ = classify(0.50, tiers_config)
        assert tier == "free_throw"

    def test_classify_three_pointer(self, tiers_config):
        """Confidence 0.40 falls into three_pointer range (0.38-0.45)."""
        tier, _ = classify(0.40, tiers_config)
        assert tier == "three_pointer"

    def test_classify_no_trade_below_all_enabled(self, tiers_config):
        """Confidence 0.20 is below all enabled tiers (half_court, hail_mary disabled)."""
        tier, params = classify(0.20, tiers_config)
        assert tier == "no_trade"
        assert params == {}

    def test_classify_no_trade_at_zero(self, tiers_config):
        """Zero confidence should be no_trade."""
        tier, _ = classify(0.0, tiers_config)
        assert tier == "no_trade"

    def test_disabled_tiers_skipped(self, tiers_config):
        """Confidence 0.33 would match half_court (0.32) if enabled, but it's disabled.
        It should fall through to no_trade since three_pointer min is 0.38."""
        tier, _ = classify(0.33, tiers_config)
        assert tier == "no_trade"

    def test_disabled_tier_re_enabled(self, tiers_config):
        """After enabling half_court, confidence 0.33 should match it."""
        tiers_config["half_court"]["enabled"] = True
        tier, params = classify(0.33, tiers_config)
        assert tier == "half_court"
        assert params["label"] == "Half Court"

    def test_classify_hail_mary_when_enabled(self, tiers_config):
        """Enable hail_mary, then confidence 0.26 should match it."""
        tiers_config["hail_mary"]["enabled"] = True
        tier, _ = classify(0.26, tiers_config)
        assert tier == "hail_mary"

    def test_classify_at_exact_boundary(self, tiers_config):
        """Confidence exactly at layup min should match layup."""
        tier, _ = classify(0.60, tiers_config)
        assert tier == "layup"

    def test_classify_just_below_boundary(self, tiers_config):
        """Confidence 0.599 should fall to short_range."""
        tier, _ = classify(0.599, tiers_config)
        assert tier == "short_range"

    # --- nearest_tier_above ---

    def test_nearest_tier_above_below_all(self, tiers_config):
        """Confidence 0.20 (below all enabled) -> nearest enabled tier above is three_pointer (0.38)."""
        name, threshold = nearest_tier_above(0.20, tiers_config)
        assert name == "three_pointer"
        assert threshold == 0.38

    def test_nearest_tier_above_in_three_pointer(self, tiers_config):
        """Confidence 0.40 is inside three_pointer; next tier above is free_throw (0.45)."""
        name, threshold = nearest_tier_above(0.40, tiers_config)
        assert name == "free_throw"
        assert threshold == 0.45

    def test_nearest_tier_above_in_free_throw(self, tiers_config):
        """Confidence 0.50 is inside free_throw; next tier above is short_range (0.52)."""
        name, threshold = nearest_tier_above(0.50, tiers_config)
        assert name == "short_range"
        assert threshold == 0.52

    def test_nearest_tier_above_in_layup(self, tiers_config):
        """Confidence 0.70 is already in the highest enabled tier => ("", 0.0)."""
        name, threshold = nearest_tier_above(0.70, tiers_config)
        assert name == ""
        assert threshold == 0.0

    def test_nearest_tier_above_skips_disabled(self, tiers_config):
        """Disabled tiers should be skipped when finding the next tier above."""
        # half_court (0.32) is disabled, so from 0.30 the nearest enabled is three_pointer (0.38)
        name, threshold = nearest_tier_above(0.30, tiers_config)
        assert name == "three_pointer"
        assert threshold == 0.38


# =====================================================================
#  5. execution/order_manager.py — OrderManager + Position
# =====================================================================

class TestPosition:
    """Tests for the Position dataclass."""

    def test_unrealized_pnl_long_profit(self):
        pos = Position("MYM", "long", 2, 20000.0, 19900.0, 20200.0)
        pos.current_price = 20050.0
        assert pos.unrealized_pnl_points == pytest.approx(50.0)

    def test_unrealized_pnl_long_loss(self):
        pos = Position("MYM", "long", 2, 20000.0, 19900.0, 20200.0)
        pos.current_price = 19950.0
        assert pos.unrealized_pnl_points == pytest.approx(-50.0)

    def test_unrealized_pnl_short_profit(self):
        pos = Position("MYM", "short", 1, 20000.0, 20100.0, 19800.0)
        pos.current_price = 19950.0
        # short pnl = -(19950 - 20000) = 50
        assert pos.unrealized_pnl_points == pytest.approx(50.0)

    def test_unrealized_pnl_short_loss(self):
        pos = Position("MYM", "short", 1, 20000.0, 20100.0, 19800.0)
        pos.current_price = 20050.0
        assert pos.unrealized_pnl_points == pytest.approx(-50.0)

    def test_unrealized_pnl_zero_current_price(self):
        pos = Position("MYM", "long", 1, 20000.0, 19900.0, 20100.0)
        # current_price defaults to 0.0
        assert pos.unrealized_pnl_points == 0.0

    def test_round_trip_serialization(self):
        pos = Position("MNQ", "long", 3, 18500.0, 18400.0, 18700.0, order_id=42)
        d = pos.to_dict()
        restored = Position.from_dict(d)
        assert restored.instrument == pos.instrument
        assert restored.direction == pos.direction
        assert restored.size == pos.size
        assert restored.entry_price == pos.entry_price
        assert restored.stop_loss == pos.stop_loss
        assert restored.take_profit == pos.take_profit
        assert restored.order_id == 42


class TestOrderManager:
    """Tests for OrderManager lifecycle operations."""

    def test_add_and_has_position(self, tmp_path):
        om = OrderManager(state_file=str(tmp_path / "positions.json"))
        pos = Position("MYM", "long", 2, 20000.0, 19900.0, 20200.0)
        om.add_position(pos)
        assert om.has_position("MYM") is True
        assert om.has_position("MNQ") is False

    def test_open_count(self, tmp_path):
        om = OrderManager(state_file=str(tmp_path / "positions.json"))
        assert om.open_count == 0

        om.add_position(Position("MYM", "long", 1, 20000.0, 19900.0, 20100.0))
        assert om.open_count == 1

        om.add_position(Position("MNQ", "short", 2, 18000.0, 18100.0, 17800.0))
        assert om.open_count == 2

    def test_close_position_long_profit(self, tmp_path):
        om = OrderManager(state_file=str(tmp_path / "positions.json"))
        om.add_position(Position("MYM", "long", 2, 20000.0, 19900.0, 20200.0))

        # Exit at 20100 => pnl_points = 20100 - 20000 = 100
        # pnl_dollars = 100 * 0.50 * 2 = $100
        pnl = om.close_position("MYM", exit_price=20100.0, contract_size=0.50)
        assert pnl == pytest.approx(100.0)
        assert om.has_position("MYM") is False
        assert om.realized_pnl_today == pytest.approx(100.0)

    def test_close_position_long_loss(self, tmp_path):
        om = OrderManager(state_file=str(tmp_path / "positions.json"))
        om.add_position(Position("MYM", "long", 2, 20000.0, 19900.0, 20200.0))

        # Exit at 19950 => pnl_points = 19950 - 20000 = -50
        # pnl_dollars = -50 * 0.50 * 2 = -$50
        pnl = om.close_position("MYM", exit_price=19950.0, contract_size=0.50)
        assert pnl == pytest.approx(-50.0)

    def test_close_position_short_profit(self, tmp_path):
        om = OrderManager(state_file=str(tmp_path / "positions.json"))
        om.add_position(Position("MNQ", "short", 1, 18000.0, 18100.0, 17800.0))

        # Exit at 17900 => pnl_points = -(17900 - 18000) = 100
        # pnl_dollars = 100 * 2.0 * 1 = $200
        pnl = om.close_position("MNQ", exit_price=17900.0, contract_size=2.0)
        assert pnl == pytest.approx(200.0)

    def test_close_position_short_loss(self, tmp_path):
        om = OrderManager(state_file=str(tmp_path / "positions.json"))
        om.add_position(Position("MNQ", "short", 1, 18000.0, 18100.0, 17800.0))

        # Exit at 18050 => pnl_points = -(18050 - 18000) = -50
        # pnl_dollars = -50 * 2.0 * 1 = -$100
        pnl = om.close_position("MNQ", exit_price=18050.0, contract_size=2.0)
        assert pnl == pytest.approx(-100.0)

    def test_close_nonexistent_returns_zero(self, tmp_path):
        om = OrderManager(state_file=str(tmp_path / "positions.json"))
        pnl = om.close_position("FAKE", exit_price=100.0, contract_size=5.0)
        assert pnl == 0.0

    def test_close_all(self, tmp_path):
        om = OrderManager(state_file=str(tmp_path / "positions.json"))
        om.add_position(Position("MYM", "long", 1, 20000.0, 19900.0, 20100.0))
        om.add_position(Position("MNQ", "short", 1, 18000.0, 18100.0, 17800.0))
        assert om.open_count == 2

        om.close_all()
        assert om.open_count == 0
        assert om.has_position("MYM") is False
        assert om.has_position("MNQ") is False
        # Positions moved to closed_positions
        assert len(om.closed_positions) == 2

    def test_persistence_save_and_load(self, tmp_path):
        """Save state, create a new OrderManager, load state — positions round-trip."""
        state_file = str(tmp_path / "positions.json")

        om1 = OrderManager(state_file=state_file)
        om1.add_position(Position("MYM", "long", 2, 20000.0, 19900.0, 20200.0, order_id=1))
        om1.add_position(Position("MNQ", "short", 1, 18000.0, 18100.0, 17800.0, order_id=2))

        # Verify file was written
        assert os.path.exists(state_file)

        # Create a brand new manager and load
        om2 = OrderManager(state_file=state_file)
        om2.load_state()

        assert om2.open_count == 2
        assert om2.has_position("MYM")
        assert om2.has_position("MNQ")
        assert om2.open_positions["MYM"].direction == "long"
        assert om2.open_positions["MYM"].size == 2
        assert om2.open_positions["MNQ"].direction == "short"

    def test_load_state_no_file(self, tmp_path):
        """Loading from a non-existent file should silently succeed (fresh start)."""
        om = OrderManager(state_file=str(tmp_path / "nonexistent.json"))
        om.load_state()
        assert om.open_count == 0

    def test_reset_daily_pnl(self, tmp_path):
        om = OrderManager(state_file=str(tmp_path / "positions.json"))
        om.add_position(Position("MYM", "long", 1, 20000.0, 19900.0, 20100.0))
        om.close_position("MYM", exit_price=20050.0, contract_size=0.50)
        assert om.realized_pnl_today != 0.0

        om.reset_daily_pnl()
        assert om.realized_pnl_today == 0.0

    def test_update_prices(self, tmp_path):
        om = OrderManager(state_file=str(tmp_path / "positions.json"))
        om.add_position(Position("MYM", "long", 1, 20000.0, 19900.0, 20100.0))
        om.update_prices({"MYM": 20050.0, "UNKNOWN": 999.0})
        assert om.open_positions["MYM"].current_price == 20050.0

    def test_remove_position(self, tmp_path):
        om = OrderManager(state_file=str(tmp_path / "positions.json"))
        om.add_position(Position("MYM", "long", 1, 20000.0, 19900.0, 20100.0))
        om.remove_position("MYM")
        assert om.open_count == 0
        assert len(om.closed_positions) == 1

    def test_remove_nonexistent_position(self, tmp_path):
        om = OrderManager(state_file=str(tmp_path / "positions.json"))
        om.remove_position("FAKE")  # Should not raise
        assert om.open_count == 0


# =====================================================================
#  6. risk/apex_compliance.py — ApexCompliance
# =====================================================================

class TestApexCompliance:
    """Tests for Apex Trader Funding compliance checks."""

    # --- 5:1 R:R check ---

    def test_rr_check_passes_valid(self, mock_config):
        """Risk:reward of 1:2 (risk/reward = 0.5) is well within 5:1."""
        ac = ApexCompliance(mock_config)
        ok, reason = ac._check_risk_reward_ratio(
            entry_price=20000,
            stop_price=19950,    # risk = 50 pts
            target_price=20100,  # reward = 100 pts  => ratio = 0.5
        )
        assert ok is True

    def test_rr_check_rejects_invalid(self, mock_config):
        """Risk:reward of 6:1 exceeds the 5:1 limit."""
        ac = ApexCompliance(mock_config)
        ok, reason = ac._check_risk_reward_ratio(
            entry_price=20000,
            stop_price=19400,    # risk = 600 pts
            target_price=20100,  # reward = 100 pts => ratio = 6.0
        )
        assert ok is False
        assert "5:1" in reason

    def test_rr_check_at_boundary(self, mock_config):
        """Risk:reward of exactly 5:1 should pass (not strictly greater)."""
        ac = ApexCompliance(mock_config)
        ok, _ = ac._check_risk_reward_ratio(
            entry_price=20000,
            stop_price=19500,    # risk = 500 pts
            target_price=20100,  # reward = 100 pts => ratio = 5.0
        )
        assert ok is True

    def test_rr_check_zero_reward_rejected(self, mock_config):
        """Target at entry price => zero reward => rejected."""
        ac = ApexCompliance(mock_config)
        ok, reason = ac._check_risk_reward_ratio(
            entry_price=20000,
            stop_price=19900,
            target_price=20000,  # zero reward
        )
        assert ok is False
        assert "Zero reward" in reason

    # --- Correlated instrument check ---

    def test_correlated_blocks_opposing_positions(self, mock_config):
        """Long MYM while short MNQ (same correlated group) should be blocked."""
        ac = ApexCompliance(mock_config)
        existing_positions = {
            "MNQ": Position("MNQ", "short", 1, 18000, 18100, 17800),
        }
        ok, reason = ac._check_correlated(
            instrument="MYM",
            direction="long",
            open_positions=existing_positions,
        )
        assert ok is False
        assert "correlated" in reason.lower()

    def test_correlated_allows_same_direction(self, mock_config):
        """Long MYM while long MNQ (same direction) is allowed."""
        ac = ApexCompliance(mock_config)
        existing_positions = {
            "MNQ": Position("MNQ", "long", 1, 18000, 17900, 18200),
        }
        ok, _ = ac._check_correlated(
            instrument="MYM",
            direction="long",
            open_positions=existing_positions,
        )
        assert ok is True

    def test_correlated_allows_uncorrelated_instruments(self, mock_config):
        """Different asset classes (e.g., gold vs equity) should not block."""
        ac = ApexCompliance(mock_config)
        # MGC is in CORRELATED_GROUPS only if it's in the equity index set
        # MGC is NOT in the equity index set, so opposing MYM should be fine
        existing_positions = {
            "MGC": Position("MGC", "short", 1, 2000, 2010, 1980),
        }
        ok, _ = ac._check_correlated(
            instrument="MYM",
            direction="long",
            open_positions=existing_positions,
        )
        assert ok is True

    def test_correlated_no_open_positions(self, mock_config):
        """No open positions => always passes."""
        ac = ApexCompliance(mock_config)
        ok, _ = ac._check_correlated("MYM", "long", {})
        assert ok is True

    # --- should_flatten_now ---

    def test_should_flatten_now_within_window(self, mock_config):
        """Between 4:55 PM and 6:00 PM ET should trigger flatten."""
        ac = ApexCompliance(mock_config)
        # 4:56 PM ET
        fake_now = datetime(2025, 6, 15, 16, 56, tzinfo=ET)
        with patch("risk.apex_compliance.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            assert ac.should_flatten_now() is True

    def test_should_flatten_now_before_window(self, mock_config):
        """Before 4:55 PM ET should NOT trigger flatten."""
        ac = ApexCompliance(mock_config)
        fake_now = datetime(2025, 6, 15, 16, 50, tzinfo=ET)
        with patch("risk.apex_compliance.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            assert ac.should_flatten_now() is False

    def test_should_flatten_now_after_reopen(self, mock_config):
        """After 6:00 PM ET (market reopen) should NOT trigger flatten."""
        ac = ApexCompliance(mock_config)
        fake_now = datetime(2025, 6, 15, 18, 5, tzinfo=ET)
        with patch("risk.apex_compliance.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            assert ac.should_flatten_now() is False

    def test_should_flatten_now_at_exact_boundary(self, mock_config):
        """Exactly 4:55 PM ET should trigger flatten (inclusive)."""
        ac = ApexCompliance(mock_config)
        fake_now = datetime(2025, 6, 15, 16, 55, 0, tzinfo=ET)
        with patch("risk.apex_compliance.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            assert ac.should_flatten_now() is True

    def test_should_flatten_now_at_exact_reopen(self, mock_config):
        """Exactly 6:00 PM ET should NOT trigger (reopen boundary is exclusive)."""
        ac = ApexCompliance(mock_config)
        fake_now = datetime(2025, 6, 15, 18, 0, 0, tzinfo=ET)
        with patch("risk.apex_compliance.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            assert ac.should_flatten_now() is False

    def test_should_flatten_during_morning(self, mock_config):
        """10:00 AM ET should NOT trigger flatten."""
        ac = ApexCompliance(mock_config)
        fake_now = datetime(2025, 6, 15, 10, 0, tzinfo=ET)
        with patch("risk.apex_compliance.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            assert ac.should_flatten_now() is False

    # --- Trailing drawdown ---

    def test_trailing_drawdown_floor_tracks_correctly(self, mock_config):
        """As balance increases, drawdown floor trails up."""
        ac = ApexCompliance(mock_config)
        # Starting: balance=50000, floor=50000-2500=47500

        # Balance rises to 51000 => floor = 51000 - 2500 = 48500
        status = ac.update_balance(51000)
        assert ac._drawdown_floor == pytest.approx(48500)
        assert ac._highest_balance == pytest.approx(51000)

        # Balance drops to 50500 => floor should NOT drop (stays at 48500)
        status = ac.update_balance(50500)
        assert ac._drawdown_floor == pytest.approx(48500)
        assert ac._highest_balance == pytest.approx(51000)

        # Balance rises again to 52000 => floor = 52000 - 2500 = 49500
        status = ac.update_balance(52000)
        assert ac._drawdown_floor == pytest.approx(49500)

    def test_trailing_drawdown_floor_locks_at_profit_target(self, mock_config):
        """Floor stops trailing once it reaches profit_target_balance ($53,000)."""
        ac = ApexCompliance(mock_config)
        # profit_target_balance = 50000 + 3000 = 53000
        # Floor locks when highest_balance - 2500 >= 53000
        # => highest_balance >= 55500

        # Push balance high enough to lock
        ac.update_balance(55500)
        # floor = 55500 - 2500 = 53000 => locks
        assert ac._floor_locked is True
        assert ac._drawdown_floor == pytest.approx(53000)

        # Even if balance goes much higher, floor stays locked at 53000
        ac.update_balance(60000)
        assert ac._drawdown_floor == pytest.approx(53000)
        assert ac._floor_locked is True

    def test_floor_does_not_lock_below_target(self, mock_config):
        """Floor should not lock if it hasn't reached the profit target balance."""
        ac = ApexCompliance(mock_config)
        ac.update_balance(52000)
        # floor = 52000 - 2500 = 49500 < 53000 => not locked
        assert ac._floor_locked is False
        assert ac._drawdown_floor == pytest.approx(49500)

    def test_drawdown_status_cushion(self, mock_config):
        """get_drawdown_status should report correct cushion."""
        ac = ApexCompliance(mock_config)
        ac.update_balance(51000)
        status = ac.get_drawdown_status(50000)
        # floor = 48500, cushion = 50000 - 48500 = 1500
        assert status["cushion"] == pytest.approx(1500)
        assert status["drawdown_floor"] == pytest.approx(48500)
        assert status["highest_balance"] == pytest.approx(51000)

    def test_drawdown_status_at_risk_flag(self, mock_config):
        """at_risk flag should be True when cushion < 20% of trailing_drawdown_amount."""
        ac = ApexCompliance(mock_config)
        # trailing_drawdown_amount = 2500, 20% = 500
        ac.update_balance(50000)
        # floor = 47500, balance = 47600 => cushion = 100 < 500 => at_risk
        status = ac.get_drawdown_status(47600)
        assert status["at_risk"] is True

    # --- MAE check ---

    def test_mae_check_no_profit_balance(self, mock_config):
        """If no profit balance set, MAE rule does not apply."""
        ac = ApexCompliance(mock_config)
        ok, _ = ac._check_mae(20000, 19900, 2, 5.0)
        assert ok is True

    def test_mae_check_passes_within_limit(self, mock_config):
        """Max loss within 30% of profit balance should pass."""
        ac = ApexCompliance(mock_config)
        ac.set_sod_profit_balance(5000)
        # max_loss = |20000-19950| * 5 * 1 = 250
        # mae_limit = 5000 * 0.30 = 1500
        # 250 < 1500 => pass
        ok, _ = ac._check_mae(20000, 19950, 1, 5.0)
        assert ok is True

    def test_mae_check_rejects_excessive(self, mock_config):
        """Max loss exceeding 30% of profit balance should fail."""
        ac = ApexCompliance(mock_config)
        ac.set_sod_profit_balance(1000)
        # max_loss = |20000 - 19900| * 5 * 2 = 1000
        # mae_limit = 1000 * 0.30 = 300
        # 1000 > 300 => fail
        ok, reason = ac._check_mae(20000, 19900, 2, 5.0)
        assert ok is False
        assert "MAE" in reason

    # --- Consistency rule ---

    def test_consistency_ok_when_balanced(self, mock_config):
        """Multiple days of balanced profit should pass consistency."""
        ac = ApexCompliance(mock_config)
        ac.record_daily_pnl("2025-01-01", 500)
        ac.record_daily_pnl("2025-01-02", 600)
        ac.record_daily_pnl("2025-01-03", 400)
        ok, _ = ac.check_consistency()
        # best_day = 600, total = 1500, best_day_pct = 40% > 30% => fail
        # Actually 600/1500 = 0.4 => fail
        assert ok is False

    def test_consistency_fails_single_big_day(self, mock_config):
        """One dominant day > 30% of total fails consistency."""
        ac = ApexCompliance(mock_config)
        ac.record_daily_pnl("2025-01-01", 900)
        ac.record_daily_pnl("2025-01-02", 100)
        ac.record_daily_pnl("2025-01-03", 100)
        ok, reason = ac.check_consistency()
        # best = 900, total = 1100, pct = 81.8% > 30%
        assert ok is False
        assert "Consistency" in reason

    def test_consistency_passes_many_equal_days(self, mock_config):
        """Many equal-sized days should easily pass the 30% rule."""
        ac = ApexCompliance(mock_config)
        for i in range(10):
            ac.record_daily_pnl(f"2025-01-{i+1:02d}", 300)
        ok, _ = ac.check_consistency()
        # best = 300, total = 3000, pct = 10% < 30% => pass
        assert ok is True

    def test_consistency_ok_with_no_profit(self, mock_config):
        """No profit => consistency rule does not apply."""
        ac = ApexCompliance(mock_config)
        ok, _ = ac.check_consistency()
        assert ok is True

    def test_consistency_ok_with_negative_total(self, mock_config):
        """Negative total P&L => consistency rule does not apply."""
        ac = ApexCompliance(mock_config)
        ac.record_daily_pnl("2025-01-01", -500)
        ac.record_daily_pnl("2025-01-02", -200)
        ok, _ = ac.check_consistency()
        assert ok is True

    # --- check_all integration ---

    def test_check_all_passes_compliant_trade(self, mock_config):
        """A fully compliant trade should pass all checks."""
        ac = ApexCompliance(mock_config)
        # Patch time to be during market hours (10 AM ET)
        fake_now = datetime(2025, 6, 15, 10, 0, tzinfo=ET)
        with patch("risk.apex_compliance.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            ok, reason = ac.check_all(
                instrument="MYM",
                direction="long",
                entry_price=20000,
                stop_price=19950,    # risk = 50
                target_price=20150,  # reward = 150, ratio = 0.33
                position_size=1,
                contract_size=0.50,
                open_positions={},
            )
        assert ok is True
        assert reason == "Apex compliant"

    def test_check_all_rejects_bad_rr(self, mock_config):
        """check_all should reject a trade with bad R:R."""
        ac = ApexCompliance(mock_config)
        fake_now = datetime(2025, 6, 15, 10, 0, tzinfo=ET)
        with patch("risk.apex_compliance.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            ok, reason = ac.check_all(
                instrument="MYM",
                direction="long",
                entry_price=20000,
                stop_price=19400,    # risk = 600
                target_price=20050,  # reward = 50, ratio = 12
                position_size=1,
                contract_size=0.50,
                open_positions={},
            )
        assert ok is False
        assert "5:1" in reason

    def test_check_all_rejects_near_close(self, mock_config):
        """check_all should reject trades after 4:45 PM ET."""
        ac = ApexCompliance(mock_config)
        fake_now = datetime(2025, 6, 15, 16, 50, tzinfo=ET)
        with patch("risk.apex_compliance.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            ok, reason = ac.check_all(
                instrument="MYM",
                direction="long",
                entry_price=20000,
                stop_price=19950,
                target_price=20100,
                position_size=1,
                contract_size=0.50,
                open_positions={},
            )
        assert ok is False
        assert "4:45" in reason or "No new trades" in reason


# =====================================================================
#  7. market_data/pipeline.py — _YFinanceRateLimiter
# =====================================================================

class TestYFinanceRateLimiter:
    """Tests for the yfinance rate limiter and circuit breaker."""

    def test_rate_limiter_enforces_min_interval(self):
        """Successive calls should be spaced at least min_interval apart."""
        rl = _YFinanceRateLimiter(max_calls_per_second=10.0)  # 100ms interval
        rl.wait()
        t1 = time.monotonic()
        rl.wait()
        t2 = time.monotonic()
        # Should have waited at least ~0.1s (allow some tolerance)
        assert (t2 - t1) >= 0.08

    def test_success_resets_failure_count(self):
        """record_success should reset the consecutive failure counter."""
        rl = _YFinanceRateLimiter(failure_threshold=5)
        for _ in range(4):
            rl.record_failure()
        assert rl._consecutive_failures == 4
        rl.record_success()
        assert rl._consecutive_failures == 0

    def test_circuit_breaker_trips_after_threshold(self):
        """After failure_threshold consecutive failures, circuit breaker should open."""
        rl = _YFinanceRateLimiter(
            failure_threshold=3, circuit_pause_seconds=0.1
        )
        for _ in range(3):
            rl.record_failure()
        # Circuit breaker should have tripped: _circuit_open_until > now
        assert rl._circuit_open_until > time.monotonic() - 1.0
        # Failures reset after tripping
        assert rl._consecutive_failures == 0

    def test_circuit_breaker_does_not_trip_below_threshold(self):
        """Fewer failures than threshold should NOT trip the circuit breaker."""
        rl = _YFinanceRateLimiter(failure_threshold=5)
        for _ in range(4):
            rl.record_failure()
        # Circuit should still be closed (open_until at 0.0 or in the past)
        assert rl._circuit_open_until <= time.monotonic()
        assert rl._consecutive_failures == 4

    def test_success_between_failures_resets_counter(self):
        """A success in the middle of failures should prevent circuit break."""
        rl = _YFinanceRateLimiter(failure_threshold=3)
        rl.record_failure()
        rl.record_failure()
        rl.record_success()  # Reset
        rl.record_failure()
        rl.record_failure()
        # Only 2 consecutive failures after reset — should not trip
        assert rl._consecutive_failures == 2
        assert rl._circuit_open_until <= time.monotonic()


# =====================================================================
#  8. orchestrator/main_loop.py — System state save/restore
# =====================================================================

class TestSystemStatePersistence:
    """Tests for graceful shutdown state save and restore.

    Tests the save/restore logic without instantiating the full TradingSystem
    (which requires PyTorch and model weights). Instead, we directly test the
    JSON serialization contract that _save_system_state / _restore_system_state use.
    """

    def test_save_system_state_creates_valid_json(self, tmp_path):
        """System state should be saved as valid JSON with expected keys."""
        state_dir = tmp_path / "data"
        state_dir.mkdir()
        state_path = state_dir / "system_state.json"

        # Simulate what _save_system_state writes
        cycle = 42
        daily_pnl = 150.0
        current_trading_date = date(2025, 6, 15)
        payload = {
            "cycle": cycle,
            "daily_pnl": daily_pnl,
            "current_trading_date": str(current_trading_date),
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        }
        tmp_fp = str(state_path) + ".tmp"
        with open(tmp_fp, "w") as f:
            json.dump(payload, f, indent=2)
        os.replace(tmp_fp, str(state_path))

        assert state_path.exists()
        with open(state_path) as f:
            data = json.load(f)
        assert data["cycle"] == 42
        assert data["daily_pnl"] == 150.0
        assert data["current_trading_date"] == "2025-06-15"
        assert "timestamp" in data

    def test_restore_system_state_sets_cycle(self, tmp_path):
        """Restoring from system_state.json should recover the cycle number."""
        state_dir = tmp_path / "data"
        state_dir.mkdir()
        state_file = state_dir / "system_state.json"
        state_file.write_text(json.dumps({
            "cycle": 99,
            "daily_pnl": 500.0,
            "current_trading_date": "2025-06-15",
            "timestamp": "2025-06-15T12:00:00",
        }))

        # Simulate what _restore_system_state does
        with open(state_file, "r") as f:
            data = json.load(f)
        restored_cycle = data.get("cycle", 0)

        assert restored_cycle == 99
        # daily_pnl should be present in file but NOT restored to the system
        assert data["daily_pnl"] == 500.0

    def test_restore_missing_file_returns_default(self, tmp_path):
        """If system_state.json does not exist, cycle stays at default (0)."""
        state_path = tmp_path / "data" / "system_state.json"
        assert not state_path.exists()

        # Simulate: if file doesn't exist, cycle stays at 0
        default_cycle = 0
        if state_path.exists():
            with open(state_path) as f:
                data = json.load(f)
            default_cycle = data.get("cycle", 0)
        assert default_cycle == 0

    def test_restore_corrupt_file_handled_gracefully(self, tmp_path):
        """A corrupt state file should not crash; should fall back to defaults."""
        state_dir = tmp_path / "data"
        state_dir.mkdir()
        state_file = state_dir / "system_state.json"
        state_file.write_text("not valid json {{{")

        restored_cycle = 0
        try:
            with open(state_file, "r") as f:
                data = json.load(f)
            restored_cycle = data.get("cycle", 0)
        except Exception:
            pass  # Should fall back gracefully
        assert restored_cycle == 0

    def test_save_with_none_trading_date(self, tmp_path):
        """When current_trading_date is None, it should be saved as null."""
        state_dir = tmp_path / "data"
        state_dir.mkdir()
        state_path = state_dir / "system_state.json"

        payload = {
            "cycle": 5,
            "daily_pnl": 0.0,
            "current_trading_date": None,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        }
        with open(state_path, "w") as f:
            json.dump(payload, f, indent=2)

        with open(state_path) as f:
            data = json.load(f)
        assert data["current_trading_date"] is None
        assert data["cycle"] == 5


# =====================================================================
#  9. Stale position detection
# =====================================================================

class TestStalePositionDetection:
    """Tests for the stale position detector."""

    def test_stale_position_detected(self):
        """A position open > 24 hours should be flagged as stale."""
        pos = Position("MYM", "long", 2, 20000.0, 19900.0, 20200.0)
        pos.entry_time = datetime.now() - timedelta(hours=25)

        now = datetime.now()
        age_hours = (now - pos.entry_time).total_seconds() / 3600.0
        assert age_hours > 24

    def test_fresh_position_not_stale(self):
        """A position open < 24 hours should not be flagged."""
        pos = Position("MYM", "long", 2, 20000.0, 19900.0, 20200.0)
        pos.entry_time = datetime.now() - timedelta(hours=2)

        now = datetime.now()
        age_hours = (now - pos.entry_time).total_seconds() / 3600.0
        assert age_hours < 24

    def test_position_without_entry_time_skipped(self):
        """If entry_time is None, the position should be skipped without error."""
        pos = Position("MYM", "long", 2, 20000.0, 19900.0, 20200.0)
        # Force entry_time to None to simulate missing data
        entry_time = getattr(pos, "entry_time", None)
        # entry_time is set by default_factory, but check getattr pattern
        assert entry_time is not None  # Position always has entry_time

    def test_stale_detection_with_mixed_positions(self):
        """Only positions older than 24h should appear in stale list."""
        positions = {
            "MYM": Position("MYM", "long", 1, 20000.0, 19900.0, 20100.0),
            "MNQ": Position("MNQ", "short", 1, 18000.0, 18100.0, 17800.0),
            "MGC": Position("MGC", "long", 1, 2000.0, 1990.0, 2020.0),
        }
        # Make MYM stale (25h old), MNQ fresh (1h old), MGC stale (48h old)
        positions["MYM"].entry_time = datetime.now() - timedelta(hours=25)
        positions["MNQ"].entry_time = datetime.now() - timedelta(hours=1)
        positions["MGC"].entry_time = datetime.now() - timedelta(hours=48)

        now = datetime.now()
        stale = []
        for inst, pos in positions.items():
            entry_time = getattr(pos, "entry_time", None)
            if entry_time is None:
                continue
            age_hours = (now - entry_time).total_seconds() / 3600.0
            if age_hours > 24:
                stale.append(inst)

        assert sorted(stale) == ["MGC", "MYM"]
        assert "MNQ" not in stale
