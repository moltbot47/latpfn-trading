# h_ema_vwap_scalper — EMA / VWAP pending-order scalper, 3 logics + regime gates

## PRE-REGISTERED RULES (written 2026-09-24 before any result was seen)

Source: the user's description (trend pullbacks off the 9/14/50/200 EMAs, reversals at VWAP /
pivots / higher-timeframe S/R toward a fib retrace, and a both-ways chop scalp with scaling
and an exhaustion-wick flip). High win rate, small TP, many positions.

### Data
1-minute broker bars from `~/range-rent/rrdata.py` (timestamps are UTC; session day rolls at
22:00 UTC):
- **US30**: 2023-01 → 2026-07, 791 sessions. The primary instrument.
- **XAUUSD**: 2025-09 → 2026-07, 226 sessions.
- **GBPJPY**: 2025-07 → 2026-07, 271 sessions.
- NAS100 was dropped: only 4 months of data.

Signals use 5m bars resampled from the 1m bars. 15m and 1h bars are built the same way and
become visible to a 5m bar only once the higher-timeframe bar has CLOSED (its close time is at
or before the 5m bar's close). Fills, stops and targets are checked on 1m bars.

### Indicators (all known at the close of the signal bar; nothing uses later bars)
- **EMAs**: 9, 14, 50 and 200 of the 5m close. **ATR**: Wilder 14 on 5m.
- **Session VWAP**: tick-volume weighted typical price, reset at each session-day start
  (22:00 UTC). CFD tick volume stands in for real volume.
- **Pivots**: from the PRIOR session's H/L/C. P = (H+L+C)/3, R1 = 2P−L, S1 = 2P−H.
- **HTF S/R**: prior session high/low and prior ISO-week high/low.
- **Swings**: a k = 2 fractal on each timeframe. A pivot is only known 2 bars after it forms,
  at that bar's close. Structure is UP when the last two confirmed swing highs AND the last
  two confirmed swing lows are both rising (HH + HL). DOWN is the mirror.

### Execution model (pessimistic, the same as range-rent)
- Pending limits fill only if a 1m bar trades THROUGH the level (strictly beyond it). The fill
  price is the limit price. A pending order lives 15 minutes (3 × 5m bars) and is then
  cancelled.
- If a 1m bar touches both stop and target, the stop counts. On a limit order's fill bar only
  the stop can trigger, never the target.
- Every trade pays the full round-trip cost from `rrdata.COST` (US30 4 pts, XAUUSD $0.45,
  GBPJPY 0.030). There is also a stress run at 2× cost.
- No new orders in the last 60 minutes of a session. Everything is flat 45 minutes before
  the session ends. Maximum hold is 120 minutes.
- One position or chain per logic per instrument at a time. An unfilled pending order blocks
  new signals until it expires.
- **Fixed size**: every trade risks $100 at its stop, so qty = 100 / (stop distance ×
  point value). The edge is judged at this size only.

### L1 — Trend pullback
- **Structure filter**, 2 variants: **A** needs UP structure on 5m, 15m and 1h; **B** needs
  UP on 15m and 1h only.
- **Trigger**: a 5m bar closes above EMA14 after the prior bar closed at or below it (a
  reclaim).
- **Entry**: buy limit at a retrace into the trigger candle, 3 variants: 25% of its range
  down from its high, 50% of its range, or EMA9. The order is skipped if the level is not
  below the close.
- **Stop**: 1.0 ATR below the entry. **Target**: 0.5 ATR above.
- **Short**: the mirror image.
- **Grid**: 2 × 3 = 6 variants per instrument.

### L2 — Level reversal
- **Level groups**, 4 variants: G1 session VWAP; G2 pivots P/R1/S1; G3 prior-day and
  prior-week high/low; G4 EMA50 and EMA200.
- **Orders**: at each 5m close, place a buy limit at the nearest group level below the close
  and a sell limit at the nearest level above. The level must be between 0.1 and 1.5 ATR
  away. The two orders are OCO, and both are skipped if they fill on the same minute.
- **Target**: a fib retrace of the approach leg. For a buy, the leg runs from the 12-bar
  (1-hour) high down to the level, and the target is level + f × (legHigh − level), with
  f ∈ {0.382, 0.5, 0.618}. The trade is skipped if the target is under 0.25 ATR away.
- **Stop**: 1.0 ATR beyond the level.
- **Grid**: 4 × 3 = 12 variants per instrument.

### L3 — Chop both-ways scalp
- **Event study first**: at each 1h candle open, does the first 15 minutes move against the
  prior 1h candle's direction? Measured as mean signed move, fraction opposite and t-stat,
  overall and by session, and compared with cost.
- **Level of interest**: the 12-bar (1-hour) 5m high or low.
- **Short leg**: when a 5m bar closes within 0.5 ATR below the level, a sell ladder is
  placed: a limit at the level, plus N adds at level + 0.25 ATR and + 0.5 ATR (N ∈ {0, 2}).
  Each unit risks $100/(N+1) at the chain stop, which sits 1.0 ATR above the last rung.
- **Target**: all units exit when price hits the average entry − 0.4 ATR.
- **Exhaustion exit and flip**: while the chain is in profit, a 1m bar whose lower wick is at
  least X of its range (X ∈ {0.5, 0.7}), with a range of at least 0.2 ATR, triggers an exit of
  all units at that bar's close. A single-unit long then opens at the next 1m open, with
  TP 0.4 ATR, stop 1.0 ATR, the same wick exit mirrored, and no further flips.
- **Long leg**: the mirror image at the 12-bar low.
- **Chop filter**: for the "natural" variant, ER(20) must be in the bottom tercile. The
  base variant has no filter.
- **Grid**: 2 × 2 = 4 variants per instrument.

### Regime gates
Each 5m signal bar is tagged with:
- **Trend/range**: efficiency ratio ER(20) on 5m, split into terciles.
- **Volatility**: ATR/close, split into terciles.
- **Session**: Asia 22–07, London 07–13 or NY 13–21 UTC.

All tercile cut-offs are computed from fold 1 only. Two gated versions are run:
- **Natural gate**: L1 trades only the top ER tercile; L2 and L3 trade only the bottom ER
  tercile.
- **Best gate**: the best of the 9 single gates (3 ER + 3 vol + 3 session) is picked on fold 1
  (net, at least 30 trades) and then judged on folds 2 and 3 against no gate.

### Evaluation
- `common.evaluate`: net of fees, 3 chronological calendar thirds per instrument.
- **Honest out-of-sample number**: pick the best grid variant on fold 1, then report its
  folds 2 and 3.
- **Grid**: 22 base variants × 3 instruments = 66 cells, plus gates. Treat as multiple
  comparisons.
- **Random control**: 300 draws for the fold-1-selected variant of each logic on US30. Each
  draw keeps every trade's side and session day, picks a random minute in that session as a
  market entry at that minute's open, and replays the same TP/SL/hold/sizing (for L3, the
  full ladder, wick and flip logic). The strategy's percentile rank in that distribution is
  reported.
