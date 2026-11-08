# Overnight drift on gold alone, with a beta control and scaling

Rule (frozen from h_overnight_drift): long gold 16:00 ET -> 09:00 ET next session, market at the scheduled bar open, no stop. Sizes are 1 MGC-equivalent (10 oz, $10 per $1 of gold). See the script docstring for sources and costs.

## 1. Fixed size, net of costs

### MGC_1h  (2024-04-05 -> 2026-08-27)

- overnight long, base cost: n=594 net=16,954 pf=1.22 wr=0.58 maxDD=8,523 folds=[2592, 7425, 6938]; per-year {2024: 2351.0, 2025: 10566.0, 2026: 4037.0}
- overnight long, 2x cost: n=594 net=13,842 pf=1.18 wr=0.57 maxDD=9,088 folds=[1564, 6367, 5911]; per-year {2024: 1387.0, 2025: 9266.0, 2026: 3188.0}
- day session long 09:00->16:00 (control): n=594 net=-3,479 pf=0.95 wr=0.53 maxDD=9,791 folds=[-1366, 2853, -4965]; per-year {2024: -2251.0, 2025: 1432.0, 2026: -2660.0}

### XAU_1m  (2025-09-01 -> 2026-07-17)

- overnight long, base cost: n=217 net=10,195 pf=1.23 wr=0.60 maxDD=7,142 folds=[5882, 7740, -3427]; per-year {2025: 7195.0, 2026: 3000.0}
- overnight long, 2x cost: n=217 net=7,897 pf=1.18 wr=0.60 maxDD=8,032 folds=[5184, 6920, -4207]; per-year {2025: 6392.0, 2026: 1506.0}
- overnight long, base cost + ASSUMED 6%/yr CFD financing: n=217 net=7,997 pf=1.18 wr=0.60 maxDD=7,989 folds=[5222, 6937, -4162]; per-year {2025: 6427.0, 2026: 1570.0}
- day session long 09:00->16:00 (control): n=218 net=-10,325 pf=0.76 wr=0.49 maxDD=12,746 folds=[106, -4675, -5755]; per-year {2025: -1261.0, 2026: -9064.0}

### GLD_1d  (2016-08-29 -> 2026-08-27)

- overnight long, base cost: n=2509 net=23,780 pf=1.16 wr=0.54 maxDD=8,656 folds=[435, 1744, 21601]; per-year {2016: -57.0, 2017: -205.0, 2018: -257.0, 2019: 1122.0, 2020: 4252.0, 2021: -1186.0, 2022: -1629.0, 2023: 749.0, 2024: 4726.0, 2025: 12450.0, 2026: 3816.0}
- overnight long, 2x cost: n=2509 net=13,499 pf=1.09 wr=0.52 maxDD=9,607 folds=[-1738, -1276, 16513]; per-year {2016: -269.0, 2017: -836.0, 2018: -891.0, 2019: 420.0, 2020: 3354.0, 2021: -2092.0, 2022: -2533.0, 2023: -223.0, 2024: 3521.0, 2025: 10723.0, 2026: 2325.0}
- overnight long, charged the corrected MGC cost ($5.24/night): n=2509 net=20,914 pf=1.14 wr=0.53 maxDD=8,264 folds=[-1772, 373, 22314]; per-year {2016: -291.0, 2017: -889.0, 2018: -933.0, 2019: 504.0, 2020: 3824.0, 2021: -1600.0, 2022: -2041.0, 2023: 410.0, 2024: 4611.0, 2025: 12866.0, 2026: 4453.0}
- day session long 09:00->16:00 (control): n=2509 net=-12,673 pf=0.90 wr=0.49 maxDD=16,009 folds=[-2769, -3391, -6513]; per-year {2016: -1741.0, 2017: 497.0, 2018: -1402.0, 2019: -166.0, 2020: -2007.0, 2021: -2044.0, 2022: 23.0, 2023: -563.0, 2024: -1477.0, 2025: 1096.0, 2026: -4889.0}

## 2. Beta control

- **MGC_1h** (585 paired dates, gross $ per 1-MGC-equivalent): overnight 23,446, day -1,428, 24h hold 22,018. Pro-rata share 0.70 -> expected overnight 15,317; actual share 1.06. **Excess over beta 8,129** (t=1.31, p=0.192).
  - gold > 50DMA: 427 dates, overnight 20,607, day 3,489, excess 3,845 (t=0.75)
  - gold < 50DMA: 158 dates, overnight 2,839, day -4,917, excess 4,285 (t=1.21)
  - per year (overnight / day / excess): 2024: 2,269 / -1,813 / 1,952; 2025: 12,017 / 2,196 / 2,130; 2026: 9,161 / -1,811 / 4,048
