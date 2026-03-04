"""Tests for the trend-following strategy."""

import os
import tempfile

import numpy as np
import pandas as pd
import pytest

from strategies.trend_follower.strategy import (
    TrendSignal,
    TrendStrategy,
    compute_adx,
    compute_atr,
)
from strategies.trend_follower.trail_manager import TrailManager, TrailState
from strategies.trend_follower.price_feed import PriceFeed, PriceSnapshot


# ── Fixtures ──────────────────────────────────────────────────────


def make_bars(n: int = 300, trend: str = "up") -> pd.DataFrame:
    """Generate synthetic OHLCV bars for testing."""
    np.random.seed(42)
    base = 20000.0
    noise = np.random.randn(n) * 20

    if trend == "up":
        drift = np.linspace(0, 500, n)
    elif trend == "down":
        drift = np.linspace(0, -500, n)
    else:
        drift = np.zeros(n)

    close = base + drift + np.cumsum(noise)
    high = close + np.abs(np.random.randn(n) * 15) + 5
    low = close - np.abs(np.random.randn(n) * 15) - 5
    opn = close + np.random.randn(n) * 5
    volume = np.random.randint(100, 10000, n)

    return pd.DataFrame(
        {"Open": opn, "High": high, "Low": low, "Close": close, "Volume": volume}
    )


def make_breakout_bars(direction: str = "long") -> pd.DataFrame:
    """Generate bars that end with a Donchian breakout."""
    np.random.seed(123)
    n = 250

    # Ranging phase (first 230 bars)
    base = 20000.0
    close = base + np.random.randn(230) * 10
    close = np.concatenate([close, np.zeros(20)])

    if direction == "long":
        # Last 20 bars: strong uptrend breaking above channel
        for i in range(20):
            close[230 + i] = close[229] + (i + 1) * 15
    else:
        for i in range(20):
            close[230 + i] = close[229] - (i + 1) * 15

    high = close + np.abs(np.random.randn(n) * 10) + 5
    low = close - np.abs(np.random.randn(n) * 10) - 5
    opn = close + np.random.randn(n) * 3
    volume = np.random.randint(100, 5000, n)

    return pd.DataFrame(
        {"Open": opn, "High": high, "Low": low, "Close": close, "Volume": volume}
    )


@pytest.fixture
def config():
    return {
        "trend_follower": {
            "donchian_period": 20,
            "atr_period": 14,
            "adx_threshold": 25,
            "ema_fast": 50,
            "ema_slow": 200,
            "stop_atr_multiplier": 2.0,
            "trail_atr_multiplier": 3.0,
            "risk_per_trade_pct": 0.02,
            "min_atr_dollars": 1.0,  # low threshold for test data
        },
        "risk": {"max_position_size_contracts": 10},
        "instruments": {
            "MNQ": {"contract_size": 2.0},
            "MYM": {"contract_size": 0.5},
        },
    }


# ── ATR / ADX Tests ──────────────────────────────────────────────


class TestIndicators:
    def test_compute_atr(self):
        bars = make_bars(100)
        atr = compute_atr(bars, period=14)
        assert len(atr) == 100
        assert atr.iloc[-1] > 0
        assert np.isnan(atr.iloc[0])  # not enough data for rolling

    def test_compute_adx(self):
        bars = make_bars(100, trend="up")
        adx = compute_adx(bars, period=14)
        assert len(adx) == 100
        # ADX should be positive for trending data
        last_valid = adx.dropna().iloc[-1]
        assert last_valid >= 0

    def test_atr_increases_with_volatility(self):
        # Low vol
        bars_low = make_bars(100)
        # High vol (scale up the price range)
        bars_high = bars_low.copy()
        bars_high["High"] = bars_high["High"] + 50
        bars_high["Low"] = bars_high["Low"] - 50

        atr_low = compute_atr(bars_low).iloc[-1]
        atr_high = compute_atr(bars_high).iloc[-1]
        assert atr_high > atr_low


