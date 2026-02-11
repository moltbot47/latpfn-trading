# LaT-PFN Automated Futures Trading System

## What This Is
Automated futures trading using LaT-PFN zero-shot time-series forecasting. Predicts price movements on micro futures (MYM, MNQ, MGC) and executes via PickMyTrade webhooks or direct Tradovate API.

## Repo
- **GitHub:** github.com/moltbot47/latpfn-trading
- **Auth:** `gh auth switch --user moltbot47`

## Tech Stack
- Python 3.11+ (venv at `~/latpfn-trading/venv/`)
- PyTorch + Lightning (LaT-PFN model)
- discord.py (slash commands + signal embeds)
- yfinance (market data)
- SQLite (local state)

## Running
```bash
source venv/bin/activate
python main.py                    # Trading system (dry-run default)
python main.py --dry-run          # Predictions only, no orders
python -m discord_bot.runner      # With Discord bot
python scripts/backtest.py        # Historical backtest
python scripts/download_model.py  # Download model weights
```

## Key Architecture
```
main.py → orchestrator/main_loop.py (TradingSystem)
  → market_data/pipeline.py (DataPipeline - yfinance)
  → forecaster/wrapper.py (LaTPFNPredictor - model inference)
  → signals/generator.py (SignalGenerator - NBA shot tiers)
  → risk/manager.py (RiskManager - Kelly criterion, circuit breaker)
  → execution/webhook_client.py (PickMyTrade) OR tradovate_client.py
  → discord_bot/bot.py (signal embeds, /status, /close, /closeall)
```

## Config
- **Main config:** config/settings.yaml
- **Secrets:** .env (PICKMYTRADE_TOKEN, PICKMYTRADE_ACCOUNT_ID, DISCORD_BOT_TOKEN, TRADOVATE_*)

## Instruments
| Symbol | Contract | Size | Context Assets |
|--------|----------|------|----------------|
| MYM | Micro Dow | $0.50/pt | SPY, DIA, VIX, DX, TNX, XLF, XLI, IWM |
| MNQ | Micro Nasdaq | $2/pt | QQQ, SPY, VIX, TNX, XLK, AAPL, MSFT, NVDA |
| MGC | Micro Gold | $10/pt | GLD, SLV, DX, TNX, TIP, DBC, UUP, VIX |

## Risk Rules
- Max risk/trade: 2%, Max daily loss: 3%, Max drawdown: 10%
- Max concurrent positions: 3, Min confidence: 0.25
- Stop loss: ATR × 1.5, Min reward/risk: 1.5
- Prop firm: $1,000 daily loss cap, $2,000 total drawdown cap

## Execution Modes
- `pickmytrade` — Webhook to PickMyTrade (Apex prop firm)
- `tradovate` — Direct REST + WebSocket API
- `dry_run` — Predictions only

## LaT-PFN Model
- Cloned at `Lat-PFN/` subdirectory
- Weights: `models/lat_pfn_checkpoint.ckpt`
- ShapeConfig: n_context=16, n_heldout=4, n_history=180, n_prompt=60
- Batch size must be >1 (duplicate + take first)
- V normalization: `(v - mean) / (2*std + 1e-8)`, T_mapping: `x / 365`

## Discord
- Channel: 1470827087085441078 (Trading Pilot)
- Commands: /status, /status_radar, /close, /closeall

## PickMyTrade
- Webhook: `https://api.pickmytrade.trade/v2/add-trade-data-latest`
- Account: APEX4406280000015
- 200 OK does NOT mean trade placed — check PMT trade logs
- Must create Settings entry in PMT dashboard for each symbol

## Market Hours
- CME Globex: Sunday 6PM ET → Friday 5PM ET
- Daily break: 5PM–6PM ET
- Prediction cycle: every 5 minutes
