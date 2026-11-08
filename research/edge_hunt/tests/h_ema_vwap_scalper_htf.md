# h_ema_vwap_scalper_htf — the 3 logics on 15m / 1h signals, 1:1 R:R, FVG / order-block entries, fixed 1.0 lot

## PRE-REGISTERED RULES (written 2026-09-24 before any HTF result was seen)

### Sizing: fixed 1.0 lot (Genesis FX / TradeLocker conventions)
| Instr | 1.0 lot = USD per 1.0 price move | Cost per round trip (rrdata.COST pts × lot value) |
|---|---|---|
| NAS100 | $10 per index point (user-given) | 5.0 pts → $50 |
| XAUUSD | 100 oz → $100 per $1 (user-given) | $0.45 → $45 |
| GBPJPY | 100k units; pip value = 1000 JPY. **No USDJPY series exists locally**, so a FIXED **$6.70/pip** is used, i.e. $670 per 1.00 JPY. That's USDJPY ≈ 149; the error scales linearly. | 0.030 → $20.10 |
| US30 | **ASSUMED** $10 per point, the same convention as NAS100; not user-given. Everything scales linearly if the broker uses $1. | 4.0 pts → $40 |

- Every filled order is 1.0 lot.
- For the part (a) restatement of the OLD L3 ladder, each rung that fills is 1.0 lot, so a
  full chain is 3 lots.

### Signal timeframes and bars
- Signal bars are 15m and 1h, resampled from 1m. The next-higher timeframe (1h for 15m
  signals, 4h for 1h signals) supplies trend context. It becomes visible only after its bar
  CLOSES.
- Orders are placed at the first 1m bar after the signal bar closes. All fills, stops,
  targets and MAE/MFE use 1m bars.
- On the signal TF: EMA 9/14/50/200, Wilder ATR14, session VWAP (22:00 UTC reset, tick
  volume), ER(20), ATR/close, and session.
- Structure uses k = 2 fractal swings, known 2 bars after the pivot. It tracks the last
  confirmed swing high/low VALUES and HH+HL / LH+LL status.
- Levels: prior-day P/R1/S1, PDH/PDL, PWH/PWL, and session VWAP.

### Execution (same honesty as before)
- Pending limits fill only if a 1m bar trades THROUGH the level; the fill price is the limit.
- On the fill bar only the stop can trigger. If a bar touches both stop and target, the stop
  counts.
- Full rrdata.COST, plus a 2× stress run.
- No new orders in the last 60 minutes of a session; flat 45 minutes before session end.
- **Max hold is 24 signal bars** (6h on 15m, 24h on 1h). The session-flat rule applies first.
- One position per variant at a time. An unfilled pending order blocks new signals until it
  expires.
- **Pending life:** K = 3 signal bars for E1 and native-level entries; K = 6 for FVG and OB
  zones, which are meant to be revisited.

### R:R and stops (fixed)
- **R:R is 1:1:** target distance = stop distance.
- **E1 (EMA pullback / native level):** stop = 1.0 ATR of the signal TF.
- **E2 FVG:** stop = the far side of candle 1 of the 3-candle pattern (its low for a bullish
  gap, its high for a bearish one).
- **E3 OB:** stop = the far extreme of the OB candle (its low for a bullish OB).
- **Structural stops (E2, E3):** skipped if the distance is < 0.25 ATR or > 3 ATR.

### Entry types
- **E1 pullback:** the 5m rule from before, moved to the signal TF. A bar closes back across
  EMA14 in the trend direction (the prior bar closed on the other side), and a limit is placed
  at EMA9. It is skipped if EMA9 is not on the pullback side of the close.
- **E2 FVG:** a 3-candle gap on the signal TF. Bullish when low[k] > high[k−2], with the zone
  [high[k−2], low[k]]. It is known only at the CLOSE of candle 3 (bar k), and the order is
  placed then, so the gap is unfilled at placement. Entry variants: the near edge (low[k] for
  a bullish gap) or the 50% point (consequent encroachment). Bearish gaps are the mirror.
- **E3 OB:**
  - A displacement bar k closes beyond the last CONFIRMED swing high (known at k−1), with a
    body of at least 1.0 ATR. That is the break of structure.
  - The OB is the most recent opposite-colour candle among k−1…k−5.
  - It is known only at the close of bar k.
  - Entry variants: the OB's open (the near edge) or the 50% of its high–low range.
- **Lookahead guard:** an assertion that every FVG/OB order is placed at a 1m time at or
  after the close of the bar that completes the pattern, and that all pattern bars are at or
  before that bar.
- **Geometry guard:** an assertion that the stop and target sit on the correct side of entry
  for every trade.

### Logic × entry type grid
| Logic | Context | E1 | E2 FVG (edge, 50%) | E3 OB (open, 50%) |
|---|---|---|---|---|
| L1 trend | Signal-TF AND higher-TF structure both HH+HL (mirror for shorts). For E3 only the higher TF is required, because the displacement bar is the signal-TF break itself. | EMA9 pullback | FVG in the trend direction | OB in the trend direction |
| L2 level | Levels VWAP, P, R1, S1, PDH, PDL, PWH, PWL, as one pooled set | **native: limit AT the nearest level 0.1–1.5 ATR away, both sides, OCO** (an EMA pullback is not an L2 entry, so E1 is the literal L2 entry) | FVG whose zone is within 0.25 ATR of a level, fading into it (bullish FVG sitting on support) | OB whose range is within 0.25 ATR of a level, same direction rule |
| L3 range both ways | 12-bar high/low of the signal TF | **native: limit at the 12-bar high (sell) or low (buy)** when the close is within 0.5 ATR of it | FVG pointing back into the range, formed within 0.25 ATR of the extreme (e.g. a bearish FVG after tagging the 12-bar high) | **SKIPPED:** an OB needs a break of structure, which contradicts range-bound chop |