- **XAU_1m** (211 paired dates, gross $ per 1-MGC-equivalent): overnight 12,005, day -9,009, 24h hold 2,995. Pro-rata share 0.70 -> expected overnight 2,084; actual share 4.01. **Excess over beta 9,921** (t=1.84, p=0.067).
  - gold > 50DMA: 131 dates, overnight 12,165, day -2,371, excess 5,351 (t=1.25)
  - gold < 50DMA: 80 dates, overnight -160, day -6,639, excess 4,569 (t=1.38)
  - per year (overnight / day / excess): 2025: 7,658 / -966 / 3,003; 2026: 4,346 / -8,043 / 6,918
- **GLD_1d** (2505 paired dates, gross $ per 1-MGC-equivalent): overnight 34,179, day -2,270, 24h hold 31,909. Pro-rata share 0.73 -> expected overnight 23,267; actual share 1.07. **Excess over beta 10,912** (t=1.59, p=0.113).
  - gold > 50DMA: 1429 dates, overnight 23,530, day 4,397, excess 3,166 (t=0.57)
  - gold < 50DMA: 1075 dates, overnight 10,708, day -6,594, excess 7,708 (t=1.88)
  - per year (overnight / day / excess): 2016: 164 / -1,520 / 1,153; 2017: 321 / 1,128 / -736; 2018: 525 / -651 / 617; 2019: 1,733 / 536 / 78; 2020: 4,868 / -1,110 / 2,128; 2021: 328 / -1,138 / 919; 2022: -1,130 / 926 / -982; 2023: 1,872 / 408 / 209; 2024: 5,734 / -273 / 1,752; 2025: 13,824 / 2,822 / 1,687; 2026: 5,942 / -3,398 / 4,087

## 3. Scaling

Risk unit for fixed-fractional = 2 x stdev of the previous 20 nights' overnight $ move per contract. It only sets size; no stop is placed, so a night can lose more than the 'risk'. Vol targeting sizes so one night's expected stdev = X% of equity. Contracts are capped by margin (~5.5% of notional per contract). Monte Carlo = 1000 stationary block-bootstrap paths (mean block 20 nights) of the same nights.

### Scaling on MGC_1h (574 nights, 2.3 years; first 20 nights used only to seed the vol estimate)