- **Also reported**: win rate, average win vs average loss, and the break-even cost multiple
  (gross ÷ fees).
- **Scaling view**: the user's proportional sizing is 1% of equity risked per trade,
  compounding from $10k. It is shown separately and never used to judge edge.
- **Verdict per logic**: KEEP needs positive folds 2 and 3 for the fold-1 pick on US30, a
  random-control rank above the 95th percentile, and survival at 2× cost. WEAK is some of
  that. DEAD is the rest.

## RESULTS
(appended below after the run)

### Run 2026-09-24 — VERDICT: all three logics DEAD on every instrument

Gold and NAS100 ran first, at the user's request. **Gold** uses XAUUSD TradeLocker 1m bars
(2025-09-01 → 2026-07-16), the only 1m gold history we have; MGC/GC exist only as yfinance
5m/1h, about 60 days, so they weren't used. **NAS100** 1m covers only 2024-01 → 2024-04
(75 sessions), so treat its results as thin. US30 and GBPJPY ran as well.

In the table below, "pick" is the variant chosen on fold 1, "net" is at fixed $100 risk per
trade, and "gross/fees" is the break-even cost multiple: the result is profitable only if
costs fall below that fraction of today's. "ctrl rank" is the percentile against 300 random
entries with identical geometry.

| Instr | Logic | Pick | n | Net | WR | Avg W / Avg L | Folds | Gross/fees | Ctrl rank |
|---|---|---|---:|---:|---:|---|---|---:|---:|
| XAUUSD | L1 | all TFs, 25% retrace | 146 | −1,749 | 65% | 40 / −109 | −269 / −436 / −1044 | <0 | 38 |
| XAUUSD | L2 | pivots, fib 0.618 | 1,909 | −12,718 | 43% | 130 / −108 | −1092 / −7795 / −3831 | 0.30 | 77 |
| XAUUSD | L3 | 2 adds, wick 0.7 | 17,145 | −71,673 | 69% | 9 / −33 | −30.6k / −18.9k / −22.1k | <0 | 0 |
| NAS100 | L1 | all TFs, 25% retrace | 34 | −2,012 | 44% | 17 / −119 | −288 / −996 / −728 | <0 | 10 |
| NAS100 | L2 | pivots, fib 0.618 | 387 | −14,825 | 39% | 123 / −139 | −4520 / −4574 / −5731 | 0.17 | 96 |
| NAS100 | L3 | 2 adds, wick 0.7 | 4,956 | −86,636 | 25% | 5 / −25 | all 3 folds < −27k | <0 | 0 |
| US30 | L1 | all TFs, 25% retrace | 351 | −12,675 | 53% | 25 / −106 | all 3 folds negative | <0 | 2 |
| US30 | L2 | HTF S/R, fib 0.618 | 4,635 | −114,803 | 39% | 122 / −119 | all 3 folds negative | <0 | 48 |
| US30 | L3 | 2 adds, wick 0.7 | 58,269 | −509,551 | 52% | 7 / −26 | all 3 folds negative | <0 | 0 |
| GBPJPY | L1 / L2 / L3 | — | — | −6.7k / −82.5k / −257k | — | — | all folds negative | ≤0.05 | n/a |