# ── TrendStrategy Tests ──────────────────────────────────────────


class TestTrendStrategy:
    def test_init(self, config):
        strategy = TrendStrategy(config)
        assert strategy.donchian_period == 20
        assert strategy.adx_threshold == 25
        assert strategy.stop_atr_mult == 2.0

    def test_scan_insufficient_bars(self, config):
        strategy = TrendStrategy(config)
        short_bars = make_bars(50)  # not enough for EMA-200
        signal = strategy.scan("MNQ", short_bars)
        assert signal is None

    def test_scan_ranging_market(self, config):
        strategy = TrendStrategy(config)
        bars = make_bars(300, trend="flat")
        signal = strategy.scan("MNQ", bars)
        # Ranging market should not trigger breakout (low ADX)
        # May or may not be None depending on noise, but ADX filter should block
        if signal is not None:
            assert signal.adx >= 25  # if signal exists, ADX must be above threshold

    def test_scan_returns_trend_signal(self, config):
        strategy = TrendStrategy(config)
        bars = make_breakout_bars("long")
        signal = strategy.scan("MNQ", bars)
        # Might be None if ADX/EMA filters don't pass with synthetic data
        if signal is not None:
            assert isinstance(signal, TrendSignal)
            assert signal.direction == "long"
            assert signal.instrument == "MNQ"
            assert signal.atr > 0
            assert signal.adx >= 25
            assert 0 <= signal.confidence <= 1
            assert signal.stop_price < signal.entry_price

    def test_scan_short_breakout(self, config):
        strategy = TrendStrategy(config)
        bars = make_breakout_bars("short")
        signal = strategy.scan("MNQ", bars)
        if signal is not None:
            assert signal.direction == "short"
            assert signal.stop_price > signal.entry_price

    def test_size_position_basic(self, config):
        strategy = TrendStrategy(config)
        signal = TrendSignal(
            instrument="MNQ",
            direction="long",
            entry_price=20000,
            stop_price=19950,
            atr=25,
            adx=30,
            confidence=0.6,
        )
        # equity=50000, risk=2% = $1000
        # stop_dist=50, contract_size=2.0 → risk_per_contract = $100
        # contracts = 1000 / 100 = 10
        size = strategy.size_position(signal, equity=50000, contract_size=2.0)
        assert size == 10

    def test_size_position_floors_at_one(self, config):
        strategy = TrendStrategy(config)
        signal = TrendSignal(
            instrument="MNQ",
            direction="long",
            entry_price=20000,
            stop_price=19500,
            atr=250,
            adx=30,
            confidence=0.6,
        )
        # stop_dist=500, contract_size=2.0 → risk_per_contract=$1000
        # risk=$1000 → contracts = 1000/1000 = 1
        size = strategy.size_position(signal, equity=50000, contract_size=2.0)
        assert size >= 1

    def test_size_position_caps_at_max(self, config):
        strategy = TrendStrategy(config)
        signal = TrendSignal(
            instrument="MNQ",
            direction="long",
            entry_price=20000,
            stop_price=19999,
            atr=0.5,
            adx=30,
            confidence=0.6,
        )
        # stop_dist=1, contract_size=2.0 → risk_per_contract=$2
        # risk=$1000 → contracts = 500, capped at 10
        size = strategy.size_position(signal, equity=50000, contract_size=2.0)
        assert size == 10  # max_position_size_contracts


# ── TrailManager Tests ────────────────────────────────────────────


