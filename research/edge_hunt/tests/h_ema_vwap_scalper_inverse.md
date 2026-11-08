# h_ema_vwap_scalper_inverse — the exact opposite of h_ema_vwap_scalper

## PRE-REGISTERED MAPPING (written 2026-09-24 before any inverse result was seen)

**Held fixed from `h_ema_vwap_scalper.md`:**
- Triggers, levels, structure filters, the 22-variant grid, and the 15-minute pending life.
- The 120-minute max hold, the no-new-orders window (last 60 minutes of the session), and
  flat 45 minutes before session end.
- Costs (`rrdata.COST`, plus a 2× stress run), 3 calendar folds, the variant picked on
  fold 1 and judged on folds 2–3, and the 9 single regime gates chosen on fold 1.
- Fixed $100 risk at the stop, then a separate compounding view at 1% of equity.

### Orders: a fade LIMIT becomes a break-direction STOP at the same price
A buy limit below the market and a sell stop at the same price trigger on the same price
path; only the direction of the position differs. So the literal inverse of "buy limit at L"
is "sell stop at L". The other candidate, a sell limit on the far side, would be a different
price and therefore a different trade.

Stop-order fills are honest:
- The order triggers when a 1m bar TOUCHES the level (high ≥ L for a buy stop, low ≤ L for
  a sell stop).
- The fill price is L, or the bar's open if the bar gapped past L, whichever is worse.
- The original fade limits needed a strict trade-through, because touching a limit does not
  guarantee a fill. Touching a stop does trigger it.
- On the fill bar only the stop may trigger, never the target. If one bar touches both stop
  and target, the stop counts. This applies to the new orientation too.

### Distance swaps (TP ↔ SL), measured from the actual fill price
| Logic | Original | Inverse |
|---|---|---|
| L1 | buy limit at the retrace level; TP +0.5 ATR, SL −1.0 ATR | **sell stop** at the same level; TP −1.0 ATR, SL +0.5 ATR |
| L2 | buy limit at the level below, TP = fib × leg, SL 1.0 ATR; sell limit at the level above (mirror); OCO | **sell stop** at the level below and **buy stop** at the level above; TP 1.0 ATR, SL = the old fib-target distance; OCO, and a same-minute double trigger is skipped |
| L3 chain | short ladder of sell limits at the 1h high, level + 0.25/0.5 ATR; SL = last rung + 1.0 ATR (fixed); TP = avg − 0.4 ATR (moves as adds fill) | **long ladder of buy stops** at the same three prices (adding WITH the break); TP = the old stop price, last rung + 1.0 ATR (fixed); SL = avg − 0.4 ATR (moves as adds fill, recomputed each bar). The 1h-low leg is the mirror image. |
| L3 exhaustion exit | exits all when a 1m bar, while in profit, prints a wick in the direction of the move that paid (lower wick on a short) of at least X of its range, with range ≥ 0.2 ATR | same rule in the new orientation: upper wick on a long, lower wick on a short |
| L3 flip | a single unit opposite the chain at the next 1m open; TP 0.4 ATR, SL 1.0 ATR | a single unit opposite the INVERSE chain; TP 1.0 ATR, SL 0.4 ATR |
| Time exits | 120 minutes or session flat, at the close | unchanged; a time exit has no direction to mirror |

- **Sizing:** $100 risk at the NEW stop distance. L3 splits that across N+1 units, each sized
  at the stop in force when it filled.
- **"Natural" regime for the inverse:** L1 inverse is a fade of trend reclaims, so it gets
  the low-ER (range) gate. The L2 and L3 inverses trade breaks, so they get the high-ER
  (trend) gate.
- **Random control:** same session days and sides as the inverse trades, a market entry at
  a random minute, and the NEW geometry: L1 TP 1.0 / SL 0.5 ATR; L2 TP 1.0 ATR / SL = the
  median realised SL/ATR; L3 runs the full inverse chain from random minutes. 300 draws.
- **Guard:** `check_geometry()` asserts, for every trade (L1, L2, L3 units, L3 flips and
  control trades), that side × (TP − entry) > 0 and side × (entry − SL) > 0. It exists
  because an inverted-sign bug faked +$1M in the first L3 run.

### Priors, stated before running
- Costs hurt BOTH directions. The originals had gross/fees ≤ 0.30, i.e. they were
  cost-dominated, so the inverse of a cost-dominated loser usually still loses. Negating the
  gross doesn't negate the fees.
- Swapping TP and SL turns a ~65% win-rate setup into a ~30–35% one. The geometry changes
  the win rate, not the expectancy.
- L3 is the only logic with a real prior. It ranked at the 0th percentile against random:
  fading the 1h high/low was worse than random entries, because those levels BREAK. Its
  inverse trades that break.

## RESULTS
(appended below after the run)

### Run 2026-09-24 — VERDICT: all three inverses DEAD

**0 of 88 grid cells are positive**, and every pick has all three folds negative. No gate
picked on fold 1 turns positive on folds 2–3. The one gate that did is XAUUSD L2 with
low-vol: +377 on folds 2+3, but its fold 1 was −2.4k, so fold 1 never picked it.