| start | granularity | policy | final | CAGR | maxDD | worst night | longest losing streak | nights traded | MC p5 / p50 / p95 final | P(DD>=30%) | P(DD>=50%) |
|---:|---|---|---:|---:|---:|---:|---:|---:|---|---:|---:|
| $10,000 | whole MGC | fixed_1ct | $27,679 | 55.3% | 25.9% | $-3,769 (-12.0%) | 6 | 574/574 | $11,308 / $26,952 / $42,957 | 60% | 22% |
| $10,000 | whole MGC | ff_0.5 | $10,000 | 0.0% | 0.0% | $-0 (-0.0%) | 0 | 0/574 | $10,000 / $10,000 / $10,000 | 0% | 0% |
| $10,000 | whole MGC | ff_1 | $10,000 | 0.0% | 0.0% | $-0 (-0.0%) | 0 | 0/574 | $10,000 / $10,000 / $10,000 | 0% | 0% |
| $10,000 | whole MGC | ff_2 | $10,000 | 0.0% | 0.0% | $-0 (-0.0%) | 0 | 0/574 | $10,000 / $10,000 / $10,000 | 0% | 0% |
| $10,000 | whole MGC | vt_3 | $40,372 | 82.8% | 37.2% | $-7,538 (-21.5%) | 6 | 552/574 | $13,349 / $35,072 / $147,591 | 48% | 1% |
| $10,000 | whole MGC | vt_5 | $85,284 | 152.6% | 62.5% | $-52,769 (-33.6%) | 6 | 574/574 | $12,972 / $82,027 / $906,427 | 100% | 61% |
| $10,000 | 0.1 ct (1 oz CFD) | ff_0.5 | $11,107 | 4.6% | 2.3% | $-161 (-1.6%) | 6 | 270/574 | $10,348 / $11,104 / $11,930 | 0% | 0% |
| $10,000 | 0.1 ct (1 oz CFD) | ff_1 | $12,573 | 10.4% | 7.7% | $-377 (-3.0%) | 6 | 492/574 | $11,291 / $13,058 / $16,177 | 0% | 0% |
| $10,000 | 0.1 ct (1 oz CFD) | ff_2 | $17,954 | 28.8% | 15.5% | $-1,131 (-6.8%) | 6 | 574/574 | $12,121 / $17,921 / $28,852 | 0% | 0% |
| $10,000 | 0.1 ct (1 oz CFD) | vt_3 | $54,526 | 108.2% | 43.4% | $-14,700 (-21.6%) | 6 | 574/574 | $14,615 / $50,848 / $220,261 | 84% | 12% |
| $10,000 | 0.1 ct (1 oz CFD) | vt_5 | $106,523 | 178.0% | 65.5% | $-70,108 (-36.5%) | 6 | 574/574 | $12,414 / $100,665 / $1,109,473 | 100% | 78% |
| $100,000 | whole MGC | fixed_1ct | $117,679 | 7.3% | 6.9% | $-3,769 (-3.1%) | 6 | 574/574 | $102,107 / $117,018 / $132,957 | 0% | 0% |
| $100,000 | whole MGC | ff_0.5 | $111,074 | 4.6% | 2.3% | $-1,612 (-1.6%) | 6 | 270/574 | $103,480 / $111,035 / $119,300 | 0% | 0% |
| $100,000 | whole MGC | ff_1 | $125,726 | 10.4% | 7.7% | $-3,769 (-3.0%) | 6 | 492/574 | $112,906 / $130,579 / $161,767 | 0% | 0% |
| $100,000 | whole MGC | ff_2 | $179,540 | 28.8% | 15.5% | $-11,308 (-6.8%) | 6 | 574/574 | $121,211 / $179,213 / $288,521 | 0% | 0% |
| $100,000 | whole MGC | vt_3 | $545,263 | 108.2% | 43.4% | $-147,001 (-21.6%) | 6 | 574/574 | $146,153 / $508,482 / $2,202,608 | 84% | 12% |
| $100,000 | whole MGC | vt_5 | $1,065,235 | 178.0% | 65.5% | $-701,079 (-36.5%) | 6 | 574/574 | $124,143 / $1,006,650 / $11,094,731 | 100% | 78% |
| $100,000 | 0.1 ct (1 oz CFD) | ff_0.5 | $117,544 | 7.2% | 4.2% | $-1,885 (-1.8%) | 6 | 574/574 | $106,055 / $117,246 / $132,636 | 0% | 0% |
| $100,000 | 0.1 ct (1 oz CFD) | ff_1 | $139,573 | 15.5% | 7.9% | $-4,523 (-3.7%) | 6 | 574/574 | $112,057 / $137,959 / $176,578 | 0% | 0% |
| $100,000 | 0.1 ct (1 oz CFD) | ff_2 | $190,612 | 32.2% | 16.1% | $-13,192 (-7.3%) | 6 | 574/574 | $123,439 / $188,688 / $307,277 | 0% | 0% |
| $100,000 | 0.1 ct (1 oz CFD) | vt_3 | $546,968 | 108.4% | 44.2% | $-151,901 (-22.0%) | 6 | 574/574 | $147,351 / $526,349 / $2,266,267 | 86% | 14% |
| $100,000 | 0.1 ct (1 oz CFD) | vt_5 | $1,092,265 | 181.1% | 65.6% | $-721,056 (-36.7%) | 6 | 574/574 | $120,753 / $1,024,507 / $11,319,911 | 100% | 80% |

Smallest account to size >= 1 whole MGC at median conditions (overnight $ stdev 268/ct, gold $3,386): ff_0.5: $107,003, ff_1: $53,501, ff_2: $26,751, vt_3: $8,917, vt_5: $5,350; margin alone (~5.5% of notional) needs $1,863.

### Scaling on GLD_1d (2489 nights, 9.9 years; first 20 nights used only to seed the vol estimate)