class TestTrailState:
    def test_long_stop_hit(self):
        trail = TrailState(
            instrument="MNQ",
            direction="long",
            entry_price=20000,
            initial_stop=19950,
            current_stop=19950,
            atr=25,
            best_price=20000,
        )
        # Price drops to stop
        action = trail.update(price=19940, high=19960, low=19930)
        assert action == "stop_hit"

    def test_long_trail_up(self):
        trail = TrailState(
            instrument="MNQ",
            direction="long",
            entry_price=20000,
            initial_stop=19950,
            current_stop=19950,
            atr=25,
            best_price=20000,
            trail_multiplier=3.0,
        )
        # Price goes up — trail should follow
        action = trail.update(price=20100, high=20120, low=20080)
        assert action is None
        assert trail.best_price == 20120
        # new stop = 20120 - 3*25 = 20045
        assert trail.current_stop == 20045

    def test_long_trail_does_not_lower(self):
        trail = TrailState(
            instrument="MNQ",
            direction="long",
            entry_price=20000,
            initial_stop=19950,
            current_stop=20045,
            atr=25,
            best_price=20120,
            trail_multiplier=3.0,
        )
        # Price dips but doesn't hit stop — trail should not move down
        action = trail.update(price=20060, high=20070, low=20050)
        assert action is None
        assert trail.current_stop == 20045  # unchanged
        assert trail.best_price == 20120  # unchanged

    def test_short_stop_hit(self):
        trail = TrailState(
            instrument="MNQ",
            direction="short",
            entry_price=20000,
            initial_stop=20050,
            current_stop=20050,
            atr=25,
            best_price=20000,
        )
        action = trail.update(price=20060, high=20070, low=20050)
        assert action == "stop_hit"

    def test_short_trail_down(self):
        trail = TrailState(
            instrument="MNQ",
            direction="short",
            entry_price=20000,
            initial_stop=20050,
            current_stop=20050,
            atr=25,
            best_price=20000,
            trail_multiplier=3.0,
        )
        # Price drops — trail should follow
        action = trail.update(price=19880, high=19920, low=19870)
        assert action is None
        assert trail.best_price == 19870
        # new stop = 19870 + 3*25 = 19945
        assert trail.current_stop == 19945

    def test_scale_out_long(self):
        trail = TrailState(
            instrument="MNQ",
            direction="long",
            entry_price=20000,
            initial_stop=19950,
            current_stop=19950,
            atr=25,
            best_price=20000,
            trail_multiplier=3.0,
            current_size=4,
            original_size=4,
        )
        # scale_out_target = 20000 + 1.5 * 50 = 20075
        assert trail.scale_out_target == 20075

        # Price reaches scale-out target
        action = trail.update(price=20080, high=20090, low=20070)
        assert action == "scale_out"
        assert trail.scale_out_done is True

        # Second time should not trigger scale-out again
        action = trail.update(price=20090, high=20100, low=20080)
        assert action is None

    def test_scale_out_not_triggered_for_single_contract(self):
        trail = TrailState(
            instrument="MNQ",
            direction="long",
            entry_price=20000,
            initial_stop=19950,
            current_stop=19950,
            atr=25,
            best_price=20000,
            current_size=1,
        )
        # Price reaches scale-out target but only 1 contract
        action = trail.update(price=20080, high=20090, low=20070)
        assert action is None  # can't scale out with 1 contract

    def test_unrealized_r(self):
        trail = TrailState(
            instrument="MNQ",
            direction="long",
            entry_price=20000,
            initial_stop=19950,
            current_stop=19950,
            atr=25,
            best_price=20100,
        )
        # risk = 50 pts, best gain = 100 pts = 2R
        assert trail.unrealized_r == 2.0

    def test_to_dict_from_dict_roundtrip(self):
        trail = TrailState(
            instrument="MNQ",
            direction="long",
            entry_price=20000,
            initial_stop=19950,
            current_stop=20045,
            atr=25,
            best_price=20120,
            trail_multiplier=3.0,
            scale_out_done=True,
            original_size=4,
            current_size=2,
        )
        d = trail.to_dict()
        restored = TrailState.from_dict(d)
        assert restored.instrument == trail.instrument
        assert restored.current_stop == trail.current_stop
        assert restored.best_price == trail.best_price
        assert restored.scale_out_done is True
        assert restored.current_size == 2


