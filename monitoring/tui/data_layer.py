"""Data layer for the TUI — reads SQLite, JSON, and WebSocket."""

import asyncio
import json
import logging
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from polymarket.edge_engine import AdaptiveEdgeEngine, EdgeMetrics
from polymarket.websocket_feed import PriceUpdate, WebSocketFeed

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent.parent
DB_PATH = PROJECT_ROOT / "data" / "turbo_analytics.db"
POSITIONS_PATH = PROJECT_ROOT / "data" / "polymarket_positions.json"


@dataclass
class TradeRecord:
    """A single resolved or pending trade from the DB."""
    id: int
    timestamp: str
    asset: str
    timeframe: str
    direction: str
    entry_price: float
    result: Optional[str]
    pnl: Optional[float]
    signal_type: str
    intel_convergence: float
    intel_multiplier: float


class TUIWebSocketFeed(WebSocketFeed):
    """Extended feed that captures full L2 depth for the TUI."""

    def __init__(self):
        super().__init__()
        self._depth_callbacks: List[Callable] = []
        self._depth: Dict[str, Dict] = {}

    def on_depth(self, callback: Callable):
        self._depth_callbacks.append(callback)

    def get_depth(self, token_id: str) -> Optional[Dict]:
        return self._depth.get(token_id)

    def _process_message(self, raw: str):
        """Capture full L2 depth before calling parent."""
        try:
            data = json.loads(raw)
            msg_type = data.get("event_type", data.get("type", ""))
            if msg_type in ("book", "price_change"):
                token_id = data.get("asset_id", "")
                if token_id:
                    bids = data.get("bids", [])[:10]
                    asks = data.get("asks", [])[:10]
                    self._depth[token_id] = {"bids": bids, "asks": asks}
                    for cb in self._depth_callbacks:
                        try:
                            cb(token_id, bids, asks)
                        except Exception:
                            pass
        except Exception:
            pass
        super()._process_message(raw)


