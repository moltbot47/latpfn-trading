"""
Time-based confidence boost for trading signals.

Applies a confidence multiplier during high-edge time windows:
- Pre-market macro (8:25-8:35 ET): CPI, jobs, GDP releases
- NYSE open (9:30-10:00 ET): Institutional flow spike
- Open continuation (10:00-10:30 ET): Trend follow-through
- Lunch dead zone (12:00-14:00 ET): Low volume, choppy
- Power hour (15:30-16:00 ET): End-of-day flow

Also provides dynamic cycle speed: 2min during hot windows vs 5min default.
"""

import logging
from datetime import datetime, time as dtime
from typing import Tuple

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# Asset class mapping for boost selection (crypto vs CME)
_CRYPTO_INSTRUMENTS = {"MBT", "MET", "BTC", "ETH", "SOL", "BTCUSDT", "ETHUSDT", "SOLUSDT"}

# Default time windows (ET) with boost multipliers
_DEFAULT_WINDOWS = [
    {
        "name": "pre_macro",
        "label": "Pre-Market Macro",
        "start": dtime(8, 25),
        "end": dtime(8, 35),
        "cme_boost": 1.20,
        "crypto_boost": 1.15,
    },
    {
        "name": "nyse_open",
        "label": "NYSE Open",
        "start": dtime(9, 30),
        "end": dtime(10, 0),
        "cme_boost": 1.25,
        "crypto_boost": 1.20,
    },
    {
        "name": "open_continuation",
        "label": "Open Continuation",
        "start": dtime(10, 0),
        "end": dtime(10, 30),
        "cme_boost": 1.15,
        "crypto_boost": 1.10,
    },
    {
        "name": "lunch_zone",
        "label": "Lunch Dead Zone",
        "start": dtime(12, 0),
        "end": dtime(14, 0),
        "cme_boost": 0.85,
        "crypto_boost": 0.90,
    },
    {
        "name": "power_hour",
        "label": "Power Hour",
        "start": dtime(15, 30),
        "end": dtime(16, 0),
        "cme_boost": 1.10,
        "crypto_boost": 1.05,
    },
]

# Windows that trigger faster cycle intervals
_FAST_CYCLE_WINDOWS = {"nyse_open", "open_continuation", "pre_macro"}

_ET = ZoneInfo("America/New_York")


def _is_crypto(instrument: str) -> bool:
    """Check if instrument is a crypto asset."""
    return instrument.upper() in _CRYPTO_INSTRUMENTS


def _load_windows(config: dict) -> list:
    """Load time windows from config, falling back to defaults."""
    tb_cfg = config.get("signal", {}).get("time_boost", {})
    if not tb_cfg.get("enabled", True):
        return []

    custom_windows = tb_cfg.get("windows")
    if not custom_windows:
        return _DEFAULT_WINDOWS

    windows = []
    for name, w in custom_windows.items():
        try:
            start_parts = w["start"].split(":")
            end_parts = w["end"].split(":")
            windows.append({
                "name": name,
                "label": name.replace("_", " ").title(),
                "start": dtime(int(start_parts[0]), int(start_parts[1])),
                "end": dtime(int(end_parts[0]), int(end_parts[1])),
                "cme_boost": w.get("cme_boost", 1.0),
                "crypto_boost": w.get("crypto_boost", 1.0),
            })
        except (KeyError, ValueError) as e:
            logger.warning("Invalid time_boost window '%s': %s", name, e)
    return windows


def get_time_boost(instrument: str, config: dict) -> Tuple[float, str]:
    """Return (multiplier, window_name) based on current ET time.

    Args:
        instrument: Trading instrument symbol (e.g. 'MNQ', 'BTC').
        config: Full system config dict.

    Returns:
        Tuple of (boost_multiplier, window_name).
        multiplier > 1.0 during high-edge windows, < 1.0 during dead zones.
        window_name is empty string when no special window is active.
    """
    windows = _load_windows(config)
    if not windows:
        return 1.0, ""

    now_et = datetime.now(_ET).time()
    is_crypto = _is_crypto(instrument)

    for w in windows:
        if w["start"] <= now_et < w["end"]:
            boost = w["crypto_boost"] if is_crypto else w["cme_boost"]
            return boost, w["label"]

    return 1.0, ""


def get_cycle_interval(base_interval: int, config: dict) -> int:
    """Return dynamic cycle interval based on current time window.

    During high-volatility windows (NYSE open, pre-macro), reduces cycle
    from the base interval (typically 5min) to a faster interval (2min)
    to capture more signals during peak edge periods.

    Args:
        base_interval: Normal cycle interval in minutes.
        config: Full system config dict.

    Returns:
        Cycle interval in minutes (may be shorter during hot windows).
    """
    tb_cfg = config.get("signal", {}).get("time_boost", {})
    if not tb_cfg.get("enabled", True):
        return base_interval

    fast_minutes = tb_cfg.get("fast_cycle_minutes", 2)
    fast_window_names = set(tb_cfg.get("fast_cycle_windows", list(_FAST_CYCLE_WINDOWS)))

    windows = _load_windows(config)
    now_et = datetime.now(_ET).time()

    for w in windows:
        if w["start"] <= now_et < w["end"] and w["name"] in fast_window_names:
            return fast_minutes

    return base_interval


def get_active_window(config: dict) -> str:
    """Return the name of the currently active time window, or empty string."""
    windows = _load_windows(config)
    now_et = datetime.now(_ET).time()

    for w in windows:
        if w["start"] <= now_et < w["end"]:
            return w["name"]
    return ""