- **L3 at 1:1:** the ladder adds and the wick-flip are dropped. With fixed 1:1 R:R the
  stop/target define the exit, and a single 1-lot position per order keeps sizing fixed.
- **Grid:** per timeframe, 5 (L1) + 5 (L2) + 3 (L3) = 13 variants. × 2 TFs = **26 per
  instrument**. × 4 instruments = **104 cells**.

### Metrics
- n, trades per session-day, net at 1.0 lot, fees in $, WR, average win/loss, PF, max
  drawdown in $, and 3 calendar folds.
- Average and median hold in minutes.
- MAE/MFE are measured on 1m bars AFTER the fill bar, up to and including the exit bar. The
  fill bar is excluded because a through-fill guarantees some adverse penetration by
  construction. Reported:
  - % of winners that were in drawdown by any amount, and by at least 0.5R.
  - % of losers that were first in profit by at least 0.5R.

### Selection, gates and controls
- The variant is picked on fold 1 per (instrument × TF × logic) and judged on folds 2–3.
- **Natural gate:** L1 → high ER; L2 and L3 → low ER. The best of 9 single gates is also
  picked on fold 1, with tercile cut-offs from fold 1 only.
- **Random control:** 300 draws for gold and NAS100 (US30 too if cheap). Each draw keeps the
  same session days and sides, picks a random signal-bar close as a market entry at the next
  1m open, and uses a 1:1 stop/target at the same R distance as the paired real trade.
- **Execution lens:** zero cost with target-first ordering, for any positive result.

### Priors
- **Tokyo** (tokyo-strategy memory, 2026-07-21) found ICT liquidity-sweep/OB confluence
  redundant on reversals and harmful on momentum. It also found raw ICT sweep-fade
  −10R out-of-sample. The expectation is that E2 and E3 add nothing over E1 and native.
- **Cost:** HTF stops are larger, so cost as a fraction of R shrinks. This is the one
  structural improvement over the 5m version.

## PART (a) and RESULTS
(appended below after the run)

## RESULTS (run 2026-09-24)

### Cost scenarios actually used (USD per 1.0-lot round trip)
- **XAUUSD:**
  - a (commission only): $10
  - **b (HEADLINE): $10 + $0.20 × 100 = $30**
  - b_sprd35: $45
  - c (old model): $45
  - The TL gold 1m file has NO bid/ask or spread column, so the $0.20 raw spread is an
    assumption, not a measurement.
- **NAS100:**
  - a: $6
  - **b (HEADLINE): $6 + 1.15 pts × $10 = $17.50** (live quote)
  - b_prop: $6 + 0.38 bp of price, about $12.8 at the 2024 ~18k level
  - c: $50
  - The 2024 NAS100 data file carries its own Spread column: median 3.42 pts, about 1.9 bp.
    That is a different feed, and much wider than the live 1.15 pts.
- **US30 / GBPJPY:** no broker quote, so the headline is c: US30 $40 (4 pts × ASSUMED
  $10/pt); GBPJPY $20.10 (0.03 × $670).
- **Slippage stress:** stop-loss exits only: +1 pt NAS100/US30, +$0.10 gold, +0.01 GBPJPY.
- The fold-1 pick is made under the headline scenario. The other scenarios re-price the SAME
  trades rather than being re-picked.

### Part (a): the earlier 5m/1m picks at 1.0 lot
L3 counts each ladder rung as 1 lot.

| Instr | Set | Logic | Pick | n | a: commission | **b: headline** | c: old model | Max DD at b | Folds at b |
|---|---|---|---|---:|---:|---:|---:|---:|---|
| XAUUSD | orig | L1 | all_0.25 | 146 | −5.0k | **−7.9k** | −10.1k | 11.1k | +452 / −2.7k / −5.7k |
| XAUUSD | orig | L2 | pivots 0.618 | 1,909 | **+21.1k** | **−17.0k** | −45.7k | 85.2k | +25.8k / −32.4k / −10.4k |
| XAUUSD | orig | L3 | 2 adds, 0.7 | 17,145 | −706k | **−1.05M** | −1.31M | 1.06M | all negative |
| XAUUSD | inv | L1 / L2 / L3 | — | — | −9.3k / −50.0k / −1.81M | **−12.0k / −76.1k / −2.17M** | −14.1k / −95.7k / −2.44M | — | — |
| NAS100 | orig | L1 | all_0.25 | 34 | −1.0k | **−1.4k** | −2.5k | 1.5k | all negative |
| NAS100 | orig | L2 | pivots 0.618 | 387 | **+4.7k** (all 3 folds +) | **+287** | −12.3k | 4.6k | −1.1k / +1.4k / −84; b_prop +2.1k |
| NAS100 | orig | L3 | 2 adds, 0.7 | 4,956 | −76.6k | **−134k** | −295k | 134k | all negative |
| NAS100 | inv | L1 / L2 / L3 | — | — | −59 / −11.8k / −109k | **−439 / −16.3k / −169k** | −1.5k / −29.1k / −338k | — | — |
| US30 | orig / inv | L1 / L2 / L3 | — | — | — | c only: −19.6k / −238k / −3.02M (orig); −14.3k / −243k / −4.34M (inv) | | | |
| GBPJPY | orig / inv | L1 / L2 / L3 | — | — | — | c only: −3.1k / −39.4k / −432k (orig); −3.4k / −41.7k / −632k (inv) | | | |