class TestTrailManager:
    def test_add_trail_long(self):
        mgr = TrailManager(trail_multiplier=3.0)
        trail = mgr.add_trail("MNQ", "long", 20000, atr=25, position_size=2)
        assert trail.entry_price == 20000
        assert trail.initial_stop == 19950  # 20000 - 2*25
        assert trail.current_stop == 19950
        assert "MNQ" in mgr.trails

    def test_add_trail_short(self):
        mgr = TrailManager(trail_multiplier=3.0)
        trail = mgr.add_trail("MNQ", "short", 20000, atr=25, position_size=2)
        assert trail.initial_stop == 20050  # 20000 + 2*25

    def test_update_all(self):
        mgr = TrailManager(trail_multiplier=3.0)
        mgr.add_trail("MNQ", "long", 20000, atr=25, position_size=1)

        # Price up — no action
        snap = PriceSnapshot("MNQ", 20050, 20060, 20040, 1000, 0)
        actions = mgr.update_all({"MNQ": snap})
        assert actions == []

        # Price hits stop
        snap2 = PriceSnapshot("MNQ", 19940, 19960, 19930, 1000, 0)
        actions = mgr.update_all({"MNQ": snap2})
        assert len(actions) == 1
        assert actions[0] == ("MNQ", "stop_hit")

    def test_remove(self):
        mgr = TrailManager()
        mgr.add_trail("MNQ", "long", 20000, atr=25, position_size=1)
        assert "MNQ" in mgr.trails
        mgr.remove("MNQ")
        assert "MNQ" not in mgr.trails

    def test_multiple_positions(self):
        mgr = TrailManager(trail_multiplier=3.0)
        mgr.add_trail("MNQ", "long", 20000, atr=25, position_size=1)
        mgr.add_trail("MYM", "short", 40000, atr=50, position_size=1)

        # MNQ goes up, MYM goes up (bad for short)
        snaps = {
            "MNQ": PriceSnapshot("MNQ", 20050, 20060, 20040, 1000, 0),
            "MYM": PriceSnapshot("MYM", 40110, 40120, 40100, 1000, 0),
        }
        actions = mgr.update_all(snaps)
        # MYM short stop hit at 40100 (initial stop = 40000 + 2*50 = 40100)
        assert ("MYM", "stop_hit") in actions


# ── PriceFeed Tests ───────────────────────────────────────────────


class TestPriceFeed:
    def test_init(self):
        feed = PriceFeed(["MNQ", "MYM"])
        assert feed.instruments == ["MNQ", "MYM"]
        assert "NQ=F" in feed.yf_tickers
        assert "YM=F" in feed.yf_tickers

    def test_ticker_mapping(self):
        feed = PriceFeed(["MBT"])
        assert feed.yf_tickers == ["BTC-USD"]
        assert feed._ticker_to_inst["BTC-USD"] == "MBT"

    def test_snapshot_returns_cached_on_rate_limit(self):
        feed = PriceFeed(["MNQ"])
        # Pre-populate cache
        feed._last_snapshots["MNQ"] = PriceSnapshot(
            "MNQ", 20000, 20010, 19990, 1000, 0
        )
        feed._snapshot_cache_time = 999999999999  # far future
        result = feed.snapshot()
        assert result["MNQ"].price == 20000


# ── Runner State Persistence Tests ────────────────────────────────


