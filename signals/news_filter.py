"""
Forex Factory economic calendar news filter.

Fetches the weekly economic calendar from Forex Factory (via
nfs.faireconomy.media) and blocks or penalizes new trade entries
around high-impact news events (FOMC, NFP, CPI, etc.).

Operates in two modes matching trend_filter.py:
  - gate: hard block new entries within ±N minutes of event
  - soft: allow entry but apply confidence penalty

Does NOT affect existing positions, profit-taking, or trailing stops.
"""

import json
import logging
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

FF_CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"


class NewsFilter:
    """Forex Factory economic calendar filter for trade gating."""

    def __init__(self, config: dict):
        self._config = config
        self._cache: Optional[List[dict]] = None
        self._last_fetch: float = 0
        self._cache_ttl = config.get("cache_ttl_seconds", 300)
        self._currencies = set(c.upper() for c in config.get("currencies", ["USD"]))
        self._high_window = config.get("high_impact_window_minutes", 15)
        self._med_window = config.get("medium_impact_window_minutes", 10)
        self._high_penalty = config.get("high_impact_penalty", 0.5)
        self._med_penalty = config.get("medium_impact_penalty", 0.7)

    def fetch_calendar(self) -> List[dict]:
        """Fetch this week's FF calendar. Returns cached if within TTL."""
        now = time.time()
        if self._cache is not None and (now - self._last_fetch) < self._cache_ttl:
            return self._cache

        try:
            req = urllib.request.Request(FF_CALENDAR_URL)
            req.add_header("User-Agent", "LaT-PFN-Trading/1.0")

            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = json.loads(resp.read().decode())

            # Filter to relevant currencies and non-Low impact
            events = []
            for entry in raw:
                country = entry.get("country", "").upper()
                impact = entry.get("impact", "").capitalize()
                if country not in self._currencies:
                    continue
                if impact not in ("High", "Medium"):
                    continue

                # Parse ISO 8601 date string
                date_str = entry.get("date", "")
                try:
                    event_dt = datetime.fromisoformat(date_str)
                    # Ensure timezone-aware (FF API returns ET offset)
                    if event_dt.tzinfo is None:
                        event_dt = event_dt.replace(tzinfo=timezone(timedelta(hours=-5)))
                except (ValueError, TypeError):
                    continue

                events.append({
                    "title": entry.get("title", "Unknown"),
                    "country": country,
                    "impact": impact,
                    "date": event_dt,
                    "forecast": entry.get("forecast", ""),
                    "previous": entry.get("previous", ""),
                })

            self._cache = events
            self._last_fetch = now
            logger.info(
                "News filter: fetched %d High/Medium USD events this week",
                len(events),
            )
            return events

        except Exception as e:
            logger.warning("News filter: calendar fetch failed: %s", e)
            return self._cache if self._cache is not None else []

    def get_nearby_events(self) -> List[dict]:
        """Return High/Medium events within their respective time windows of now."""
        events = self.fetch_calendar()
        now = datetime.now(timezone.utc)
        nearby = []

        for ev in events:
            ev_time = ev["date"].astimezone(timezone.utc)
            window = self._high_window if ev["impact"] == "High" else self._med_window
            delta = abs((now - ev_time).total_seconds()) / 60.0  # minutes

            if delta <= window:
                nearby.append({
                    **ev,
                    "minutes_away": round((ev_time - now).total_seconds() / 60.0, 1),
                })

        return nearby

    def check_news_clear(
        self, instrument: str, mode: str = "gate"
    ) -> Tuple[bool, str, float]:
        """Check if it's safe to open a new trade given upcoming news.

        Args:
            instrument: Trading instrument (for logging).
            mode: 'gate' = hard block, 'soft' = confidence penalty.

        Returns:
            (allowed, reason, confidence_multiplier)
        """
        nearby = self.get_nearby_events()

        if not nearby:
            return True, "clear — no upcoming High/Medium news events", 1.0

        # Find the highest-impact event in the window
        high_events = [e for e in nearby if e["impact"] == "High"]
        med_events = [e for e in nearby if e["impact"] == "Medium"]

        if high_events:
            ev = high_events[0]
            mins = ev["minutes_away"]
            direction = "in" if mins > 0 else "ago"
            abs_mins = abs(mins)
            detail = (
                f"HIGH impact: {ev['title']} "
                f"({abs_mins:.0f}min {direction})"
            )

            if mode == "gate":
                return False, f"BLOCKED — {detail}", 0.0
            else:
                return True, f"SOFT_PENALTY — {detail}", self._high_penalty

        if med_events:
            ev = med_events[0]
            mins = ev["minutes_away"]
            direction = "in" if mins > 0 else "ago"
            abs_mins = abs(mins)
            detail = (
                f"MEDIUM impact: {ev['title']} "
                f"({abs_mins:.0f}min {direction})"
            )

            if mode == "gate":
                return False, f"BLOCKED — {detail}", 0.0
            else:
                return True, f"SOFT_PENALTY — {detail}", self._med_penalty

        return True, "clear — no upcoming High/Medium news events", 1.0