- **Only one 1m pick is positive at the headline cost:** NAS100 L2 pivots-fade, at +$287. It
  is +$4.7k at commission-only. Both figures come from 75 sessions.
- XAUUSD L2 pivots-fade at commission-only (+21k) is carried entirely by fold 1.
- **The 1m verdict stands:** dead after realistic spread.

### Part (b): HTF grid, 312 cells
78 per instrument = 26 variants × 3 R:R. Headline cost, 1.0 lot.

- **73 of 312 cells are net positive; 9 are positive in all 3 folds.**
  - XAUUSD: 42/78 positive, 5 fold-consistent.
  - NAS100: 24/78 positive, 3 fold-consistent.
  - US30: 1/78 positive, 0 fold-consistent.
  - GBPJPY: 6/78 positive, 1 fold-consistent.
- **Fold-1 picks with positive folds 2+3:** XAUUSD 13/18, NAS100 8/18, US30 0/18, GBPJPY 3/18.
- **Regime gates:**
  - The best gate picked on fold 1 beat the ungated pick on folds 2–3 in 5/18 (XAUUSD),
    8/18 (NAS100), 17/18 (US30) and 11/18 (GBPJPY) cases.
  - A gated pick was positive on folds 2–3 in only 10, 4, 0 and 1 cases.
  - On US30 and GBPJPY, gates mostly just shrink losses.
- The lookahead assertion on every FVG/OB order and the geometry assertion on every trade and
  control trade all passed.

**Reading the table columns.**
- "WR/BE" is the actual win rate against the break-even win rate after the headline cost.
- ✓ marks a cell positive in all 3 folds.
- Stop is 1×, 2× or 3× the fixed target distance. The target is 1 ATR for E1 and native
  entries, and the structural distance for E2 and E3.
- "win-DD" is the share of winners that went against the entry by any amount, and by at least
  0.5 × the stop distance, on bars after the fill.
- "losers MFE" is the share of losers that first ran at least 0.5 × the target distance in
  profit.

#### XAUUSD — headline cost `b` · 42/78 cells positive · 5 positive in all 3 folds