| start | granularity | policy | final | CAGR | maxDD | worst night | longest losing streak | nights traded | MC p5 / p50 / p95 final | P(DD>=30%) | P(DD>=50%) |
|---:|---|---|---:|---:|---:|---:|---:|---:|---|---:|---:|
| $10,000 | whole MGC | fixed_1ct | $30,954 | 12.1% | 40.5% | $-3,185 (-9.2%) | 12 | 2489/2489 | $10,740 / $29,755 / $51,467 | 68% | 27% |
| $10,000 | whole MGC | ff_0.5 | $10,000 | 0.0% | 0.0% | $-0 (-0.0%) | 0 | 0/2489 | $10,000 / $10,000 / $10,000 | 0% | 0% |
| $10,000 | whole MGC | ff_1 | $9,089 | -1.0% | 9.1% | $-231 (-2.3%) | 5 | 41/2489 | $8,660 / $9,390 / $10,316 | 0% | 0% |
| $10,000 | whole MGC | ff_2 | $9,097 | -1.0% | 32.9% | $-462 (-4.7%) | 12 | 912/2489 | $6,277 / $8,959 / $15,548 | 55% | 2% |
| $10,000 | whole MGC | vt_3 | $2,824 | -12.0% | 73.8% | $-1,154 (-13.4%) | 12 | 1411/2489 | $1,513 / $15,013 / $337,945 | 100% | 98% |
| $10,000 | whole MGC | vt_5 | $1,300 | -18.6% | 90.1% | $-2,078 (-25.6%) | 12 | 1069/2489 | $726 / $4,056 / $971,597 | 100% | 100% |
| $10,000 | 0.1 ct (1 oz CFD) | ff_0.5 | $11,083 | 1.0% | 10.0% | $-179 (-1.6%) | 12 | 2175/2489 | $9,339 / $11,198 / $13,311 | 0% | 0% |
| $10,000 | 0.1 ct (1 oz CFD) | ff_1 | $13,722 | 3.2% | 20.5% | $-358 (-3.2%) | 12 | 2432/2489 | $9,040 / $13,427 / $20,938 | 4% | 0% |
| $10,000 | 0.1 ct (1 oz CFD) | ff_2 | $17,775 | 6.0% | 38.0% | $-1,075 (-6.6%) | 12 | 2489/2489 | $7,413 / $18,110 / $47,051 | 66% | 10% |
| $10,000 | 0.1 ct (1 oz CFD) | vt_3 | $28,540 | 11.2% | 84.0% | $-6,052 (-19.3%) | 12 | 2489/2489 | $1,642 / $27,398 / $483,318 | 100% | 99% |
| $10,000 | 0.1 ct (1 oz CFD) | vt_5 | $12,173 | 2.0% | 97.3% | $-5,733 (-31.1%) | 12 | 2489/2489 | $118 / $10,385 / $1,263,939 | 100% | 100% |
| $100,000 | whole MGC | fixed_1ct | $120,954 | 1.9% | 6.6% | $-3,185 (-2.6%) | 12 | 2489/2489 | $102,341 / $119,823 / $141,467 | 0% | 0% |
| $100,000 | whole MGC | ff_0.5 | $110,831 | 1.0% | 10.0% | $-1,792 (-1.6%) | 12 | 2175/2489 | $93,391 / $111,985 / $133,108 | 0% | 0% |
| $100,000 | whole MGC | ff_1 | $137,217 | 3.2% | 20.5% | $-3,584 (-3.2%) | 12 | 2432/2489 | $90,403 / $134,274 / $209,381 | 4% | 0% |
| $100,000 | whole MGC | ff_2 | $177,746 | 6.0% | 38.0% | $-10,751 (-6.6%) | 12 | 2489/2489 | $74,128 / $181,096 / $470,506 | 66% | 10% |
| $100,000 | whole MGC | vt_3 | $285,398 | 11.2% | 84.0% | $-60,517 (-19.3%) | 12 | 2489/2489 | $16,419 / $273,976 / $4,833,180 | 100% | 99% |
| $100,000 | whole MGC | vt_5 | $121,733 | 2.0% | 97.3% | $-57,332 (-31.1%) | 12 | 2489/2489 | $1,184 / $103,851 / $12,639,392 | 100% | 100% |
| $100,000 | 0.1 ct (1 oz CFD) | ff_0.5 | $120,275 | 1.9% | 11.1% | $-1,792 (-1.6%) | 12 | 2489/2489 | $96,405 / $120,682 / $152,758 | 0% | 0% |
| $100,000 | 0.1 ct (1 oz CFD) | ff_1 | $144,623 | 3.8% | 21.4% | $-4,300 (-3.4%) | 12 | 2489/2489 | $91,689 / $144,467 / $232,321 | 8% | 0% |
| $100,000 | 0.1 ct (1 oz CFD) | ff_2 | $193,477 | 6.9% | 39.1% | $-11,647 (-6.8%) | 12 | 2489/2489 | $78,279 / $195,097 / $506,795 | 70% | 11% |
| $100,000 | 0.1 ct (1 oz CFD) | vt_3 | $280,366 | 11.0% | 85.0% | $-62,428 (-20.4%) | 12 | 2489/2489 | $18,801 / $289,563 / $5,018,678 | 100% | 99% |
| $100,000 | 0.1 ct (1 oz CFD) | vt_5 | $115,568 | 1.5% | 98.4% | $-58,925 (-33.4%) | 12 | 2489/2489 | $1,299 / $118,197 / $12,889,692 | 100% | 100% |

