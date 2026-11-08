# h_fx_edges: does any FX (or US30) strategy have an edge after Genesis costs and swap?

Asked 2026-09-24: "show me something with an edge. test the major forex pairs like gbpjpy nzdjpy etc",
plus "include US30 too". The rules below were written BEFORE any result was computed. Code:
`tests/h_fx_edges.py`; data fetch `tests/fx_fetch.py`; sources in `data/fx/MANIFEST.md`.

## Universe
- FX (14): EURUSD GBPUSD USDJPY USDCHF AUDUSD USDCAD NZDUSD, GBPJPY NZDJPY AUDJPY EURJPY CADJPY CHFJPY, EURGBP.
- US30: its own section.

## Data (see MANIFEST)
- **FX daily:** Yahoo `=X`, 2003/04 → 2026-09.
  - **Data trap found before testing:** in 2012 and in 2022–2025, Yahoo's FX daily "close" equals the open, a snapshot near 00:00 UTC. The high and low still span the whole day.
  - A daily close labelled D can therefore be the price at the START of day D, while that bar's high and low happen after it.
  - **Rule:** the daily strategies use closes only, and decide at close t but trade at close t+1. The one-day lag removes any benefit from the labelling.
  - No strategy combines a Yahoo daily high/low with its close.
- **FX hourly:** Yahoo, 2023-12-11 → 2026-09-24 (~2.8 years).
  - The intraday candidates (Tokyo A+, tight-range breakout, Asia/London breakout) use these hourly bars.
  - They use daily bars **rebuilt from the hourly bars** with a 22:00 UTC day boundary (the 5pm New York rollover).
  - Dukascopy was rate-limited (HTTP 429). TradeLocker 1m exists for GBPJPY only, 2025-07 → 2026-07, and is used only for spread notes.
- **Policy rates:** FRED OECD "immediate" monthly rates `IRSTCI01{US,JP,GB,EZ,AU,NZ,CA,CH}M156N`.
  - After a series ends, it is spliced with a fallback: NZ → `IR3TIB01NZM156N` (3-month interbank), CH → `IR3TIB01CHM156N`, EZ → `ECBDFR` (ECB deposit rate).
  - For signals, the rate of month m becomes known only at the start of month m+1 (one-month lag).
  - For swap accrual, the contemporaneous rate is used.
- **US30:**
  - `^DJI` daily closes, 1992 → 2026, for trend. Its opens are stale before 2016, so they are not used.
  - `DIA` ETF daily, 1998 → 2026, for overnight versus day-session returns. Dividends are added back on ex-dates. DIA returns are applied to the DJI level to get points.
  - TradeLocker US30 1m bars from `~/range-rent/rrdata.py`, 2023-01 → 2026-07, for the exact 16:00→09:30 ET overnight and the opening-range breakout.

## Costs (Genesis TradeLocker)
**Everything below is an assumption; the user needs to confirm it.**
- **Size:** fixed 1.0 lot, which is 100k base units for FX and $1/point for US30 (the lot value is an assumption). P&L is converted to USD at each bar's rate.
- **FX commission:** $6 per lot round trip, i.e. $3 a side. The user saw $6/lot on NAS100 and $10 on gold; the FX rate is unconfirmed.
- **FX spread, round trip in pips:**
  - EURUSD 0.3; GBPUSD 0.5; USDJPY 0.4; AUDUSD 0.4
  - USDCHF 0.6; USDCAD 0.6; NZDUSD 0.6; EURGBP 0.6
  - EURJPY 0.8; AUDJPY 1.0
  - GBPJPY 1.5; NZDJPY 1.5; CADJPY 1.5; CHFJPY 1.5
- **US30:** $6 commission plus a 2.0-point spread, so $8 per lot round trip.
- **Stress run:** every commission and spread doubled.
- **Position strategies:** costs are charged on position CHANGES only. Keeping a position through a monthly rebalance costs nothing.
- **FX swap, per calendar day:** 1 lot × base notional in USD × (r_base − r_quote − 1.0%) / 365 for a long; the mirror for a short. The broker markup is 1%/yr on each side.
- **US30 financing on a long:** −(US rate + 2.5%) / 365 × notional per night.
- **US30 on a short:** +(US rate − 2.5%) / 365 × notional per night.
- Weekend accrual follows calendar days.