| TF | Logic | Entry | n (1:1) | /day | hold avg/med min | 1:1 net · WR/BE | 2:1 net · WR/BE | 3:1 net · WR/BE | win-DD any / ≥0.5R (1:1) | losers MFE ≥0.5 tgt (1:1) |
|---|---|---|---:|---:|---|---|---|---|---|---|
| 15min | L1 | E1 ema9 | 123 | 0.55 | 42/25 | +16,694✓ · 57/51% | +1,566 · 68/68% | +4,532 · 74/76% | 87% / 23% | 28% |
| 15min | L1 | E2 ce50 | 141 | 0.63 | 46/23 | +9,868 · 51/51% | +9,613✓ · 64/68% | -8,023 · 67/76% | 81% / 24% | 30% |
| 15min | L1 | E2 edge | 158 | 0.71 | 64/35 | +9,396 · 47/51% | +16,564 · 63/67% | -2,880 · 65/76% | 85% / 29% | 30% |
| 15min | L1 | E3 ce50 | 74 | 0.33 | 13/4 | +585 · 57/53% | -978 · 68/68% | -5,193 · 75/76% | 74% / 19% | 19% |
| 15min | L1 | E3 edge | 89 | 0.40 | 25/14 | -4,296 · 52/52% | +3,139 · 67/68% | -3,502 · 73/76% | 80% / 33% | 28% |
| 15min | L2 | E1 native | 2574 | 11.49 | 38/23 | -109,436 · 49/51% | +3,941 · 65/68% | -18,382 · 70/76% | 87% / 33% | 31% |
| 15min | L2 | E2 ce50 | 622 | 2.78 | 52/28 | +35,708 · 50/51% | +96,940 · 67/68% | +86,337 · 72/76% | 86% / 28% | 33% |
| 15min | L2 | E2 edge | 716 | 3.20 | 76/41 | +61,204 · 51/51% | +80,353 · 64/67% | +66,762 · 69/76% | 89% / 32% | 33% |
| 15min | L2 | E3 ce50 | 174 | 0.78 | 11/4 | -10,458 · 48/53% | -18,931 · 62/69% | -4,196 · 73/76% | 77% / 29% | 27% |
| 15min | L2 | E3 edge | 219 | 0.98 | 27/12 | -11,392 · 49/52% | +13,161 · 69/68% | +14,586 · 76/76% | 80% / 30% | 27% |
| 15min | L3 | E1 native | 2178 | 9.72 | 36/22 | -166,062 · 48/51% | -67,362 · 65/68% | -94,609 · 69/76% | 85% / 31% | 31% |
| 15min | L3 | E2 ce50 | 422 | 1.88 | 55/28 | +11,295 · 52/51% | +12,025 · 66/68% | +3,761 · 73/76% | 91% / 28% | 34% |
| 15min | L3 | E2 edge | 476 | 2.12 | 73/42 | +11,729 · 52/51% | +4,194 · 65/67% | -7,922 · 71/76% | 91% / 32% | 33% |
| 1h | L1 | E1 ema9 | 32 | 0.15 | 172/121 | +12,764 · 59/51% | +8,874✓ · 66/67% | -463 · 66/75% | 100% / 32% | 15% |
| 1h | L1 | E2 ce50 | 36 | 0.17 | 82/45 | -12,425 · 58/51% | +9,134 · 81/67% | +1,921 · 83/75% | 90% / 19% | 33% |
| 1h | L1 | E2 edge | 41 | 0.19 | 102/95 | -10,537 · 61/50% | +11,676 · 80/67% | +15,454 · 85/75% | 92% / 16% | 25% |
| 1h | L1 | E3 ce50 | 23 | 0.11 | 42/20 | +5,664✓ · 70/51% | +2,160 · 83/68% | +16,649✓ · 87/76% | 81% / 25% | 43% |
| 1h | L1 | E3 edge | 25 | 0.12 | 101/28 | -652 · 60/51% | -4,525 · 76/67% | +1,132 · 76/75% | 80% / 40% | 20% |
| 1h | L2 | E1 native | 981 | 4.52 | 139/95 | -4,595 · 51/51% | +16,923 · 63/67% | -58,605 · 66/75% | 92% / 30% | 26% |
| 1h | L2 | E2 ce50 | 197 | 0.91 | 144/100 | -15,248 · 48/51% | -29,371 · 59/67% | -55,950 · 62/75% | 88% / 24% | 25% |
| 1h | L2 | E2 edge | 245 | 1.13 | 204/140 | +14,111 · 50/51% | -2,638 · 57/67% | -21,517 · 61/75% | 94% / 23% | 25% |
| 1h | L2 | E3 ce50 | 49 | 0.23 | 35/12 | +1,917 · 57/52% | -200 · 73/68% | +15,866 · 78/76% | 75% / 21% | 43% |
| 1h | L2 | E3 edge | 58 | 0.27 | 76/28 | +2,421 · 57/51% | +2,125 · 75/67% | +4,917 · 75/76% | 85% / 30% | 24% |
| 1h | L3 | E1 native | 517 | 2.38 | 134/95 | -116,933 · 44/51% | -129,945 · 59/67% | -50,176 · 64/75% | 95% / 38% | 37% |
| 1h | L3 | E2 ce50 | 81 | 0.37 | 148/115 | +9,717 · 47/51% | -1,671 · 56/67% | -11,198 · 60/75% | 92% / 26% | 16% |
| 1h | L3 | E2 edge | 89 | 0.41 | 187/155 | +12,459 · 46/51% | -11,878 · 50/67% | -25,589 · 54/75% | 98% / 22% | 23% |

#### NAS100 — headline cost `b` · 24/78 cells positive · 3 positive in all 3 folds

