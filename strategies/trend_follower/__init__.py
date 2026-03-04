"""Trend-following strategy with 5-second trailing stop management.

Entry: Donchian breakout + ADX regime filter + EMA trend alignment
Exit:  Chandelier trailing stop (ATR-based) with scale-out
Exec:  TradersPost webhooks -> Apex/Tradovate

Run standalone:
    python -m strategies.trend_follower.runner
    python -m strategies.trend_follower.runner --dry-run
"""