## Evaluation (the same for all)
- **Harness:** `common.evaluate` / `walk_forward`, with 3 chronological folds.
- **Walk-forward:** variant picked on fold 1 (net), headline = folds 2+3 of that pick.
- **Position strategies:**
  - One trade row per pair per calendar month held.
  - Gross = price P&L + swap; fee = transaction costs.
  - Drawdown also comes from daily equity.
- **Controls:**
  - Position strategies: random signs, 300 draws. Each held pair-month gets a random direction; exposure and cost are kept.
  - Event strategies: random entry times on the same pairs with the same geometry and hold, direction random, 300 draws.
- **Reported:**
  - n, trades per month, average hold, win rate, average win/loss, PF, Sharpe
  - Max drawdown in $ at 1.0 lot, per-year net
  - % of winners that were underwater first (event strategies)
- **Lenses on anything positive out of sample:** leakage, execution (2× cost, and a 1-day extra delay for daily strategies), statistics (t-stat, fold spread, control rank).
- **Verdicts:**
  - **TRADEABLE:** out-of-sample net > 0 in both OOS folds, survives 2× cost, and is above the 95th percentile of the control.
  - **FORWARD-TEST:** positive out of sample but fails one of those.
  - **DEAD:** otherwise.

## Candidates and grid (fixed; 35 cells total)

### FX daily, 2005-01 → 2026-09, 14 pairs, 1 lot per pair (11 cells)
- **C1 carry:**
  - Carry = r_base − r_quote, using the lagged rate. Rebalance at month-end.
  - Hold in the direction of carry.
  - Cross-sectional variants: the top K pairs by |carry|, K ∈ {3, 5}.
  - Per-pair variants: every pair with |carry| ≥ thr, thr ∈ {1.0, 2.0}%.
  - 4 cells.
- **C2 trend:**
  - Sign of the past-L-day return, L ∈ {63, 126, 252}, rebalanced monthly on all 14 pairs.
  - MA50/MA200 state, checked daily.
  - 4 cells.
- **C2c carry + trend:** per-pair carry with |carry| ≥ 1.0%, held only when sign(L-day return) agrees with the carry, L ∈ {63, 126, 252}. 3 cells.
- **Crash windows reported:** 2008-08 → 2008-12, 2015-01-14 → 01-20 (SNB), 2020-02-20 → 03-31, 2024-07-10 → 08-09 (yen unwind).

### FX intraday, hourly 2023-12 → 2026-09 (12 cells)
- **C3 Tokyo A+ reversal:** the spec from `tokyo-strategy/analysis/forex_backtest.py`, run strictly.
  - Rebuilt daily bars; the 20-day range position and daily RSI(14) must be extreme.
  - Score as in the original; the 4H confirm uses 4H bars closed by the daily close.
  - Entry at the open of the first hourly bar after the daily close.
  - Manage "hold-bounce": TP +0.5 ATR, disaster stop −2.5 ATR, horizon 72h. "fixed1.5": SL 1 ATR, TP 1.5 ATR, 72h.
  - Score threshold ∈ {60, 75}.
  - One open trade per pair; stop first when an hourly bar touches both.
  - 4 cells.
- **C4 tight-range breakout:**
  - On 1H or 4H bars, when the last 20 bars' range is < 3 × ATR14 of that timeframe, place OCO stop orders at the range high and low.
  - Target = range width (the measured move); cancel after 5 bars; time exit after 30 bars.
  - Stop ∈ {opposite side, range midpoint}; timeframe ∈ {1H, 4H}.
  - 4 cells.
- **C5 Asia range → London breakout:**
  - Asia range = 00:00–06:59 UTC. At 07:00, place OCO stops at its high and low. Stop at the opposite side.
  - Exit ∈ {TP = 1 × range width, else 16:00 UTC; flat at 16:00 UTC}.
  - Filter ∈ {none, range < 0.5 × daily ATR}.
  - 4 cells.