| TF | Logic | Entry | n (1:1) | /day | hold avg/med min | 1:1 net · WR/BE | 2:1 net · WR/BE | 3:1 net · WR/BE | win-DD any / ≥0.5R (1:1) | losers MFE ≥0.5 tgt (1:1) |
|---|---|---|---:|---:|---|---|---|---|---|---|
| 15min | L1 | E1 ema9 | 24 | 0.33 | 50/21 | -2,027 · 38/54% | -1,723 · 64/69% | -2,303 · 73/77% | 78% / 44% | 33% |
| 15min | L1 | E2 ce50 | 44 | 0.60 | 48/30 | -1,678 · 48/54% | -2,081 · 66/70% | -3,895 · 73/77% | 95% / 48% | 52% |
| 15min | L1 | E2 edge | 49 | 0.67 | 70/33 | -1,602 · 47/53% | -1,259 · 65/69% | -1,603 · 73/77% | 91% / 43% | 31% |
| 15min | L1 | E3 ce50 | 27 | 0.37 | 4/1 | -1,095 · 33/60% | -2,243 · 41/73% | -2,405 · 52/80% | 44% / 33% | 39% |
| 15min | L1 | E3 edge | 33 | 0.45 | 13/3 | -1,290 · 45/55% | -4,059 · 52/70% | -4,472 · 58/77% | 60% / 7% | 22% |
| 15min | L2 | E1 native | 705 | 9.66 | 48/20 | -25,336 · 46/54% | -29,596 · 58/69% | -24,035 · 64/77% | 87% / 30% | 34% |
| 15min | L2 | E2 ce50 | 221 | 3.03 | 55/28 | -3,315 · 53/54% | -1,983 · 66/69% | -5,348 · 70/77% | 91% / 27% | 32% |
| 15min | L2 | E2 edge | 249 | 3.41 | 86/44 | -1,045 · 51/53% | +1,039 · 63/68% | -2,014 · 66/76% | 92% / 27% | 34% |
| 15min | L2 | E3 ce50 | 53 | 0.73 | 6/2 | -3,469 · 34/57% | -4,795 · 43/72% | -5,071 · 46/79% | 44% / 17% | 23% |
| 15min | L2 | E3 edge | 62 | 0.85 | 16/6 | +524 · 52/55% | -2,002 · 60/70% | -883 · 67/78% | 75% / 12% | 23% |
| 15min | L3 | E1 native | 640 | 8.77 | 48/22 | -13,451 · 48/54% | -21,565 · 60/69% | -23,114 · 65/77% | 85% / 33% | 28% |
| 15min | L3 | E2 ce50 | 126 | 1.73 | 50/25 | -1,993 · 48/53% | -3,210 · 61/69% | -3,524 · 66/77% | 93% / 32% | 30% |
| 15min | L3 | E2 edge | 137 | 1.88 | 72/35 | -847 · 50/53% | -2,188 · 62/69% | -3,160 · 66/76% | 91% / 29% | 31% |
| 1h | L1 | E1 ema9 | 7 | 0.11 | 90/60 | -499 · 43/52% | +1,801 · 86/68% | +1,437 · 86/76% | 100% / 0% | 50% |
| 1h | L1 | E2 ce50 | 4 | 0.06 | 43/39 | -73 · 50/54% | -471 · 50/70% | -869 · 50/77% | 100% / 0% | 0% |
| 1h | L1 | E2 edge | 7 | 0.11 | 254/93 | -1,831 · 43/52% | -723 · 57/68% | -1,166 · 57/76% | 100% / 0% | 50% |
| 1h | L1 | E3 ce50 | 2 | 0.03 | 2/2 | +232 · 100/57% | +232 · 100/71% | +232 · 100/78% | 50% / 50% | nan% |
| 1h | L1 | E3 edge | 2 | 0.03 | 4/4 | +297 · 100/55% | +297 · 100/70% | +297 · 100/78% | 50% / 0% | nan% |
| 1h | L2 | E1 native | 245 | 3.71 | 143/59 | -8,233 · 50/52% | -7,486 · 63/68% | +2,897 · 70/76% | 87% / 25% | 35% |
| 1h | L2 | E2 ce50 | 83 | 1.26 | 107/60 | +2,856 · 53/52% | +2,947 · 66/68% | +6,849 · 74/76% | 93% / 34% | 21% |
| 1h | L2 | E2 edge | 100 | 1.52 | 175/113 | +6,547 · 58/52% | +11,458 · 74/68% | +15,457✓ · 80/76% | 91% / 22% | 29% |
| 1h | L2 | E3 ce50 | 15 | 0.23 | 30/3 | -301 · 60/54% | -675 · 67/69% | +1 · 80/77% | 56% / 33% | 33% |
| 1h | L2 | E3 edge | 20 | 0.30 | 33/7 | -744 · 50/53% | -2,256 · 50/68% | -669 · 60/76% | 70% / 20% | 60% |
| 1h | L3 | E1 native | 171 | 2.59 | 128/65 | +751 · 53/52% | -1,230 · 64/68% | -1,649 · 67/76% | 92% / 37% | 27% |
| 1h | L3 | E2 ce50 | 38 | 0.58 | 111/64 | +1,956 · 50/52% | -1,083 · 55/68% | +3,005✓ · 69/76% | 100% / 26% | 11% |
| 1h | L3 | E2 edge | 40 | 0.61 | 158/106 | +2,923✓ · 57/51% | +222 · 65/68% | +2,015 · 73/76% | 100% / 22% | 12% |

#### US30 — headline cost `c` · 1/78 cells positive · 0 positive in all 3 folds

