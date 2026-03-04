"""Trading Command Center — unified multi-platform TUI dashboard.

Tabs:
  1. Overview   — cross-platform portfolio summary
  2. CME        — Apex futures (MNQ, MYM, MES, MBT)
  3. HL         — Hyperliquid crypto perpetuals
  4. Poly       — Polymarket turbo contrarian
  5. Strategies — per-strategy performance + decay monitoring
  6. Backtest   — run backtests as subprocesses with live output
  7. Alerts     — live alert feed with severity filtering
  8. Risk       — Apex drawdown gauge, daily limits, consistency

Keybindings:
  1-8 = switch tabs, q = quit, r = refresh, d = theme, escape = back
"""

import asyncio

from textual.app import App, ComposeResult
from textual.widgets import Footer, TabbedContent, TabPane

from monitoring.tui.alerts import AlertEngine
from monitoring.tui.data_layer import DataManager
from monitoring.tui.tabs.alerts_tab import AlertsTab
from monitoring.tui.tabs.backtest_tab import BacktestTab
from monitoring.tui.tabs.cme_tab import CMETab
from monitoring.tui.tabs.hyperliquid_tab import HyperliquidTab
from monitoring.tui.tabs.overview import OverviewTab
from monitoring.tui.tabs.polymarket_tab import PolymarketTab
from monitoring.tui.tabs.risk_tab import RiskTab
from monitoring.tui.tabs.strategies_tab import StrategiesTab
from monitoring.tui.widgets.header_bar import GlobalHeader


