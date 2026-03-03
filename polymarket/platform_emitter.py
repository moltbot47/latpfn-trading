"""
Real-time event emitter for the Agent Platform.

Sends Turbo strategy events (signals, trades, resolutions) to the
Agent Platform REST API, which broadcasts them via WebSocket to the
live dashboard at https://backend-production-6a0e.up.railway.app
"""

import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import requests

logger = logging.getLogger(__name__)

PLATFORM_URL = os.environ.get(
    "PLATFORM_URL", "https://backend-production-6a0e.up.railway.app"
)
API_KEY = os.environ.get("PLATFORM_API_KEY", "")


class PlatformEmitter:
    """Non-blocking event emitter for the Agent Platform."""

    def __init__(
        self,
        base_url: str = PLATFORM_URL,
        api_key: str = API_KEY,
        enabled: bool = True,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.enabled = enabled
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        })
        self._pool = ThreadPoolExecutor(max_workers=4)
        self._lock = threading.Lock()
        self._last_heartbeat = 0.0
        self._last_price_fetch = 0.0
        self._error_count = 0
        self._max_errors = 10  # Back off after 10 consecutive errors
        # Throttle: track last momentum emit per asset to avoid noise
        self._last_momentum: dict[str, float] = {}
        self._momentum_interval = 300  # Only emit momentum blocks every 5 min per asset

    def emit(
        self,
        event_type: str,
        outcome: str,
        instrument: str = "",
        confidence: Optional[float] = None,
        payload: Optional[dict] = None,
        cycle_id: str = "",
        duration_ms: Optional[int] = None,
    ):
        """Queue and send an event (non-blocking via thread)."""
        if not self.enabled or self._error_count >= self._max_errors:
            return

        event = {
            "event_type": event_type,
            "outcome": outcome,
            "instrument": instrument,
        }
        if confidence is not None:
            event["confidence"] = round(confidence, 4)
        if payload:
            event["payload"] = payload
        if cycle_id:
            event["cycle_id"] = cycle_id
        if duration_ms is not None:
            event["duration_ms"] = duration_ms

        # Fire-and-forget in bounded thread pool
        self._pool.submit(self._send, event)

    def emit_batch(self, events: list):
        """Send multiple events at once (non-blocking)."""
        if not self.enabled or not events or self._error_count >= self._max_errors:
            return
        self._pool.submit(self._send_batch, events)

    def heartbeat(self):
        """Send a heartbeat (rate-limited to once per 60s)."""
        now = time.time()
        if now - self._last_heartbeat < 60:
            return
        self._last_heartbeat = now
        self._pool.submit(self._send_heartbeat)

    def _send(self, event: dict):
        try:
            resp = self._session.post(
                f"{self.base_url}/api/v1/events/",
                json=event,
                timeout=5,
            )
            if resp.status_code == 201:
                self._error_count = 0
            else:
                self._error_count += 1
                logger.debug("[PLATFORM] Event rejected: %d %s", resp.status_code, resp.text[:100])
        except Exception as e:
            self._error_count += 1
            logger.debug("[PLATFORM] Send failed: %s", e)

    def _send_batch(self, events: list):
        try:
            resp = self._session.post(
                f"{self.base_url}/api/v1/events/batch/",
                json={"events": events},
                timeout=10,
            )
            if resp.status_code == 201:
                self._error_count = 0
            else:
                self._error_count += 1
        except Exception:
            self._error_count += 1

    def _send_heartbeat(self):
        try:
            self._session.post(
                f"{self.base_url}/api/v1/heartbeat/",
                json={},
                timeout=5,
            )
            self._error_count = 0
        except Exception:
            pass

    # ── Convenience methods for Turbo events ──────────────────

    def signal_check(
        self,
        asset: str,
        tf: str,
        momentum: dict,
        signal: Optional[dict],
        skip_reason: str = "",
    ):
        """Emit a signal evaluation event.

        Throttles momentum BLOCK events to once per asset per 5 minutes
        to avoid flooding the live feed. Signal PASS events always emit.
        """
        outcome = "pass" if signal else "block"
        is_signal = bool(signal)
        key = f"{asset}_{tf}"

        # Throttle momentum blocks — only emit every N seconds per asset
        if not is_signal:
            now = time.time()
            last = self._last_momentum.get(key, 0)
            if now - last < self._momentum_interval:
                return  # Skip this noisy momentum block
            self._last_momentum[key] = now

        direction = signal["direction"] if signal else momentum.get("direction", "")
        self.emit(
            event_type="momentum" if not is_signal else "signal",
            outcome=outcome,
            instrument=f"{asset.upper()}-{tf}",
            confidence=momentum.get("strength", 0),
            cycle_id=f"turbo_{asset}_{tf}_{int(time.time())}",
            payload={
                "direction": direction,
                "momentum_1m": round(momentum.get("pct_change_1m", 0), 6),
                "momentum_3m": round(momentum.get("pct_change_3m", 0), 6),
                "strength": round(momentum.get("strength", 0), 4),
                "skip_reason": skip_reason,
                "signal_type": signal.get("signal_type", "") if signal else "",
                "signal_reason": signal.get("reason", "") if signal else "",
            },
        )

    def trade_executed(
        self,
        asset: str,
        tf: str,
        direction: str,
        entry_price: float,
        shares: float,
        size_usdc: float,
        reason: str,
        cycle_id: str = "",
    ):
        """Emit a trade execution event."""
        self.emit(
            event_type="execution",
            outcome="pass",
            instrument=f"{asset.upper()}-{tf}",
            confidence=1.0 - entry_price,  # Edge as confidence
            cycle_id=cycle_id or f"turbo_{asset}_{tf}_{int(time.time())}",
            payload={
                "direction": direction,
                "entry_price": round(entry_price, 4),
                "shares": round(shares, 1),
                "size_usdc": round(size_usdc, 2),
                "signal_reason": reason,
            },
        )

    def trade_resolved(
        self,
        asset: str,
        tf: str,
        direction: str,
        outcome_price: float,
        pnl: float,
        session_pnl: float,
        cycle_id: str = "",
    ):
        """Emit a resolution event."""
        won = outcome_price > 0.5
        self.emit(
            event_type="resolution",
            outcome="win" if won else "loss",
            instrument=f"{asset.upper()}-{tf}",
            cycle_id=cycle_id or f"turbo_{asset}_{tf}_{int(time.time())}",
            payload={
                "direction": direction,
                "result": "WIN" if won else "LOSS",
                "pnl": round(pnl, 4),
                "session_pnl": round(session_pnl, 4),
                "outcome_price": round(outcome_price, 2),
            },
        )

    def price_fetch(self, assets: dict):
        """Emit a price fetch event with current prices (throttled to 5 min)."""
        now = time.time()
        if now - self._last_price_fetch < 300:
            return
        self._last_price_fetch = now

        prices = {}
        for asset, history in assets.items():
            if history:
                prices[asset] = round(history[-1].price, 2)
        if prices:
            self.emit(
                event_type="price_fetch",
                outcome="pass",
                instrument="CRYPTO",
                payload=prices,
            )

    def edge_gate(self, asset: str, direction: str, allowed: bool, reason: str):
        """Emit an edge gate decision. Only emits PASS (allowed) events."""
        if not allowed:
            return  # Don't emit edge gate blocks — too noisy
        self.emit(
            event_type="edge_gate",
            outcome="pass",
            instrument=f"{asset.upper()}",
            payload={
                "direction": direction,
                "reason": reason,
            },
        )


# Module-level singleton
_emitter: Optional[PlatformEmitter] = None


def get_emitter() -> PlatformEmitter:
    """Get or create the global emitter instance."""
    global _emitter
    if _emitter is None:
        _emitter = PlatformEmitter()
    return _emitter