| TF | Logic | Entry | n (1:1) | /day | hold avg/med min | 1:1 net · WR/BE | 2:1 net · WR/BE | 3:1 net · WR/BE | win-DD any / ≥0.5R (1:1) | losers MFE ≥0.5 tgt (1:1) |
|---|---|---|---:|---:|---|---|---|---|---|---|
| 15min | L1 | E1 ema9 | 427 | 0.54 | 51/28 | -24,307 · 48/55% | -33,447 · 61/70% | -31,743 · 66/78% | 86% / 32% | 30% |
| 15min | L1 | E2 ce50 | 487 | 0.62 | 38/23 | -29,269 · 48/55% | -20,448 · 64/70% | -21,699 · 70/78% | 85% / 31% | 36% |
| 15min | L1 | E2 edge | 523 | 0.66 | 54/34 | -33,779 · 49/54% | -24,526 · 64/70% | -26,926 · 69/77% | 89% / 31% | 29% |
| 15min | L1 | E3 ce50 | 317 | 0.40 | 7/2 | -9,854 · 49/59% | -3,699 · 66/72% | -6,184 · 73/79% | 71% / 31% | 22% |
| 15min | L1 | E3 edge | 351 | 0.44 | 19/7 | -19,929 · 46/56% | -16,876 · 65/70% | -11,385 · 72/78% | 78% / 35% | 29% |
| 15min | L2 | E1 native | 9472 | 12.01 | 42/18 | -435,428 · 49/55% | -427,187 · 63/70% | -297,563 · 69/77% | 87% / 33% | 29% |
| 15min | L2 | E2 ce50 | 2548 | 3.23 | 48/25 | -83,651 · 48/55% | -46,393 · 64/70% | -32,480 · 70/77% | 87% / 31% | 31% |
| 15min | L2 | E2 edge | 2749 | 3.48 | 74/40 | -153,252 · 46/54% | -129,451 · 60/69% | -112,063 · 65/77% | 90% / 32% | 30% |
| 15min | L2 | E3 ce50 | 807 | 1.02 | 10/3 | -50,381 · 46/58% | -55,687 · 63/72% | -69,086 · 70/79% | 72% / 28% | 26% |
| 15min | L2 | E3 edge | 889 | 1.13 | 22/8 | -70,932 · 45/55% | -88,323 · 62/70% | -70,984 · 70/78% | 78% / 32% | 26% |
| 15min | L3 | E1 native | 7612 | 9.65 | 45/22 | -406,638 · 47/55% | -332,815 · 62/70% | -247,316 · 69/77% | 87% / 33% | 29% |
| 15min | L3 | E2 ce50 | 1647 | 2.09 | 46/24 | -41,030 · 49/54% | -24,235 · 64/70% | -35,458 · 69/77% | 86% / 33% | 32% |
| 15min | L3 | E2 edge | 1755 | 2.22 | 62/36 | -81,646 · 48/54% | -70,395 · 62/69% | -91,469 · 66/77% | 89% / 34% | 31% |
| 1h | L1 | E1 ema9 | 114 | 0.15 | 115/66 | -8,391 · 46/52% | -4,032 · 59/68% | -15,136 · 64/76% | 81% / 28% | 33% |
| 1h | L1 | E2 ce50 | 107 | 0.14 | 101/51 | -8,875 · 49/53% | +3,127 · 64/69% | -1,850 · 70/76% | 88% / 31% | 29% |
| 1h | L1 | E2 edge | 125 | 0.16 | 140/81 | -11,874 · 50/52% | -4,997 · 62/68% | -3,459 · 70/76% | 89% / 27% | 29% |
| 1h | L1 | E3 ce50 | 105 | 0.13 | 21/5 | -4,039 · 46/55% | -6,347 · 60/70% | -5,536 · 69/77% | 71% / 29% | 28% |
| 1h | L1 | E3 edge | 117 | 0.15 | 37/11 | -3,626 · 48/53% | -7,846 · 62/69% | -12,759 · 66/77% | 82% / 21% | 26% |
| 1h | L2 | E1 native | 3567 | 4.56 | 140/59 | -188,087 · 50/52% | -123,734 · 64/68% | -57,158 · 69/76% | 92% / 31% | 30% |
| 1h | L2 | E2 ce50 | 1026 | 1.31 | 113/52 | -57,813 · 50/53% | -95,473 · 62/68% | -105,246 · 69/76% | 88% / 31% | 27% |
| 1h | L2 | E2 edge | 1161 | 1.48 | 161/88 | -13,786 · 51/52% | -53,678 · 63/68% | -77,635 · 67/76% | 91% / 32% | 28% |
| 1h | L2 | E3 ce50 | 301 | 0.38 | 20/5 | -17,561 · 46/55% | -11,529 · 63/70% | -12,227 · 69/77% | 75% / 30% | 21% |
| 1h | L2 | E3 edge | 344 | 0.44 | 42/14 | -19,276 · 47/53% | -16,463 · 61/69% | -28,217 · 66/76% | 80% / 29% | 27% |
| 1h | L3 | E1 native | 2013 | 2.57 | 122/66 | -168,113 · 47/52% | -104,006 · 62/68% | -142,467 · 66/76% | 92% / 33% | 28% |
| 1h | L3 | E2 ce50 | 368 | 0.47 | 102/50 | -29,580 · 51/52% | -50,059 · 59/68% | -64,924 · 64/76% | 89% / 27% | 27% |
| 1h | L3 | E2 edge | 410 | 0.52 | 140/82 | -26,372 · 49/52% | -44,192 · 58/68% | -69,582 · 61/76% | 92% / 29% | 28% |

#### GBPJPY — headline cost `c` · 6/78 cells positive · 1 positive in all 3 folds