Smallest account to size >= 1 whole MGC at median conditions (overnight $ stdev 112/ct, gold $1,807): ff_0.5: $44,624, ff_1: $22,312, ff_2: $11,156, vt_3: $3,719, vt_5: $2,231; margin alone (~5.5% of notional) needs $994.


## 4. Lenses

- **Leakage:** clean. Entries and exits are fixed clock times. The 50-DMA regime uses a close from before the entry date. Vol sizing uses only the previous 20 nights.
- **Execution:** MGC stays positive at 2x cost (+13.8k, all folds positive). XAUUSD loses ~22% to an ASSUMED 6%/yr CFD financing charge (the real swap rate for the account is unknown), and its fold 3 (2026) is negative at every cost level. MGC legs are roll-adjusted with 1 extra tick/side. Worst single night: 2026-01-29, -$3,769 per MGC (gold 5,423 -> 5,047). No stop is placed, so a night like that hits in full.
- **Statistics:** the three sources overlap in time (GLD contains the MGC and XAU periods), so they are not three independent confirmations. The overnight excess over the hours-pro-rata share is positive in every source but never significant (t = 1.31 / 1.84 / 1.59, p = 0.19 / 0.07 / 0.11). GLD 2016-2023 at the corrected MGC cost: gross +8,647, **net -1,016 over 7.3 years**. 2024-2026: net +21,930. The result is the 2024-26 gold bull market.

## Interpretation

- At fixed size, gold alone is positive on all three sources: MGC +17.0k (folds +2.6k / +7.4k / +6.9k), XAUUSD +10.2k (folds +5.9k / +7.7k / -3.4k), GLD-proxy 10y +20.9k at MGC cost (folds -1.8k / +0.4k / +22.3k).
- **Mostly beta.** The overnight leg captured 100-107% of gold's 24h gain (and 400% on XAU, where the day session lost). About two-thirds of the overnight $ is what holding gold for those hours is expected to earn (MGC 15.3k of 23.4k gross; GLD 23.3k of 34.2k). The remaining third is "day session loses, overnight doesn't" - consistent across sources and years, but not statistically significant, and absent in net terms before 2024.
- **Down-trends:** no protection. Overnight net was negative in 2021 (-1.6k) and 2022 (-2.0k) at MGC cost. Below the 50-DMA the overnight leg makes ~0 (MGC +2.8k gross, XAU -0.2k); it only beats the day session there because the day session loses more.
- **Scaling** multiplies this, including the beta. Over 10 years (GLD proxy), vol targeting at 3-5% of equity per night ends in 84-98% drawdowns. The only settings with tolerable 10-year drawdowns are fixed-fractional 0.5-1% (risk unit = 2 x 20-night stdev): ff_1 = 3-4% CAGR, max DD ~21%, P(DD>=30%) 4-8%. On the 2024-26 MGC window alone the same ff_1 shows 10-16% CAGR - that gap is the bull market.
- **Account size:** at today's gold (~$3.4k median in-sample, ~$5k now) and overnight stdev (~$268/MGC), ff_1 needs ~$54k to hold even 1 whole MGC. At $10k, 1 fixed MGC is ~4-5x notional leverage: 60% chance of a 30% drawdown and 22% of a 50% drawdown in the bootstrap. Below ~$50k, only 1-oz CFD steps size properly, and those carry an unknown financing cost.

Verdict: **weak - needs a forward test, not capital.** It is a leveraged long-gold position that skips the US day session. The timing part (excess over beta) is unconfirmed (best p = 0.07) and was net-flat for 2016-2023. If traded at all: fixed-fractional 0.5-1%, whole MGC only above ~$54k, and judged on 2026-27 forward nights against a plain gold hold.