class DataManager:
    """Unified data access for the TUI."""

    def __init__(self):
        self.ws_feed = TUIWebSocketFeed()
        self._price_callbacks: List[Callable] = []
        self._depth_callbacks: List[Callable] = []
        self._subscribed_tokens: set = set()
        self.ws_connected = False
        self.edge_engine = AdaptiveEdgeEngine()

    async def start_ws(self, token_ids: Dict[str, str]):
        """Start WebSocket and subscribe to token_ids."""
        self.ws_feed.on_price(self._on_price)
        self.ws_feed.on_depth(self._on_depth)

        for tid in token_ids:
            await self.ws_feed.subscribe(tid)
            self._subscribed_tokens.add(tid)

        asyncio.create_task(self._run_ws())

    async def _run_ws(self):
        self.ws_connected = True
        try:
            await self.ws_feed.start()
        except Exception as e:
            logger.error("WS feed error: %s", e)
            self.ws_connected = False

    async def subscribe_token(self, token_id: str):
        if token_id not in self._subscribed_tokens:
            await self.ws_feed.subscribe(token_id)
            self._subscribed_tokens.add(token_id)

    def _on_price(self, update: PriceUpdate):
        for cb in self._price_callbacks:
            try:
                cb(update)
            except Exception:
                pass

    def _on_depth(self, token_id: str, bids: list, asks: list):
        for cb in self._depth_callbacks:
            try:
                cb(token_id, bids, asks)
            except Exception:
                pass

    def on_price(self, callback: Callable):
        self._price_callbacks.append(callback)

    def on_depth(self, callback: Callable):
        self._depth_callbacks.append(callback)

    def poll_db(self) -> Dict[str, Any]:
        """Read turbo analytics DB. Call from worker thread."""
        try:
            conn = sqlite3.connect(str(DB_PATH), timeout=1.0)
            conn.row_factory = sqlite3.Row

            # Recent trades (last 50 resolved)
            rows = conn.execute(
                """SELECT id, timestamp, asset, timeframe, signal_direction,
                          entry_price, result, pnl, signal_type,
                          intel_convergence, intel_multiplier
                   FROM turbo_signals
                   WHERE traded = 1 AND result IS NOT NULL
                   ORDER BY id DESC LIMIT 200"""
            ).fetchall()

            trades = [
                TradeRecord(
                    id=r["id"], timestamp=r["timestamp"],
                    asset=r["asset"], timeframe=r["timeframe"],
                    direction=r["signal_direction"] or "?",
                    entry_price=r["entry_price"] or 0,
                    result=r["result"], pnl=r["pnl"] or 0,
                    signal_type=r["signal_type"] or "unknown",
                    intel_convergence=r["intel_convergence"] or 0,
                    intel_multiplier=r["intel_multiplier"] or 1.0,
                )
                for r in rows
            ]

            # Scorecard (24h)
            cutoff_24h = time.strftime(
                "%Y-%m-%dT%H:%M:%SZ",
                time.gmtime(time.time() - 24 * 3600),
            )
            sc = conn.execute(
                """SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN traded=1 THEN 1 ELSE 0 END) as trades,
                    SUM(CASE WHEN result='win' THEN 1 ELSE 0 END) as wins,
                    SUM(CASE WHEN result='loss' THEN 1 ELSE 0 END) as losses,
                    SUM(CASE WHEN traded=1 AND result IS NOT NULL THEN pnl ELSE 0 END) as total_pnl
                   FROM turbo_signals WHERE timestamp >= ?""",
                (cutoff_24h,),
            ).fetchone()

            wins = sc["wins"] or 0
            losses = sc["losses"] or 0

            # Extended metrics: avg win, avg loss, best, worst
            ext = conn.execute(
                """SELECT
                    AVG(CASE WHEN result='win' THEN pnl END) as avg_win,
                    AVG(CASE WHEN result='loss' THEN pnl END) as avg_loss,
                    MAX(pnl) as best_trade,
                    MIN(pnl) as worst_trade
                   FROM turbo_signals
                   WHERE traded=1 AND result IS NOT NULL"""
            ).fetchone()

            avg_win = ext["avg_win"] or 0
            avg_loss = ext["avg_loss"] or 0
            payoff_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 0

            # Time-windowed PnL (1h, 6h)
            pnl_windows = {}
            for hrs, label in [(1, "1h"), (6, "6h")]:
                cutoff = time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ",
                    time.gmtime(time.time() - hrs * 3600),
                )
                r = conn.execute(
                    """SELECT SUM(pnl) as pnl, COUNT(*) as n
                       FROM turbo_signals
                       WHERE traded=1 AND result IS NOT NULL
                       AND timestamp >= ?""",
                    (cutoff,),
                ).fetchone()
                pnl_windows[label] = {
                    "pnl": round(r["pnl"] or 0, 2),
                    "trades": r["n"] or 0,
                }

            # Drawdown calculation
            pnl_rows = conn.execute(
                """SELECT pnl FROM turbo_signals
                   WHERE traded=1 AND result IS NOT NULL
                   ORDER BY id ASC"""
            ).fetchall()
            cumulative = []
            running = 0.0
            peak = 0.0
            max_dd = 0.0
            for r in pnl_rows:
                running += r["pnl"] or 0
                cumulative.append(round(running, 2))
                if running > peak:
                    peak = running
                dd = peak - running
                if dd > max_dd:
                    max_dd = dd
            current_dd = peak - running

            # Block rate
            edge_blocks = conn.execute(
                """SELECT COUNT(*) FROM turbo_signals
                   WHERE skip_reason LIKE 'edge_%'"""
            ).fetchone()[0]
            total_traded = conn.execute(
                """SELECT COUNT(*) FROM turbo_signals WHERE traded=1"""
            ).fetchone()[0]
            total_evals = conn.execute(
                """SELECT COUNT(*) FROM turbo_signals
                   WHERE signal_generated=1"""
            ).fetchone()[0]
            block_rate = edge_blocks / (edge_blocks + total_traded) if (edge_blocks + total_traded) > 0 else 0

            # Per-asset + direction breakdown
            asset_dir_rows = conn.execute(
                """SELECT asset, signal_direction as d,
                    SUM(CASE WHEN result='win' THEN 1 ELSE 0 END) as w,
                    SUM(CASE WHEN result='loss' THEN 1 ELSE 0 END) as l,
                    SUM(pnl) as pnl, AVG(entry_price) as avg_entry
                   FROM turbo_signals
                   WHERE traded=1 AND result IS NOT NULL
                   GROUP BY asset, signal_direction
                   ORDER BY SUM(pnl) DESC"""
            ).fetchall()
            asset_dir_stats = [
                {
                    "asset": r["asset"],
                    "direction": r["d"],
                    "wins": r["w"] or 0,
                    "losses": r["l"] or 0,
                    "pnl": round(r["pnl"] or 0, 2),
                    "avg_entry": round(r["avg_entry"] or 0, 3),
                }
                for r in asset_dir_rows
            ]

            # Trades per hour (velocity)
            first_ts = conn.execute(
                """SELECT MIN(timestamp) FROM turbo_signals
                   WHERE traded=1 AND result IS NOT NULL"""
            ).fetchone()[0]
            total_resolved = wins + losses
            hours_active = 1
            if first_ts:
                try:
                    from datetime import datetime, timezone
                    dt = datetime.fromisoformat(first_ts.replace("Z", "+00:00"))
                    hours_active = max(1, (time.time() - dt.timestamp()) / 3600)
                except Exception:
                    pass
            trades_per_hour = total_resolved / hours_active if hours_active > 0 else 0

            # Streak
            streak_rows = conn.execute(
                """SELECT result FROM turbo_signals
                   WHERE traded=1 AND result IS NOT NULL
                   ORDER BY id DESC LIMIT 20"""
            ).fetchall()
            streak = 0
            streak_type = ""
            if streak_rows:
                streak_type = streak_rows[0]["result"]
                for r in streak_rows:
                    if r["result"] == streak_type:
                        streak += 1
                    else:
                        break

            conn.close()

            # Kelly criterion: f* = (p * b - q) / b
            # where p = win_rate, q = 1-p, b = avg_win/|avg_loss|
            wr = wins / (wins + losses) if (wins + losses) > 0 else 0
            kelly_pct = 0
            if payoff_ratio > 0 and wr > 0:
                kelly_pct = max(0, (wr * payoff_ratio - (1 - wr)) / payoff_ratio)

            scorecard = {
                "evaluations": sc["total"] or 0,
                "trades": sc["trades"] or 0,
                "wins": wins,
                "losses": losses,
                "total_pnl": round(sc["total_pnl"] or 0, 2),
                "win_rate": round(wr * 100, 1),
                "streak": streak,
                "streak_type": streak_type,
                # Extended
                "avg_win": round(avg_win, 2),
                "avg_loss": round(avg_loss, 2),
                "payoff_ratio": round(payoff_ratio, 2),
                "best_trade": round(ext["best_trade"] or 0, 2),
                "worst_trade": round(ext["worst_trade"] or 0, 2),
                "max_drawdown": round(max_dd, 2),
                "current_dd": round(current_dd, 2),
                "peak_pnl": round(peak, 2),
                "kelly_pct": round(kelly_pct * 100, 1),
                "pnl_1h": pnl_windows.get("1h", {}).get("pnl", 0),
                "pnl_6h": pnl_windows.get("6h", {}).get("pnl", 0),
                "trades_1h": pnl_windows.get("1h", {}).get("trades", 0),
                "trades_6h": pnl_windows.get("6h", {}).get("trades", 0),
                "block_rate": round(block_rate * 100, 1),
                "edge_blocks": edge_blocks,
                "trades_per_hour": round(trades_per_hour, 1),
                "asset_dir_stats": asset_dir_stats,
            }

            return {
                "trades": trades,
                "scorecard": scorecard,
                "pnl_series": cumulative,
            }
        except Exception as e:
            return {"trades": [], "scorecard": {}, "pnl_series": [], "error": str(e)}

    def poll_edge_metrics(self) -> EdgeMetrics:
        """Read edge engine metrics. Call from worker thread."""
        self.edge_engine.refresh(force=True)
        return self.edge_engine.get_metrics()

    def poll_positions(self) -> List[Dict]:
        """Read polymarket_positions.json. Call from worker thread."""
        try:
            if not POSITIONS_PATH.exists():
                return []
            with open(POSITIONS_PATH) as f:
                data = json.load(f)
            if isinstance(data, list):
                return [
                    p for p in data
                    if p.get("status") == "open" and p.get("strategy") == "turbo"
                ]
            elif isinstance(data, dict):
                return [
                    v for v in data.values()
                    if isinstance(v, dict) and v.get("status") == "open" and v.get("strategy") == "turbo"
                ]
            return []
        except Exception:
            return []

    def poll_hl_data(self) -> Optional[Dict]:
        """
        Fetch Hyperliquid account data via API for TUI display.
        Call from worker thread (blocking API call).
        """
        try:
            import os
            address = os.getenv("HYPERLIQUID_WALLET_ADDRESS", "")
            if not address or address.startswith("your_"):
                return None

            from hyperliquid.info import Info
            from hyperliquid.utils import constants

            info = Info(constants.MAINNET_API_URL, skip_ws=True)
            state = info.user_state(address)

            margin = state.get("marginSummary", {})
            equity = float(margin.get("accountValue", 0))
            total_ntl = float(margin.get("totalNtlPos", 0))
            leverage = total_ntl / equity if equity > 0 else 0

            # Positions
            positions = {}
            total_unrealized = 0.0
            for p in state.get("assetPositions", []):
                pos = p.get("position", {})
                sz = float(pos.get("szi", 0))
                if sz == 0:
                    continue
                coin = pos.get("coin", "?")
                pnl = float(pos.get("unrealizedPnl", 0))
                total_unrealized += pnl
                margin_used = float(pos.get("marginUsed", 0))
                roe = pnl / margin_used if margin_used > 0 else 0
                positions[coin] = {
                    "size": sz,
                    "entry": float(pos.get("entryPx", 0)),
                    "pnl": pnl,
                    "roe": roe,
                    "notional": abs(float(pos.get("positionValue", 0))),
                }

            # Funding rates for core pairs
            funding_rates = {}
            try:
                meta_data = info.meta_and_asset_ctxs()
                universe = meta_data[0]["universe"]
                contexts = meta_data[1]
                for asset, ctx in zip(universe, contexts):
                    coin = asset["name"]
                    if coin in ("BTC", "ETH", "SOL", "XRP"):
                        rate = float(ctx.get("funding", 0))
                        funding_rates[coin.lower()] = {
                            "rate_8h": rate,
                            "annual": rate * 3 * 365,
                            "direction": "longs_pay" if rate > 0 else "shorts_pay",
                        }
            except Exception:
                pass

            # Read turbo WR from edge engine for cross-platform display
            turbo_wr = {}
            try:
                for asset in ("btc", "eth", "sol", "xrp"):
                    stats = self.edge_engine._metrics.asset_stats.get(asset)
                    if stats and stats.total >= 5:
                        turbo_wr[asset] = stats.wins / stats.total
            except Exception:
                pass

            # HL per-asset WR (from trade logger if available)
            hl_asset_wr = {}
            for coin, pos_data in positions.items():
                # Just show position ROE as a proxy
                hl_asset_wr[coin.lower()] = max(0, min(1, 0.5 + pos_data["roe"]))

            result = {
                "equity": equity,
                "leverage": leverage,
                "position_count": len(positions),
                "unrealized_pnl": total_unrealized,
                "positions": positions,
                "funding_rates": funding_rates,
                "turbo_asset_wr": turbo_wr,
                "hl_asset_wr": hl_asset_wr,
                "recent_actions": [],   # populated by position manager if running
                "gate_blocks": [],      # populated by risk module if running
            }

            return result

        except Exception as e:
            logger.debug("HL data poll failed: %s", e)
            return None