| TF | Logic | Entry | n (1:1) | /day | hold avg/med min | 1:1 net · WR/BE | 2:1 net · WR/BE | 3:1 net · WR/BE | win-DD any / ≥0.5R (1:1) | losers MFE ≥0.5 tgt (1:1) |
|---|---|---|---:|---:|---|---|---|---|---|---|
| 15min | L1 | E1 ema9 | 171 | 0.64 | 45/31 | -3,040 · 54/62% | -3,410 · 66/75% | -4,033 · 70/81% | 89% / 36% | 34% |
| 15min | L1 | E2 ce50 | 167 | 0.62 | 42/23 | -3,856 · 47/62% | -4,369 · 60/74% | -3,231 · 66/81% | 83% / 23% | 31% |
| 15min | L1 | E2 edge | 188 | 0.70 | 58/30 | -5,272 · 48/60% | -4,992 · 61/73% | -4,900 · 65/80% | 84% / 26% | 33% |
| 15min | L1 | E3 ce50 | 102 | 0.38 | 9/3 | -2,050 · 45/72% | -2,087 · 58/81% | -2,724 · 65/86% | 67% / 33% | 27% |
| 15min | L1 | E3 edge | 110 | 0.41 | 28/8 | -1,808 · 50/64% | -2,821 · 61/76% | -2,961 · 65/82% | 80% / 35% | 31% |
| 15min | L2 | E1 native | 3297 | 12.26 | 41/26 | -72,968 · 49/62% | -56,124 · 63/74% | -52,247 · 68/81% | 89% / 32% | 33% |
| 15min | L2 | E2 ce50 | 793 | 2.95 | 60/33 | -19,831 · 48/61% | -16,039 · 63/74% | -14,234 · 68/80% | 85% / 36% | 37% |
| 15min | L2 | E2 edge | 882 | 3.28 | 88/52 | -25,980 · 47/58% | -21,994 · 58/72% | -20,239 · 62/79% | 91% / 34% | 33% |
| 15min | L2 | E3 ce50 | 216 | 0.80 | 9/3 | -4,326 · 50/71% | -4,334 · 64/81% | -5,406 · 70/86% | 66% / 22% | 30% |
| 15min | L2 | E3 edge | 245 | 0.91 | 29/10 | -5,247 · 49/63% | -4,745 · 64/76% | -4,340 · 71/82% | 82% / 27% | 33% |
| 15min | L3 | E1 native | 2847 | 10.58 | 42/26 | -52,388 · 51/62% | -36,863 · 66/74% | -31,421 · 71/81% | 88% / 31% | 33% |
| 15min | L3 | E2 ce50 | 546 | 2.03 | 54/32 | -13,297 · 49/61% | -11,015 · 63/74% | -5,034 · 71/80% | 85% / 32% | 39% |
| 15min | L3 | E2 edge | 602 | 2.24 | 75/44 | -12,508 · 50/59% | -7,529 · 64/72% | -3,374 · 69/79% | 90% / 33% | 32% |
| 1h | L1 | E1 ema9 | 37 | 0.14 | 150/108 | -1,843 · 41/56% | -1,880 · 51/70% | -2,211 · 54/78% | 87% / 20% | 36% |
| 1h | L1 | E2 ce50 | 48 | 0.18 | 133/102 | -1,242 · 50/56% | -2,050 · 57/71% | -2,674 · 60/78% | 92% / 38% | 29% |
| 1h | L1 | E2 edge | 50 | 0.19 | 150/131 | -1,546 · 46/56% | -2,268 · 51/70% | -2,515 · 55/78% | 100% / 35% | 33% |
| 1h | L1 | E3 ce50 | 36 | 0.14 | 36/23 | -114 · 58/61% | +188 · 69/74% | +597 · 78/81% | 100% / 33% | 33% |
| 1h | L1 | E3 edge | 42 | 0.16 | 84/48 | -46 · 60/58% | -738 · 62/72% | -376 · 69/79% | 100% / 44% | 53% |
| 1h | L2 | E1 native | 1260 | 4.81 | 140/97 | -21,242 · 51/56% | -13,918 · 63/71% | -14,923 · 66/78% | 92% / 31% | 30% |
| 1h | L2 | E2 ce50 | 326 | 1.24 | 159/90 | -5,320 · 50/56% | -5,863 · 59/70% | -2,376 · 64/78% | 91% / 32% | 24% |
| 1h | L2 | E2 edge | 365 | 1.39 | 205/136 | -6,734 · 50/55% | -9,980 · 56/70% | -3,703 · 62/77% | 94% / 28% | 27% |
| 1h | L2 | E3 ce50 | 85 | 0.32 | 34/13 | -216 · 59/62% | +351 · 74/74% | +2,195✓ · 82/81% | 88% / 40% | 23% |
| 1h | L2 | E3 edge | 94 | 0.36 | 96/44 | -33 · 56/57% | +679 · 68/72% | +1,106 · 74/79% | 94% / 43% | 32% |
| 1h | L3 | E1 native | 704 | 2.69 | 140/101 | -13,867 · 50/56% | -7,902 · 64/71% | -9,157 · 68/78% | 95% / 33% | 29% |
| 1h | L3 | E2 ce50 | 124 | 0.47 | 184/131 | -2,355 · 48/55% | -3,166 · 56/70% | -858 · 61/78% | 93% / 28% | 23% |
| 1h | L3 | E2 edge | 143 | 0.55 | 221/175 | -3,723 · 48/54% | -5,025 · 53/70% | -1,938 · 58/77% | 94% / 28% | 28% |


### Random control (300 draws; same sides, session days, target and R:R) for the fold-1 picks
- **XAUUSD:** 15m L2 E2 at 1:1 / 2:1 / 3:1 ranks at the 97th / 99th / 100th percentile. 15m
  L1 E2 and L3 E2 rank 91–93. All 1h picks rank between 13 and 91.
- **NAS100:** the 1h L2 E2 edge pick ranks at the 97th / 99th / 100th percentile across the
  three R:R. Every other NAS100 pick ranks between 0 and 88.
- **US30:** all 18 picks rank between 0 and 83. Several are at the 0–5th percentile.
- The long share of the gold picks is about 0.50, so the rank is not bull-market drift.

### Lenses on the only family that ranks high: L2 + E2 (FVG sitting on a key level)

