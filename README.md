# LaT-PFN Automated Futures Trading System

Automated futures trading using **LaT-PFN zero-shot time-series forecasting**. Predicts price movements on micro futures and executes via TradersPost webhooks to prop firm accounts.

## Live Performance (Broker-Confirmed)

| Metric | Value |
|--------|-------|
| Total Trades | 187 |
| Win Rate | 56.7% |
| Profit Factor | 1.61 |
| Net P&L | +$3,205.25 |

| Symbol | Trades | Win Rate | P&L | PF |
|--------|--------|----------|-----|-----|
| MNQ (Micro Nasdaq) | 72 | 61.1% | +$1,668 | 1.53 |
| MES (Micro S&P 500) | 56 | 51.8% | +$404 | 1.29 |
| MBT (Micro Bitcoin) | 10 | 80.0% | +$263 | 2.14 |
| MYM (Micro Dow) | 48 | 50.0% | +$256 | 1.54 |

**All 4 instruments profitable live.**

## How It Works

```
Data Pipeline (yfinance 5-min bars)
  → LaT-PFN Model (zero-shot time-series forecasting)
  → Signal Generator (NBA shot-tier classification)
  → Trend Filter (EMA 50/200 gate mode)
  → Regime Detection (ADX + volatility + VIX)
  → Signal Ranker (multi-factor scoring)
  → Risk Manager (drawdown-aware sizing)
  → Apex Compliance (prop firm rule enforcement)
  → Execution (TradersPost webhooks → Tradovate)
```

## Signal Classification

Signals are classified into NBA shot tiers based on composite confidence:

| Tier | Confidence | Description |
|------|-----------|-------------|
| Layup | 0.70+ | Highest conviction |
| Short Range | 0.55-0.70 | Strong signal |
| Free Throw | 0.40-0.55 | Moderate signal |
| Three Pointer | 0.30-0.40 | Speculative |
| Half Court | <0.30 | Low conviction |

## Risk Management

- Max risk per trade: 2%
- Max daily loss: $1,000
- Max concurrent positions: 6
- Stop loss: uncertainty-based × ATR multiplier
- Position sizing: drawdown-aware (scales with remaining cushion)
- EMA trend filter: rejects counter-trend signals
- Apex trailing drawdown compliance

## Tech Stack

`Python` `PyTorch` `Lightning` `Flask` `SQLite` `Discord.py` `yfinance` `TradersPost`

## Running

```bash
source venv/bin/activate
python -m discord_bot.runner      # Trading system + Discord bot
python main.py                    # Trading system without Discord
python main.py --dry-run          # Predictions only, no orders
python scripts/backtest.py        # Historical backtest
python scripts/dashboard.py       # Web dashboard (port 5050)
```

## Author

Built by [@moltbot47](https://github.com/moltbot47) — Founder, Eula Labs Ventures
