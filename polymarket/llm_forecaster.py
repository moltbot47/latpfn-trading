"""
LLM Superforecaster — uses Claude API to estimate true probabilities
for Polymarket prediction markets.

Tracks calibration over time via Brier score.  Uses structured output
parsing to extract probability, confidence, and reasoning from the LLM.
"""

import asyncio
import json
import logging
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent.parent / "data" / "polymarket_forecasts.db"

SYSTEM_PROMPT = """You are a superforecaster calibrated on prediction markets.
You estimate probabilities for binary events. Your estimates should be
well-calibrated: when you say 70%, outcomes should occur ~70% of the time.

Rules:
- probability: Your best estimate that this resolves YES (0.0 to 1.0)
- confidence: How confident you are in your estimate (0.5 = very uncertain, 1.0 = very sure)
- reasoning: 2-3 sentence explanation of your estimate
- Consider base rates, recent news, historical analogies, and time remaining
- Be contrarian when evidence supports it — markets can misprice events
- Account for time pressure: events resolving soon have less uncertainty
- Do NOT anchor on the current market price — form your own independent estimate

You MUST respond with ONLY a JSON object in this exact format:
{"probability": 0.XX, "confidence": 0.XX, "reasoning": "Your explanation here."}"""


class LLMForecaster:
    """Claude-powered probability estimator for prediction markets."""

    def __init__(self, config: dict):
        pm_cfg = config.get("polymarket", {})
        fc_cfg = pm_cfg.get("forecaster", {})
        self.model = fc_cfg.get("model", "claude-sonnet-4-6")
        self.cache_hours = fc_cfg.get("cache_hours", 4)
        self._client = None
        self._no_api_key_warned = False
        self._db: Optional[sqlite3.Connection] = None
        self._cache: Dict[str, Tuple[float, Dict]] = {}  # market_id → (timestamp, forecast)
        self._init_db()

    def _init_db(self):
        """Initialize SQLite database for forecast tracking."""
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(DB_PATH))
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS forecasts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                market_id TEXT NOT NULL,
                question TEXT,
                llm_probability REAL,
                llm_confidence REAL,
                market_price REAL,
                reasoning TEXT,
                model TEXT,
                timestamp TEXT,
                outcome REAL DEFAULT NULL,
                resolved_at TEXT DEFAULT NULL
            )
        """)
        self._db.execute("""
            CREATE INDEX IF NOT EXISTS idx_forecasts_market
            ON forecasts(market_id)
        """)
        self._db.commit()

    def _get_anthropic_client(self):
        """Lazy-initialize Anthropic client."""
        if self._client is None:
            import anthropic
            api_key = os.getenv("ANTHROPIC_API_KEY", "")
            if not api_key:
                if not self._no_api_key_warned:
                    logger.warning(
                        "ANTHROPIC_API_KEY not set — LLM forecaster disabled. "
                        "Add your key to .env to enable superforecaster strategy."
                    )
                    self._no_api_key_warned = True
                raise RuntimeError("ANTHROPIC_API_KEY not set")
            self._client = anthropic.Anthropic(api_key=api_key)
        return self._client

    async def forecast(
        self,
        question: str,
        market_id: str = "",
        market_price: float = 0.5,
        end_date: str = "",
        category: str = "",
    ) -> Dict:
        """
        Estimate the true probability of a market resolving YES.

        Args:
            question:     The market question text.
            market_id:    Polymarket condition ID.
            market_price: Current YES token price (for logging, NOT shown to LLM).
            end_date:     ISO timestamp of market resolution.
            category:     Market category (Politics, Crypto, Sports, etc.).

        Returns:
            {"probability": float, "confidence": float, "reasoning": str}
        """
        # Check cache
        if market_id and market_id in self._cache:
            cached_time, cached_result = self._cache[market_id]
            age_hours = (time.time() - cached_time) / 3600
            if age_hours < self.cache_hours:
                logger.debug("Cache hit for %s (%.1fh old)", market_id[:12], age_hours)
                return cached_result

        # Build user prompt (deliberately exclude market price to avoid anchoring)
        user_msg = self._build_user_prompt(question, end_date, category)

        # Call Claude API
        try:
            result = await asyncio.to_thread(
                self._call_claude, user_msg
            )
        except RuntimeError as e:
            if "ANTHROPIC_API_KEY" in str(e):
                return {"probability": 0.5, "confidence": 0.0, "reasoning": "API key not configured"}
            logger.error("LLM forecast failed for '%s': %s", question[:50], e)
            return {"probability": 0.5, "confidence": 0.0, "reasoning": f"Error: {e}"}
        except Exception as e:
            logger.error("LLM forecast failed for '%s': %s", question[:50], e)
            return {"probability": 0.5, "confidence": 0.0, "reasoning": f"Error: {e}"}

        # Cache result
        if market_id:
            self._cache[market_id] = (time.time(), result)

        # Log to database
        self._log_forecast(market_id, question, result, market_price)

        logger.info(
            "Forecast: '%s' → P=%.2f (conf=%.2f)  market=%.2f  div=%+.2f",
            question[:50], result["probability"], result["confidence"],
            market_price, result["probability"] - market_price,
        )
        return result

    async def batch_forecast(
        self,
        markets: List[Dict],
        max_concurrent: int = 5,
    ) -> Dict[str, Dict]:
        """
        Forecast multiple markets concurrently.

        Args:
            markets: List of market dicts with 'market_id', 'question',
                     'yes_price', 'end_date', 'category' keys.
            max_concurrent: Max parallel API calls.

        Returns:
            Dict of market_id → forecast result.
        """
        # Quick check: if no API key, skip all forecasts
        if not os.getenv("ANTHROPIC_API_KEY", ""):
            if not self._no_api_key_warned:
                logger.warning(
                    "ANTHROPIC_API_KEY not set — LLM forecaster disabled. "
                    "Add your key to .env to enable superforecaster strategy."
                )
                self._no_api_key_warned = True
            return {m["market_id"]: {"probability": 0.5, "confidence": 0.0, "reasoning": "API key not configured"} for m in markets}

        semaphore = asyncio.Semaphore(max_concurrent)
        results = {}

        async def _forecast_one(m):
            async with semaphore:
                result = await self.forecast(
                    question=m["question"],
                    market_id=m["market_id"],
                    market_price=m.get("yes_price", 0.5),
                    end_date=m.get("end_date", ""),
                    category=m.get("category", ""),
                )
                results[m["market_id"]] = result

        tasks = [_forecast_one(m) for m in markets]
        await asyncio.gather(*tasks, return_exceptions=True)

        logger.info(
            "Batch forecast complete: %d/%d markets", len(results), len(markets)
        )
        return results

    def _build_user_prompt(
        self, question: str, end_date: str, category: str
    ) -> str:
        """Build user prompt for Claude. No market price to avoid anchoring."""
        parts = [f"Question: {question}"]
        if category:
            parts.append(f"Category: {category}")
        if end_date:
            try:
                end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
                now = datetime.now(timezone.utc)
                delta = end_dt - now
                days_left = delta.total_seconds() / 86400
                if days_left < 1:
                    parts.append(f"Time remaining: {delta.total_seconds() / 3600:.1f} hours")
                else:
                    parts.append(f"Time remaining: {days_left:.1f} days")
                parts.append(f"Resolution date: {end_date}")
            except (ValueError, TypeError):
                parts.append(f"Resolution date: {end_date}")
        parts.append(
            f"\nToday's date: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
        )
        parts.append(
            "\nEstimate the probability this resolves YES. "
            "Respond with ONLY the JSON object."
        )
        return "\n".join(parts)

    def _call_claude(self, user_msg: str) -> Dict:
        """Synchronous Claude API call (run in thread)."""
        client = self._get_anthropic_client()
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            temperature=0,
            system=SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": user_msg + "\n\nRespond with ONLY the JSON object, nothing else."},
            ],
        )
        # Extract text from all content blocks (skip thinking blocks)
        text = ""
        for block in response.content:
            if hasattr(block, "text"):
                text += block.text
        text = text.strip()
        return self._parse_response(text)

    def _parse_response(self, text: str) -> Dict:
        """Extract probability, confidence, reasoning from Claude output."""
        # Try direct JSON parse
        try:
            # Handle markdown code blocks
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()
            data = json.loads(text)
            return {
                "probability": float(data.get("probability", 0.5)),
                "confidence": float(data.get("confidence", 0.5)),
                "reasoning": str(data.get("reasoning", "")),
            }
        except (json.JSONDecodeError, KeyError, TypeError):
            pass

        # Fallback: extract JSON from text (greedy match for nested braces)
        import re
        json_match = re.search(r'\{[^{}]*"probability"[^{}]*\}', text, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group())
                return {
                    "probability": float(data.get("probability", 0.5)),
                    "confidence": float(data.get("confidence", 0.5)),
                    "reasoning": str(data.get("reasoning", "")),
                }
            except (json.JSONDecodeError, KeyError, TypeError):
                pass

        logger.warning("Failed to parse LLM response: %s", text[:200])
        return {"probability": 0.5, "confidence": 0.0, "reasoning": f"Parse error: {text[:100]}"}

    # ── Forecast logging & Brier score ───────────────────────────────

    def _log_forecast(
        self, market_id: str, question: str, forecast: Dict, market_price: float
    ):
        """Record forecast to SQLite."""
        if not self._db:
            return
        try:
            self._db.execute(
                """INSERT INTO forecasts
                   (market_id, question, llm_probability, llm_confidence,
                    market_price, reasoning, model, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    market_id,
                    question,
                    forecast["probability"],
                    forecast["confidence"],
                    market_price,
                    forecast.get("reasoning", ""),
                    self.model,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            self._db.commit()
        except Exception as e:
            logger.error("Failed to log forecast: %s", e)

    def log_resolution(self, market_id: str, outcome: float):
        """
        Record actual outcome for a market.

        Args:
            market_id: Polymarket condition ID.
            outcome:   1.0 if resolved YES, 0.0 if resolved NO.
        """
        if not self._db:
            return
        try:
            self._db.execute(
                """UPDATE forecasts SET outcome = ?, resolved_at = ?
                   WHERE market_id = ? AND outcome IS NULL""",
                (outcome, datetime.now(timezone.utc).isoformat(), market_id),
            )
            self._db.commit()
            logger.info("Resolution logged: %s → %s", market_id[:12], "YES" if outcome == 1 else "NO")
        except Exception as e:
            logger.error("Failed to log resolution: %s", e)

    def compute_brier_score(self, days: int = 30) -> Optional[float]:
        """
        Compute Brier score over recent resolved forecasts.

        Brier score = mean((probability - outcome)^2)
        0.0 = perfect, 0.25 = random, 0.5 = always wrong.

        Returns None if insufficient data.
        """
        if not self._db:
            return None
        try:
            cutoff = datetime.now(timezone.utc)
            from datetime import timedelta
            cutoff = (cutoff - timedelta(days=days)).isoformat()

            rows = self._db.execute(
                """SELECT llm_probability, outcome FROM forecasts
                   WHERE outcome IS NOT NULL AND timestamp >= ?""",
                (cutoff,),
            ).fetchall()

            if len(rows) < 5:
                return None

            brier = sum((p - o) ** 2 for p, o in rows) / len(rows)
            logger.info("Brier score (last %d days, %d forecasts): %.4f", days, len(rows), brier)
            return brier
        except Exception as e:
            logger.error("Brier score computation failed: %s", e)
            return None

    def get_calibration_curve(self, buckets: int = 10) -> Dict[str, float]:
        """
        Compute calibration curve: for each probability bucket, what's
        the actual win rate?

        Returns dict of "0.X-0.Y" → actual_rate.
        """
        if not self._db:
            return {}
        try:
            rows = self._db.execute(
                "SELECT llm_probability, outcome FROM forecasts WHERE outcome IS NOT NULL"
            ).fetchall()

            if len(rows) < 10:
                return {}

            bucket_size = 1.0 / buckets
            curve = {}
            for i in range(buckets):
                low = i * bucket_size
                high = (i + 1) * bucket_size
                bucket_rows = [(p, o) for p, o in rows if low <= p < high]
                if bucket_rows:
                    actual_rate = sum(o for _, o in bucket_rows) / len(bucket_rows)
                    curve[f"{low:.1f}-{high:.1f}"] = round(actual_rate, 3)

            return curve
        except Exception as e:
            logger.error("Calibration curve failed: %s", e)
            return {}

    def get_forecast_stats(self) -> Dict:
        """Get summary statistics for all forecasts."""
        if not self._db:
            return {}
        try:
            total = self._db.execute("SELECT COUNT(*) FROM forecasts").fetchone()[0]
            resolved = self._db.execute(
                "SELECT COUNT(*) FROM forecasts WHERE outcome IS NOT NULL"
            ).fetchone()[0]
            brier = self.compute_brier_score()

            return {
                "total_forecasts": total,
                "resolved": resolved,
                "unresolved": total - resolved,
                "brier_score": brier,
                "calibration": self.get_calibration_curve(),
            }
        except Exception:
            return {}