All 88 grid cells (22 variants × 4 instruments) are negative in every fold.

**1h-open event study.** The first 15 minutes against the prior hour's direction:
- XAUUSD: 51.6% opposite, mean +0.06 against a $0.45 cost, t = 0.41.
- NAS100: 50.9% opposite, t = −0.92.
- US30: 49.6% opposite, t = −0.06.
- GBPJPY: 49.4% opposite.

It is a coin flip, and the mean move is a fraction of cost. **Refuted.**

**Regime gates.**
- The natural gate (L1 in trend, L2/L3 in range) and the best single gate picked on fold 1
  both only shrink losses by trading less.
- Folds 2+3 stay negative in every case. For example, XAUUSD L3 with the NY-session gate lost
  −12.1k out of sample, against −41.0k ungated.
- **No gate turns any logic positive out of sample.**

**Execution lens: best case at zero cost, touch fills, target-first.**
- XAUUSD: L1 −6, L2 +10.3k (folds +9.3k / −2.1k / +3.1k), L3 −24.0k.
- NAS100: L1 −250, L2 +4.7k, L3 −9.6k.
- US30: L1 0, L2 +22.5k, L3 −91k.

Even with free, perfect execution, L1 and L3 have no gross edge. L2's small gross comes out
at 17–30% of retail cost.

**Statistics lens.**
- NAS100 L2 ranks at the 96th percentile against random, but that means it loses less than
  random (−14.8k vs −18.9k average), not that it makes money. With 88 cells, one result at
  the 96th percentile is expected by chance, and it comes from 75 sessions.
- L3 ranks at the 0th percentile everywhere. Fading the 1h high/low is worse than a random
  entry: those levels tend to break, not reverse.

**Leakage lens.** Not run, because no result was positive.

**Win rate is geometry.** L1 and L3 reach the 65–69% win rate the user wants on gold, but the
average loss is 3–4× the average win. That comes from TP 0.4–0.5 ATR against a 1 ATR stop.

**Proportional scaling** (1% of equity risked per trade, compounding from $10k; not used to
judge edge):

| Logic, instrument | Compounding end | Fixed-size end |
|---|---:|---:|
| XAUUSD L1 | $8,363 (20% max drawdown) | $8,251 |
| XAUUSD L2 | $2,393 | −$2,718 |
| XAUUSD L3 | $7 (wiped) | −$61,673 |
| NAS100 L3 | $2 (wiped) | −$76,636 |
| US30 L3 | $0 (wiped) | −$499,551 |

Scaling multiplies an edge; it cannot create one. Here it compounds a loss.

**Rule interpretations** (user wording → mechanical rule):
- "Close above 14 EMA" → a reclaim cross.
- "Small retracement into the previous candle" → a 25% or 50% retrace of the trigger candle,
  or a limit at EMA9.
- "Level of interest" → the 1h (12 × 5m) high/low.
- "Looks like it may exhaust and wick back" → a 1m wick of at least 50–70% of its range, with
  a range of at least 0.2 ATR, while in profit.
- "Safe fib" → a 38.2/50/61.8 retrace of the approach leg.
- VWAP resets at 22:00 UTC and is weighted by tick volume.

A bug found during the build was fixed before the results above: the L3 short-side stop,
target and rung signs were inverted, which had produced a fake +$1M at a 100% win rate.

**Files:**
- Code: `h_ema_vwap_scalper.py`
- Results: `h_ema_vwap_scalper_XAUUSD_NAS100.json` (gold and NAS100, with controls) and
  `h_ema_vwap_scalper.json` (US30 with controls, XAUUSD and GBPJPY)
- Logs: `*.log`
- quant-lab: strategy `ema_vwap_scalper`, 28 rows per instrument (112 total)
