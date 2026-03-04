# LaT-PFN Automated Futures Trading System

## What This Is
Automated futures trading using LaT-PFN zero-shot time-series forecasting. Predicts price movements on micro futures (MYM, MNQ, MES, MBT, MET, 10Y) and executes via TradersPost webhooks to Apex prop firm accounts.

## Repo
- **GitHub:** github.com/moltbot47/latpfn-trading
- **Auth:** `gh auth switch --user moltbot47`

## Tech Stack
- Python 3.11+ (venv at `~/latpfn-trading/venv/`)
- PyTorch + Lightning (LaT-PFN model)
- discord.py (slash commands + signal embeds)
- yfinance (market data)
- SQLite (local state + trade logging)
- Flask (dashboard at localhost:5050)

## Running
```bash
source venv/bin/activate
python -m discord_bot.runner      # Main: trading system + Discord bot
python main.py                    # Trading system without Discord
python main.py --dry-run          # Predictions only, no orders
python scripts/backtest.py        # Historical backtest
python scripts/dashboard.py       # Web dashboard (port 5050)

# Trend Follower (standalone strategy)
python -m strategies.trend_follower.runner           # Live execution
python -m strategies.trend_follower.runner --dry-run  # Dry run (no orders)
```

## Key Architecture
```
main.py → orchestrator/main_loop.py (TradingSystem)
  → market_data/pipeline.py (DataPipeline - yfinance 5-min bars)
  → forecaster/wrapper.py (LaTPFNPredictor - model inference)
  → signals/generator.py (SignalGenerator - NBA shot tiers)
  → signals/trend_filter.py (EMA trend filter - rejects counter-trend)
  → signals/regime.py (ADX + volatility regime detection)
  → signals/signal_ranker.py (multi-factor candidate ranking)
  → risk/manager.py (RiskManager - drawdown-aware sizing)
  → risk/apex_compliance.py (Apex prop firm rule enforcement)
  → execution/traderspost_client.py (TradersPost webhooks)
  → execution/order_manager.py (position tracking + persistence)
  → monitoring/trade_logger.py (SQLite trade/prediction logging)
  → discord_bot/bot.py (signal embeds, /status, /close, /closeall)

strategies/trend_follower/runner.py (TrendFollowerRunner - standalone)
  → strategies/trend_follower/price_feed.py (yfinance batch polling, 5s snapshots)
  → strategies/trend_follower/strategy.py (Donchian breakout + ADX/EMA filters)
  → strategies/trend_follower/trail_manager.py (ATR chandelier trailing stops)
  → execution/traderspost_client.py (TradersPost webhooks - shared)
  → risk/apex_compliance.py (Apex prop firm rules - shared)
  → polymarket/platform_emitter.py (agent platform events - shared)
```

## Config
- **Main config:** config/settings.yaml
- **Secrets:** .env (DISCORD_BOT_TOKEN, TRADOVATE_*)

## Active Instruments & Tier Filters
| Symbol | Contract | Size | Allowed Tiers | Asset Class |
|--------|----------|------|---------------|-------------|
| MNQ | Micro Nasdaq | $2/pt | layup, short_range, three_pointer | equity_index |
| MYM | Micro Dow | $0.50/pt | all tiers | equity_index |
| MES | Micro S&P 500 | $5/pt | layup, short_range, three_pointer | equity_index |
| MBT | Micro Bitcoin | $0.10/pt | layup, free_throw | crypto |

Disabled: MET (PF 0.29), 10Y (PF 0.00), M2K (no edge), MGC (Apex metals halt), MCL (no edge), FX micros (broken data)

## Live Performance (Broker-Confirmed, 02/19-02/23/2026)
**187 trades | 56.7% WR | PF 1.61 | +$3,205.25**

| Symbol | Trades | Win Rate | P&L | PF | Avg Trade |
|--------|--------|----------|-----|-----|-----------|
| MNQ | 72 | 61.1% | +$1,668 | 1.53 | +$23.17 |
| MES | 56 | 51.8% | +$404 | 1.29 | +$7.21 |
| MBT | 10 | 80.0% | +$263 | 2.14 | +$26.25 |
| MYM | 48 | 50.0% | +$256 | 1.54 | +$5.33 |

**All 4 instruments profitable live.** MNQ is the top earner; MBT has highest WR and PF.

## Signal Pipeline
1. Fetch 240 bars of 5-min OHLCV (yfinance)
2. LaT-PFN model predicts next 60 bars → direction + confidence
3. Composite confidence: 40% model + 30% trend clarity + 30% uncertainty inverse
4. Regime detection: ADX + vol + VIX → trending/ranging/volatile multiplier
5. NBA shot-tier classification: confidence → tier (layup/short_range/free_throw/three_pointer/half_court)
6. Per-instrument tier filter: reject tiers not in allowed_tiers
7. **EMA trend filter**: reject counter-trend signals (longs in bearish, shorts in bullish)
8. Signal ranking: confidence × tier × regime × diversification × ADX bonus
9. Risk validation: drawdown-aware sizing, Apex compliance, portfolio cap
10. Execution: TradersPost webhook → Tradovate → Apex

