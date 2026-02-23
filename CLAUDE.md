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
- **Account:** APEX4406280000016 ($50k eval)
- **Trailing drawdown:** $2,500 (floor trails up with new highs, locks at $50k)
- **Daily loss limit:** $1,000 (conservative, system enforced)
- **Profit target:** $3,000 ($53k balance)
- **Consistency rule:** No single day > 30% of total profit
- **Flatten EOD:** 4:55 PM ET hard flatten
- **No new trades after:** 4:45 PM ET

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

## Key Operations
```bash
# Clear ghost positions
echo '[]' > data/positions.json

# Send Discord message
python3 -c "
import os, requests
from dotenv import load_dotenv
load_dotenv('.env')
token = os.getenv('DISCORD_BOT_TOKEN')
requests.post(f'https://discord.com/api/v10/channels/1470827087085441078/messages',
    json={'content': 'YOUR MESSAGE'},
    headers={'Authorization': f'Bot {token}'})
"

# Run backtest for specific instrument
python scripts/backtest.py --instrument MNQ --days 60

# Analyze broker performance
# Import Performance.csv from Tradovate → dashboard reads ~/Downloads/Performance.csv
```