class CommandCenter(App):
    """Multi-platform trading command center."""

    TITLE = "TRADING COMMAND CENTER"
    CSS_PATH = "command_center.tcss"
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "refresh", "Refresh"),
        ("d", "toggle_dark", "Theme"),
        ("1", "tab_1", "Overview"),
        ("2", "tab_2", "CME"),
        ("3", "tab_3", "HL"),
        ("4", "tab_4", "Poly"),
        ("5", "tab_5", "Strategies"),
        ("6", "tab_6", "Backtest"),
        ("7", "tab_7", "Alerts"),
        ("8", "tab_8", "Risk"),
        ("escape", "back", "Back"),
    ]

    def __init__(self):
        super().__init__()
        self.data_mgr = DataManager()
        self.alert_engine = AlertEngine()

        # Caches
        self._portfolio_cache = {}
        self._cme_data_cache = {}
        self._cme_positions_cache = []
        self._poly_data_cache = {}
        self._poly_positions_cache = []
        self._poly_edge_cache = None
        self._hl_cache = None
        self._strategies_cache = []
        self._bot_status_cache = {}

        # Poll counters (HL is slower to avoid API limits)
        self._poll_count = 0

    def compose(self) -> ComposeResult:
        yield GlobalHeader(id="global-header")
        with TabbedContent(id="main-tabs"):
            with TabPane("Overview", id="tab-overview"):
                yield OverviewTab(id="overview-tab")
            with TabPane("CME", id="tab-cme"):
                yield CMETab(id="cme-tab")
            with TabPane("Hyperliquid", id="tab-hl"):
                yield HyperliquidTab(id="hl-tab")
            with TabPane("Polymarket", id="tab-poly"):
                yield PolymarketTab(id="poly-tab")
            with TabPane("Strategies", id="tab-strategies"):
                yield StrategiesTab(id="strategies-tab")
            with TabPane("Backtest", id="tab-backtest"):
                yield BacktestTab(id="backtest-tab")
            with TabPane("Alerts", id="tab-alerts"):
                yield AlertsTab(id="alerts-tab")
            with TabPane("Risk", id="tab-risk"):
                yield RiskTab(id="risk-tab")
        yield Footer()

    def on_mount(self):
        # Initial data load after short delay, then poll on interval
        self.set_timer(1.0, self._do_poll)
        self.set_interval(2.0, self._do_poll)
        # 1-second tick for header clock + position timers
        self.set_interval(1.0, self._tick_second)

    # ── Tab switching ─────────────────────────────────────────

    def _switch_tab(self, tab_id: str):
        try:
            tabs = self.query_one("#main-tabs", TabbedContent)
            tabs.active = tab_id
        except Exception:
            pass

    def action_tab_1(self):
        self._switch_tab("tab-overview")

    def action_tab_2(self):
        self._switch_tab("tab-cme")

    def action_tab_3(self):
        self._switch_tab("tab-hl")

    def action_tab_4(self):
        self._switch_tab("tab-poly")

    def action_tab_5(self):
        self._switch_tab("tab-strategies")

    def action_tab_6(self):
        self._switch_tab("tab-backtest")

    def action_tab_7(self):
        self._switch_tab("tab-alerts")

    def action_tab_8(self):
        self._switch_tab("tab-risk")

    def action_back(self):
        """Dismiss any modal or go back to overview."""
        if len(self.screen_stack) > 1:
            self.pop_screen()
        else:
            self._switch_tab("tab-overview")

    def action_refresh(self):
        asyncio.create_task(self._do_poll())

    # ── Alert ack handler ──────────────────────────────────────

    def on_alerts_tab_ack_all(self, message: AlertsTab.AckAll):
        self.alert_engine.acknowledge_all()

    # ── 1-second tick ─────────────────────────────────────────

    def _tick_second(self):
        """Update header clock and position timers."""
        self._update_header()
        # Refresh poly positions (live countdown timers)
        active = self._active_tab()
        if active == "tab-poly" and self._poly_positions_cache:
            try:
                self.query_one("#poly-tab", PolymarketTab).update_positions(
                    self._poly_positions_cache
                )
            except Exception:
                pass

    # ── 2-second polling ──────────────────────────────────────

    async def _do_poll(self):
        self._poll_count += 1
        active = self._active_tab()

        # Always poll overview-level data
        await self._poll_cme()
        await self._poll_poly()

        # HL only every 5 cycles (~10s) to respect rate limits
        if self._poll_count % 5 == 0:
            await self._poll_hl()

        # Strategies only every 15 cycles (~30s) since it's expensive
        if self._poll_count % 15 == 0:
            await self._poll_strategies()

        # Bot status every 10 cycles (~20s)
        if self._poll_count % 10 == 1:
            await self._poll_bot_status()

        # Run alert engine every 5 cycles (~10s)
        if self._poll_count % 5 == 0:
            self._run_alerts()

        # Update active tab
        self._render_active_tab(active)

        # Update header with latest data
        self._update_header()

    async def _poll_cme(self):
        try:
            self._cme_data_cache = await asyncio.to_thread(
                self.data_mgr.poll_cme_trades
            )
        except Exception:
            pass
        try:
            self._cme_positions_cache = await asyncio.to_thread(
                self.data_mgr.poll_cme_positions
            )
        except Exception:
            pass

    async def _poll_poly(self):
        try:
            self._poly_data_cache = await asyncio.to_thread(
                self.data_mgr.poll_db
            )
        except Exception:
            pass
        try:
            self._poly_positions_cache = await asyncio.to_thread(
                self.data_mgr.poll_positions
            )
        except Exception:
            pass
        try:
            self._poly_edge_cache = await asyncio.to_thread(
                self.data_mgr.poll_edge_metrics
            )
        except Exception:
            pass

    async def _poll_hl(self):
        try:
            self._hl_cache = await asyncio.to_thread(
                self.data_mgr.poll_hl_data
            )
        except Exception:
            pass

    async def _poll_strategies(self):
        try:
            self._strategies_cache = await asyncio.to_thread(
                self.data_mgr.poll_strategies
            )
        except Exception:
            pass

    async def _poll_bot_status(self):
        try:
            self._bot_status_cache = await asyncio.to_thread(
                self.data_mgr.poll_bot_status
            )
        except Exception:
            pass

    # ── Alert engine ───────────────────────────────────────────

    def _run_alerts(self):
        """Evaluate all alert rules against current cached data."""
        cme_sc = self._cme_data_cache.get("scorecard", {})
        cme_trades = self._cme_data_cache.get("trades", [])

        self.alert_engine.evaluate_all(
            strategies=self._strategies_cache,
            bot_statuses=self._bot_status_cache,
            cme_scorecard=cme_sc,
            daily_pnl=cme_sc.get("total_pnl", 0),
            recent_trades=cme_trades,
        )

        # Live drawdown check with actual equity
        cme_equity = 50000 + cme_sc.get("total_pnl", 0)
        try:
            import json
            from monitoring.tui.alerts import DRAWDOWN_STATE_PATH
            if DRAWDOWN_STATE_PATH.exists():
                with open(DRAWDOWN_STATE_PATH) as f:
                    ds = json.load(f)
                floor = ds.get("drawdown_floor", 47500)
                self.alert_engine.evaluate_drawdown_live(cme_equity, floor)
        except Exception:
            pass

    # ── Render active tab ─────────────────────────────────────

    def _active_tab(self) -> str:
        try:
            return self.query_one("#main-tabs", TabbedContent).active
        except Exception:
            return "tab-overview"

    def _render_active_tab(self, active: str):
        try:
            if active == "tab-overview":
                self._render_overview()
            elif active == "tab-cme":
                self._render_cme()
            elif active == "tab-hl":
                self._render_hl()
            elif active == "tab-poly":
                self._render_poly()
            elif active == "tab-strategies":
                self._render_strategies()
            elif active == "tab-alerts":
                self._render_alerts()
            elif active == "tab-risk":
                self._render_risk()
        except Exception:
            pass

    def _render_overview(self):
        overview = self.query_one("#overview-tab", OverviewTab)

        # Build portfolio summary
        cme_sc = self._cme_data_cache.get("scorecard", {})
        poly_sc = self._poly_data_cache.get("scorecard", {})
        hl = self._hl_cache

        portfolio = {
            "cme": {
                "equity": 50000 + cme_sc.get("total_pnl", 0),
                "pnl_24h": cme_sc.get("total_pnl", 0),
                "positions": len(self._cme_positions_cache),
                "trades": cme_sc.get("trades", 0),
                "win_rate": cme_sc.get("win_rate", 0),
                "pf": cme_sc.get("payoff_ratio", 0),
            },
            "hl": {
                "equity": hl.get("equity", 0) if hl else 0,
                "pnl_24h": hl.get("unrealized_pnl", 0) if hl else 0,
                "positions": hl.get("position_count", 0) if hl else 0,
                "leverage": hl.get("leverage", 0) if hl else 0,
            },
            "poly": {
                "equity": poly_sc.get("total_pnl", 0),
                "pnl_24h": poly_sc.get("total_pnl", 0),
                "positions": len(self._poly_positions_cache),
                "trades": poly_sc.get("trades", 0),
                "win_rate": poly_sc.get("win_rate", 0),
            },
        }

        overview.update_data(portfolio)

        # Unified trades
        cme_trades = self._cme_data_cache.get("trades", [])
        poly_trades = self._poly_data_cache.get("trades", [])
        overview.update_trades(cme_trades, poly_trades)

        # Risk dashboard
        overview.update_risk(cme_sc, portfolio)

    def _render_cme(self):
        cme = self.query_one("#cme-tab", CMETab)
        cme_data = self._cme_data_cache

        cme.update_positions(self._cme_positions_cache)
        cme.update_scorecard(cme_data.get("scorecard", {}))
        cme.update_instruments(
            cme_data.get("scorecard", {}).get("instruments", [])
        )
        cme.update_pnl_chart(cme_data.get("pnl_series", []))
        cme.update_feed(cme_data.get("trades", []))

    def _render_hl(self):
        hl_tab = self.query_one("#hl-tab", HyperliquidTab)
        hl = self._hl_cache

        if hl:
            hl_tab.update_positions(hl)
            hl_tab.update_account(hl)
            hl_tab.update_funding(hl)
            hl_tab.update_equity_chart(hl.get("equity", 0))
            hl_tab.update_feed(hl)

    def _render_poly(self):
        poly_tab = self.query_one("#poly-tab", PolymarketTab)
        poly_data = self._poly_data_cache

        poly_tab.update_positions(self._poly_positions_cache)
        poly_tab.update_scorecard(
            poly_data.get("scorecard", {}),
            self._poly_edge_cache,
        )
        poly_tab.update_assets(
            poly_data.get("scorecard", {}).get("asset_dir_stats", [])
        )
        poly_tab.update_pnl_chart(poly_data.get("pnl_series", []))
        poly_tab.update_feed(poly_data.get("trades", []))

    def _render_strategies(self):
        if self._strategies_cache:
            self.query_one("#strategies-tab", StrategiesTab).update_strategies(
                self._strategies_cache
            )

    def _render_alerts(self):
        self.query_one("#alerts-tab", AlertsTab).update_alerts(
            self.alert_engine
        )

    def _render_risk(self):
        cme_sc = self._cme_data_cache.get("scorecard", {})
        cme_equity = 50000 + cme_sc.get("total_pnl", 0)

        self.query_one("#risk-tab", RiskTab).update_risk(
            cme_equity=cme_equity,
            cme_scorecard=cme_sc,
            hl_data=self._hl_cache,
            strategies=self._strategies_cache,
        )

    # ── Header ────────────────────────────────────────────────

    def _update_header(self):
        try:
            header = self.query_one("#global-header", GlobalHeader)

            cme_sc = self._cme_data_cache.get("scorecard", {})
            poly_sc = self._poly_data_cache.get("scorecard", {})
            hl = self._hl_cache

            cme_equity = 50000 + cme_sc.get("total_pnl", 0)
            cme_pnl = cme_sc.get("total_pnl", 0)
            hl_equity = hl.get("equity", 0) if hl else 0
            hl_pnl = hl.get("unrealized_pnl", 0) if hl else 0
            poly_equity = poly_sc.get("total_pnl", 0)
            poly_pnl = poly_sc.get("total_pnl", 0)

            total_positions = (
                len(self._cme_positions_cache)
                + (hl.get("position_count", 0) if hl else 0)
                + len(self._poly_positions_cache)
            )

            header.update_data(
                bots=self._bot_status_cache or None,
                cme_equity=cme_equity,
                cme_pnl=cme_pnl,
                hl_equity=hl_equity,
                hl_pnl=hl_pnl,
                poly_equity=poly_equity,
                poly_pnl=poly_pnl,
                positions=total_positions,
                alert_count=self.alert_engine.alert_count,
                critical_count=self.alert_engine.critical_count,
            )
        except Exception:
            pass