## EMA Trend Filter (signals/trend_filter.py)
- Computes 50-period (fast, ~4hr) and 200-period (slow, ~16hr) EMAs on 5-min close data
- Price below both EMAs → bearish → longs blocked
- Price above both EMAs → bullish → shorts blocked
- Price between EMAs → neutral → both directions allowed
- Config: `signal.trend_filter.enabled: true` in settings.yaml

## Risk Rules
- Max risk/trade: 2%, Max daily loss: $1,000
- Max concurrent positions: 6, Min confidence: 0.25
- Stop loss: uncertainty-based × ATR multiplier (1.5)
- Position sizing: drawdown-aware (scales with remaining cushion)

## Apex Prop Firm Rules
- **Active account:** APEX4406280000020 (Tradovate 42664428) — $50k EOD Trail eval
- **Previous accounts:** APEX-18 + 19 (evals), APEX-16 + 17 — blown 02/24 (counter-trend longs in gate=soft mode)
- **Trailing drawdown:** $2,000 EOD Trail (floor only moves at session close, not intraday)
- **Daily loss limit:** $1,000 (conservative, system enforced)
- **Profit target:** $3,000 ($53k balance)
- **Consistency rule:** No single day > 30% of total profit
- **Flatten EOD:** 4:55 PM ET hard flatten
- **No new trades after:** 4:45 PM ET
- **Trend filter:** `gate` mode (hard reject counter-trend signals) — changed from `soft` after 02/24 loss

## Dashboard
- **URL:** http://localhost:5050
- **Tabs:** Overview, Signals, Positions, Trades, Broker P&L, Config
- **Broker data:** Reads ~/Downloads/Performance.csv (Tradovate export)
- **Script:** scripts/dashboard.py (Flask, port 5050)

## Discord
- Channel: 1470827087085441078 (Trading Pilot)
- Commands: /status, /status_radar, /close, /closeall

## TradersPost
- Webhook: configured in settings.yaml (traderspost.webhook_url)
- Auth embedded in webhook URL — no separate API key needed
- Rate limits: 60 requests/min, 500 requests/hour
- Docs: https://docs.traderspost.io/docs/core-concepts/signals/webhooks

## Trend Follower Strategy
- **Type:** Donchian breakout trend-following with ATR trailing stops
- **Entry:** Price breaks 20-period Donchian channel + ADX > 25 + EMA 50/200 alignment
- **Exit:** 3x ATR chandelier trailing stop (follows best price, never retreats)
- **Scale-out:** 50% at 1.5R, stop moves to breakeven for remainder
- **Initial stop:** 2x ATR from entry
- **Polling:** 5-second price polling for trail management, 5-min cycle for entry scanning
- **Sizing:** 2% equity risk per trade, risk-based: (equity * 0.02) / (stop_dist * contract_size)
- **Agent Platform:** Registered as `trend_follower_cme` (ID: 3a10a35b-043d-41ec-9a9e-e6dce4096c6c)
- **API Key prefix:** ak_1b84aef65
- **State file:** data/trend_positions.json
- **Config section:** `trend_follower` in settings.yaml

## LaT-PFN Model
- Cloned at `Lat-PFN/` subdirectory
- Weights: `models/lat_pfn_checkpoint.ckpt`
- ShapeConfig: n_context=16, n_heldout=4, n_history=180, n_prompt=60
- Batch size must be >1 (duplicate + take first)
- V normalization: `(v - mean) / (2*std + 1e-8)`, T_mapping: `x / 365`

## Market Hours
- CME Globex: Sunday 6PM ET → Friday 5PM ET
- Daily break: 5PM–6PM ET
- Prediction cycle: every 5 minutes

## Development & Operations
```bash
make help            # Show all available commands
make test            # Run 240 tests
make lint            # Ruff linter
make coverage        # Coverage report (90% on core modules)
make backup          # Backup all SQLite databases
make db-maintain     # VACUUM + ANALYZE + integrity check
make health          # Check service health
make load-test       # Load test funding dashboard
make docker          # Build and run in Docker
```

## Key Operations
```bash
# Clear ghost positions
echo '[]' > data/positions.json

# Run backtest for specific instrument
python scripts/backtest.py --instrument MNQ --days 60

# Analyze broker performance
# Import Performance.csv from Tradovate → dashboard reads ~/Downloads/Performance.csv
```

## Funding Dashboard (port 5055)
```bash
python scripts/funding_dashboard.py   # Start dashboard
curl localhost:5055/health            # Liveness check
curl localhost:5055/health/detail     # Readiness + DB probe
curl localhost:5055/metrics           # Request stats
curl localhost:5055/api/docs          # Auto-generated API docs
```