`check_geometry()` passed for every trade: L1, L2, each L3 unit, each flip and every control
trade.

Honest fills, fixed $100 risk, full cost. "Pick" is the variant chosen on fold 1.
"Gross/fees" is the break-even cost multiple; a negative value means the result loses even
before costs. "Ctrl" is the percentile rank against 300 random entries using the NEW
geometry.

| Instr | Logic | Pick | n | Net | WR | Avg W / Avg L | Folds | Gross/fees | Ctrl |
|---|---|---|---:|---:|---:|---|---|---:|---:|
| XAUUSD | L1 inv | all TFs, 50% retrace | 138 | −4,047 | 30% | 176 / −119 | −1797 / −1803 / −446 | <0 | 24 |
| XAUUSD | L2 inv | HTF S/R, fib 0.618 | 1,304 | −9,309 | 58% | 61 / −102 | −4256 / −1923 / −3130 | <0 | 20 |
| XAUUSD | L3 inv | 2 adds, wick 0.7 | 17,920 | −357,432 | 18% | 79 / −41 | −124k / −110k / −123k | <0 | 0 |
| NAS100 | L1 inv | all TFs, EMA9 | 33 | −2,929 | 39% | 93 / −207 | −861 / −360 / −1708 | 0.17 | 76 |
| NAS100 | L2 inv | pivots, fib 0.618 | 393 | −16,508 | 51% | 39 / −125 | −4138 / −6245 / −6125 | <0 | 0 |
| NAS100 | L3 inv | 2 adds, wick 0.7 | 5,216 | −317,450 | 16% | 58 / −83 | −108k / −92k / −118k | <0 | 0 |
| US30 | L1 inv | all TFs, 25% retrace | 354 | −21,123 | 33% | 143 / −160 | all 3 negative | <0 | 16 |
| US30 | L2 inv | HTF S/R, fib 0.618 | 4,770 | −108,124 | 56% | 51 / −115 | all 3 negative | <0 | 0 |
| US30 | L3 inv | 2 adds, wick 0.7 | 62,241 | −2.07M | 18% | 70 / −56 | all 3 negative | <0 | 0 |
| GBPJPY | L1 / L2 / L3 inv | — | — | −15.7k / −80.8k / −1.20M | — | — | all folds negative | <0 | n/a |

**Execution lens: intrabar ordering decides L3, and 1m bars can't resolve it.** L3 inverse
enters on a stop with a stop-loss 0.4 ATR away, which is about one 1m bar's range.

| Instr | Honest fills, 0 cost | Best-case fills, 0 cost | Best-case fills, full cost |
|---|---:|---:|---:|
| XAUUSD | −153k | **+169k** (all 3 folds +) | **+224** (−11.7k / +10.2k / +1.7k) |
| NAS100 | — | +50k | −224k |
| US30 | — | +501k | −1.03M |
| GBPJPY | — | +65k | −857k |

- "Best-case fills" assumes the fill bar's adverse extreme happened before the trigger, and
  that the target counts first.
- The zero-cost gross flips sign depending only on an assumption about order inside the
  minute. That makes it a measurement artifact, not a signal.
- Even with best-case fills, costs wipe it out: gold is flat, and the other three lose
  heavily. Tick data would be needed to settle the gross. It would not change the net
  conclusion, because the best case still can't pay retail costs.

**Statistics lens.**
- The L3 inverse ranks at the 0th percentile against a random stop-in chain on every
  instrument. The L2 inverse does too on NAS100 and US30.
- The only above-median rank is NAS100 L1 at the 76th percentile, from 33 trades, still at
  −$2.9k.

**Leakage lens.** Not run: no result was positive.

**Costs cut both ways.**
- The originals were cost-dominated: gross/fees was at most 0.30, and at or below 0 for
  most. Reversing the direction negates the gross but not the fees.
- The swap also moves the stop from 1.0 ATR to 0.4–0.5 ATR. At fixed $100 risk that roughly
  doubles position size, so the same point cost takes about twice as many dollars. Fees
  hurt the inverse MORE than the original.

**The L3 prior didn't hold.** "The levels break" was true relative to fading them, which
ranked 0th percentile. It was not true enough to buy the break with a 0.4 ATR stop through
1m noise and pay costs.

**Proportional scaling** (1% risk per trade, compounding from $10k; not used to judge edge):
- Gold: L1 ends at $6,582, L2 at $3,756, L3 at $0.
- NAS100: L1 ends at $7,420, L2 at $1,880, L3 at $0.

**Gap-through fills.** A stop rung that gaps through the target is treated as cancelled.
This happened to 207 rung fills on gold, 42 on NAS100, 733 on US30 and 9 on GBPJPY; the
counts include the control runs.

**Files:**
- Code: `h_ema_vwap_scalper_inverse.py`
- Results: `h_ema_vwap_scalper_inverse_XAUUSD_NAS100.json` and
  `h_ema_vwap_scalper_inverse_US30_GBPJPY.json`, plus the `.log` files
- quant-lab: strategy `ema_vwap_scalper_inverse`, 28 rows per instrument (112 total)