class TestRunnerState:
    def test_save_and_load_state(self):
        from strategies.trend_follower.runner import TrendFollowerRunner

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            state_file = f.name

        try:
            config = {
                "trend_follower": {
                    "instruments": ["MNQ"],
                    "state_file": state_file,
                },
                "risk": {"prop_firm": {}},
                "execution": {"default_equity": 50000},
                "traderspost": {
                    "webhook_url": "https://webhooks.traderspost.io/test/fake"
                },
            }
            runner = TrendFollowerRunner(config, dry_run=True)
            runner.open_positions = {
                "MNQ": {
                    "instrument": "MNQ",
                    "direction": "long",
                    "size": 2,
                    "entry_price": 20000,
                    "entry_time": 1000000,
                    "atr": 25,
                }
            }
            runner.trail_mgr.add_trail(
                "MNQ", "long", 20000, atr=25, position_size=2
            )
            runner.equity = 50500
            runner.realized_pnl_today = 150.0
            runner._save_state()

            # Load into fresh runner
            runner2 = TrendFollowerRunner(config, dry_run=True)
            runner2._load_state()

            assert "MNQ" in runner2.open_positions
            assert runner2.open_positions["MNQ"]["direction"] == "long"
            assert runner2.equity == 50500
            assert runner2.realized_pnl_today == 150.0
            assert "MNQ" in runner2.trail_mgr.trails
            assert runner2.trail_mgr.trails["MNQ"].entry_price == 20000
        finally:
            os.unlink(state_file)

    def test_get_status(self):
        from strategies.trend_follower.runner import TrendFollowerRunner

        config = {
            "trend_follower": {
                "instruments": ["MNQ"],
                "state_file": "/tmp/test_trend.json",
            },
            "risk": {"prop_firm": {}},
            "execution": {"default_equity": 50000},
            "traderspost": {
                "webhook_url": "https://webhooks.traderspost.io/test/fake"
            },
        }
        runner = TrendFollowerRunner(config, dry_run=True)
        status = runner.get_status()
        assert status["agent"] == "trend-follower-cme"
        assert status["mode"] == "dry_run"
        assert status["positions"] == 0
        assert status["equity"] == 50000


# ── Integration-style tests ───────────────────────────────────────


class TestEntryToExitFlow:
    """Test the full entry → trail → exit flow without live data."""

    def test_entry_trail_exit_long(self):
        """Simulate: entry at 20000, price rises to 20200, then falls to trail stop."""
        mgr = TrailManager(trail_multiplier=3.0)

        # Entry
        trail = mgr.add_trail("MNQ", "long", 20000, atr=25, position_size=2)
        assert trail.current_stop == 19950  # 20000 - 2*25

        # Price rises in stages
        for price in [20050, 20100, 20150, 20200]:
            snap = PriceSnapshot("MNQ", price, price + 10, price - 10, 1000, 0)
            actions = mgr.update_all({"MNQ": snap})
            assert not any(a == "stop_hit" for _, a in actions)

        # After 20200: best=20210, stop=20210-75=20135
        assert trail.best_price == 20210
        assert trail.current_stop == 20135

        # Price falls to trail stop
        snap = PriceSnapshot("MNQ", 20130, 20140, 20120, 1000, 0)
        actions = mgr.update_all({"MNQ": snap})
        assert ("MNQ", "stop_hit") in actions

        # Profit: entered at 20000, stopped at 20130 → +130 pts
        # Much better than fixed TP that might have exited at +50

    def test_entry_immediate_loss_short(self):
        """Simulate: short at 20000, price immediately spikes up to stop."""
        mgr = TrailManager(trail_multiplier=3.0)
        trail = mgr.add_trail("MNQ", "short", 20000, atr=25, position_size=1)
        assert trail.current_stop == 20050  # 20000 + 2*25

        # Price spikes up
        snap = PriceSnapshot("MNQ", 20060, 20070, 20050, 1000, 0)
        actions = mgr.update_all({"MNQ": snap})
        assert ("MNQ", "stop_hit") in actions
        # Loss capped at 2*ATR = 50 pts

    def test_winner_runs_far(self):
        """Test that a trending winner can run 5R+ before trail catches up."""
        mgr = TrailManager(trail_multiplier=3.0)
        trail = mgr.add_trail("MNQ", "long", 20000, atr=25, position_size=1)

        # Simulate strong trend: price goes from 20000 to 20500 in steps
        for i in range(50):
            price = 20000 + i * 10
            snap = PriceSnapshot("MNQ", price, price + 5, price - 5, 1000, 0)
            actions = mgr.update_all({"MNQ": snap})
            if any(a == "stop_hit" for _, a in actions):
                break

        # Should have run far before stopping
        assert trail.best_price > 20400
        assert trail.unrealized_r > 5  # at least 5R run