### US30 (12 cells)
- **U1 trend on `^DJI`, 1993 → 2026:**
  - Long/short signal from the sign of the L-day return, L ∈ {63, 126, 252}, or MA50/200. Monthly rebalance; MA checked daily. 4 cells.
  - Long-or-flat versions of the same 4. 4 cells.
  - Baseline: buy-and-hold 1 lot, with financing.
- **U2 overnight drift:**
  - Long 16:00 → 09:30 ET on DIA, 1998 → 2026, and on US30 1m, 2023 → 2026. 1 cell each.
  - Beta control: day session (09:30 → 16:00) and buy-and-hold over the same dates. Financing: one night, three on Fridays.
- **U3 opening-range breakout, US30 1m:**
  - Range = first 15 or 30 minutes after 09:30 ET; OCO stops at the high and low; stop at the opposite side.
  - Exit ∈ {TP = 1 × range, else 15:55 ET; flat at 15:55 ET}.
  - Within a 1m bar, stop first.
  - 4 cells (the 2 U2 cells are not counted in the 12).

With ~35 cells, one or two "positives" at the 95% level are expected by chance. The verdict must hold out of sample and against the control, not just have a positive total.

---
# RESULTS (appended after the run, 2026-09-24)

Conventions:
- All figures are at 1.0 lot per position, net of assumed Genesis commission, spread and swap/financing.
- **OOS** = folds 2+3 of the variant picked on fold 1.
- quant-lab: 38 rows (`fx_*` and `us30_*`, project edge-hunt). Raw output is in `h_fx_edges.json`.

## Ranking

| # | Strategy | Out-of-sample net | Fold 2 / fold 3 | Control | Verdict |
|---|---|---:|---|---:|---|
| 1 | **C1 FX carry, top-3 pairs by \|rate differential\|, monthly** | **+$63.8k** (2012-05 → 2026-09, 3 lots) | +21.7k / +42.1k | 97th pct | **FORWARD-TEST.** Passes the mechanical bar; the statistics lens downgrades it (t = 0.76). |
| 2 | C3 Tokyo A+ reversal, score ≥ 75, hold-bounce | +$4.3k (2025-01 → 2026-09) | +4.1k / +0.2k | 86th pct | Weak. Fold 1 was −9.7k; full period −5.4k; t = 0.68. |
| 3 | C2c carry + trend (63d) | +$24.8k | −48.7k / +73.5k | 90th pct | DEAD by the rule: fold 2 lost. |
| 4 | U1 US30 12-month trend, long-or-flat | +$10.6k | +4.9k / +5.7k | 29th pct | DEAD as an edge: buy-and-hold made +$17.8k over the same span. |
| — | C2 FX trend (TSMOM / MA) | −$345k (picked TSMOM63) | −228k / −117k | 17th pct | DEAD. The 1%/yr swap markup on 14 always-on lots (≈ −$14k/yr) swamps it. |
| — | C4 tight-range breakout (4H, stop at the opposite side) | −$20.8k | −21.1k / +0.3k | 11th pct | DEAD |
| — | C5 Asia range → London breakout | −$7.5k; −$58.8k at 2× cost | +5.6k / −13.1k | — | DEAD. 195 trades/month; costs kill it. |
| — | U2 US30 overnight, DIA 1998–2026 | −$41.1k (all folds negative) | — | — | DEAD at $8/lot. Gross points were +$42.8k, but costs were $57.1k and financing $26.8k. The overnight session made 79% of buy-and-hold points (t = 3.9 against zero), but overnight minus day has t = 1.4. |
| — | U2 US30 overnight, TradeLocker 1m 2023–2026 | −$4.7k | −4.3k / +4.0k | — | DEAD. Financing (−$8.5k) is the difference. |
| — | U3 US30 opening-range breakout (15/30 min) | −$4.5k | −1.8k / −2.6k | 46th pct | DEAD. All 4 cells were negative. |

## C1 carry top-3 in detail (the only survivor)

**How much comes from swap:**
- The out-of-sample profit is all swap: price −$3.8k, carry income +$108.5k, markup −$40.5k, fees −$0.4k.
- It is a bet that the positive-carry swap is paid as modelled. **Genesis's swap table is unknown.**