| Variant | Net (headline) | Folds | 2× cost | Stop-slip | Orders 1 min late | 5 min late | 10 min late | 1 signal bar late |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| XAU 15m edge, 1:1 | +61.2k | +10.3k / +51.9k / −1.1k | +39.7k | +58.1k | — | — | — | **−53.0k** |
| XAU 15m edge, 2:1 | +80.4k | +35.9k / +72.8k / **−28.3k** | +61.4k | +78.8k | +54.9k | +27.1k | −2.6k | **−64.9k** |
| XAU 15m 50%, 2:1 | +96.9k | +32.2k / +89.5k / **−24.8k** | +80.4k | +95.6k | +91.0k | +72.8k | +34.3k | +18.4k |
| XAU 15m 50%, 3:1 | +86.3k | +41.0k / +73.3k / **−28.0k** | +70.6k | +85.6k | — | — | — | +11.8k |
| NAS 1h edge, 1:1 | +6.5k | +3.4k / +5.1k / −1.9k | +4.8k | +6.2k | — | — | — | −2.1k |
| NAS 1h edge, 2:1 | +11.5k | +4.2k / +7.5k / −272 | +9.9k | +11.3k | — | — | — | +5.3k |
| **NAS 1h edge, 3:1** | **+15.5k** (n = 88) | **+5.0k / +7.4k / +3.0k** | +13.9k | +15.4k | +15.2k | +15.5k | +14.4k | +5.0k |

- **Execution:** costs and stop slippage don't kill either lead.
- **Leakage / fragility:**
  - Gold decays smoothly with delay, rather than falling off a 1-minute cliff, so it is not a
    bar-close leak. But the edge-entry version flips to −$53k to −$65k when orders are one
    15m bar late: it lives in the first minutes after the gap forms.
  - NAS100 1h is insensitive to 1–10 minute delays.
- **Statistics:**
  - Every gold variant in this family LOSES in fold 3 (the most recent third, about Apr–Jul
    2026). The profit sits in fold 2.
  - The same family is negative on gold 1h (−2.6k to −56k), NAS100 15m, US30 (every TF and
    R:R), and GBPJPY.
  - The NAS100 1h 3:1 cell comes from 88 trades on 75 sessions (Jan–Apr 2024), picked from 36
    fold-1 picks and 312 cells. A 100th-percentile rank means p < 1/300 per pick, which is
    about 0.12 after Bonferroni across the 36 picks. That is not significant.
  - US30 15m L2 E2 50% at 2:1 is +$66k in the zero-cost best case (+36.6k / +0.3k / +29.3k).
    Priced at NAS100's $17.50/lot instead of the assumed $40, it would be about +$4.9k. It is
    −$46k at the assumed cost.

### Metrics the user asked about (1:1, headline cost)
- **Winners that went into drawdown first:** 75–100% dipped below entry after the fill bar.
  20–40% went at least 0.5R against before winning. A "never in drawdown" winner is rare at
  every TF.
- **Losers that were first in profit by at least 0.5 × the target:** 11–43%, typically about
  30%.
- **Hold times:** 15m signals average 11–76 minutes (median 4–42). 1h signals average 35–204
  minutes (median 12–140).
- **Frequency:** 15m L2/L3 native entries fire 7–11 trades per day on gold, and those are
  deeply negative. FVG/OB entries fire 0.1–3 per day.

### Tokyo consistency
The tokyo-strategy memory (2026-07-21) says ICT liquidity-sweep/OB confluence is redundant on
reversals and harmful on momentum. **Consistent:** E3 OB never produced a replicating
result. Its positive cells are 23–85 trades, US30 OB is negative, and OB never ranked high
against the random control. The one high-ranking family is FVG at a level (E2), which Tokyo
didn't test. It fails to replicate on US30 and on gold 1h, so it doesn't contradict Tokyo's
finding either.

### VERDICT
- **L1 (trend pullback) and L3 (range both-ways):** DEAD at every TF, entry type and R:R.
  Nothing replicates across instruments. Gold's positives are fold-2 concentrated or fewer
  than 50 trades.
- **L2 + E2 (FVG sitting on VWAP/pivot/PDH-L/PWH-L): WEAK LEAD, not deployable.**
  - Gold 15m ranks at the 97th–100th percentile against random but loses in the most recent
    third, and depends on filling within minutes of the gap forming.
  - NAS100 1h at 3:1 is the cleanest cell (3/3 folds, 100th percentile, delay-robust), but it
    is 88 trades from 4 months and doesn't survive multiple-comparison correction.
  - It is dead on US30 (3.5 years, the longest data) and on GBPJPY.
- **Next step, if any:** get 1–2 years of NAS100/MNQ 1m data and re-run ONLY
  `1h_L2_E2_edge_rr3to1` and `15min_L2_E2_*` as a pre-registered confirmation. No new grid.
- **Higher R:R (2:1, 3:1 stop:target):** raises the win rate to 64–87%, but the break-even
  win rate rises in step (68–81%). It moves no cell from dead to alive except inside the one
  family above.

**Files:**
- Code: `h_ema_vwap_scalper_htf.py` and `h_ema_vwap_scalper_htf_lenses.py`
- Results: `h_ema_vwap_scalper_htf_partA.json`, `h_ema_vwap_scalper_htf_XAUUSD_NAS100.json`
  and `h_ema_vwap_scalper_htf_US30_GBPJPY.json`, plus the `.log` files
- quant-lab: strategy `ema_vwap_scalper_htf`, 114 rows per instrument (456 total)