**Swap-markup sensitivity** (out-of-sample net / t):

| Markup per side | OOS net | t |
|---|---:|---:|
| 0% | +104.3k | 1.25 |
| 0.5% | +84.0k | 1.00 |
| 1% (base) | +63.8k | 0.76 |
| 1.5% | +43.6k | 0.52 |
| 2% | +23.3k | 0.28 |
| 3% | −17.2k | −0.21 |

Break-even markup ≈ 2.6%/yr.

**Other checks:**
- **Stress:** 2× cost gives +$63.4k; an extra day of signal lag gives +$58.0k. Costs barely matter, because it trades ~once a month.
- **Crashes** (3 lots): 2008 GFC −$74k; 2015 SNB −$0.4k; 2020 Covid −$11.1k; Aug-2024 yen unwind −$25.9k.
  - Worst daily-equity drawdown: −$153k over the full period, −$60k out of sample.
  - Per-year out of sample: 2015 −24.1k, 2020 −27.6k, 2022 −8.9k; 2023 +23.3k, 2024 +31.7k.
- **Size:** about $367/month for 3 lots out of sample, ≈ $120 per lot per month, with a daily Sharpe of 0.2.
- **Pairs held most** out of sample: NZDJPY, USDCHF, AUDJPY, USDJPY. Current book (Sep 2026): long USDCHF, GBPJPY, AUDJPY.

**Lenses:**
- **Leakage:** clean. Rates lag one month and decisions lag one day; the extra-lag test barely moved it.
- **Execution:** clean on costs, but everything hinges on the swap assumption.
- **Statistics:** t = 0.76 over 14 years out of sample, which is not distinguishable from zero. The 97th-percentile control only shows that "carry direction" beats random directions. That is expected, since random directions pay carry.
- **Verdict: FORWARD-TEST, conditional on Genesis's actual swap rates.** Pull the Genesis swap table first. If the markup is ≥ 2.6%/yr, it's dead.

## C3 Tokyo A+ reversal: the memory's claim is refuted

- **The claim** (tokyo-strategy memory): 84.7% win, +0.32R.
- **Replicated** with the original timing in `tests/h_fx_edges_tokyo_replica.py`: **85.2% win, +0.30R** (n = 614, no costs).
- **The cause is look-ahead.**
  - The original entered at Yahoo's daily "close". In 2022–2025 that is the ~00:00 UTC opening snapshot of day D.
  - Its forward path started at D 00:00, and its 20-day range and ATR included day D's own high and low.
- **Strict timing** (daily bars rebuilt on the 22:00 UTC boundary, entry at the next hourly open, stop first when a bar hits both): **66.3% win, −0.001R gross** (n = 282).
- **After costs and swap:** full period −$5.4k; the out-of-sample pick +$4.3k with t = 0.68, 8.3 trades/month and an average hold of 53h.
- **Underwater before winning:** 97% of winners went into the red first, but only 5% by ≥ 0.5R.
- **Verdict:** no edge. The "84.7%" was look-ahead.

## Other metrics (out-of-sample picks)

| | A+ | Tight-range 4H | Asia/London | US30 ORB 15m |
|---|---:|---:|---:|---:|
| Trades/month | 8.3 | 17.5 | 195 | ~18 |
| Average hold | 53h | 85h | 6.8h | intraday |
| Win rate | 68% | 48% | 44% | — |
| Winners underwater first (any / ≥ 0.5R) | 97% / 5% | 100% / 37% | 100% / 46% | see json |
| Losers that were up ≥ 0.5R | 0% | 28% | 34% | — |

## Assumptions to confirm with Genesis
1. FX commission: is it $6/lot round trip?
2. FX spreads per pair (the table above).
3. **Swap/rollover table**: long/short points per pair. This decides C1.
4. US30 lot value: $1/point assumed. Is 1.0 lot $1, $10 or $20 per point?
5. US30 commission, spread and overnight financing.

Grid: 35 pre-registered cells (+1 US30 buy-hold baseline, +1 diagnostic replica). At that count, 1–2 false positives at the 95% level are expected; only C1 is positive in both OOS folds, and it isn't statistically significant.
