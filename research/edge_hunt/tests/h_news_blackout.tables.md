# News blackout on the best edge-hunt candidates

Calendar: `data/econ_calendar_2024_2026.csv` - FOMC (14:00 ET), CPI/NFP/PPI (08:30 ET), real release dates (BLS archive + federalreserve.gov), incl. the 2025 shutdown shifts. Retail sales / GDP not included.
All numbers net of fees, walk-forward OOS (folds 2+3) with each strategy's own fold-1 parameters; `random-removal p` = share of 2,000 random removals of the same number of OOS trades that leave net >= the filtered net (small p = the news trades really were worse than average).

Overnight span 2024-04-05 -> 2026-08-27; OOS 2025-01-21 -> 2026-08-27; events in OOS: 67.

## overnight_drift_raw

| filter | n | removed | net | Δ vs none | PF | WR | maxDD | fold2 | fold3 | random-removal p | removed trades net |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| none | 1592 | 0 | 38368 | +0 | 1.23 | 0.56 | 13093 | 13664 | 24704 |  |  |
| gate30 | 1592 | 0 | 38368 | +0 | 1.23 | 0.56 | 13093 | 13664 | 24704 | nan | 0 |
| gate60 | 1592 | 0 | 38368 | +0 | 1.23 | 0.56 | 13093 | 13664 | 24704 | nan | 0 |
| gate120 | 1540 | 52 | 34647 | -3721 | 1.22 | 0.56 | 10551 | 12043 | 22605 | 0.84 | 3721 |
| day | 1340 | 252 | 32616 | -5752 | 1.24 | 0.56 | 9841 | 8889 | 23727 | 0.47 | 5752 |
| hold | 1376 | 216 | 36139 | -2229 | 1.26 | 0.55 | 8507 | 12941 | 23198 | 0.31 | 2229 |

Walk-forward pick of the filter on fold 1: **none** (fold-1 nets: none 22089, gate30 22089, gate60 22089, gate120 18881, day 20112, hold 18044) -> OOS net 38368, folds [13664, 24704].


## overnight_drift_corrected

| filter | n | removed | net | Δ vs none | PF | WR | maxDD | fold2 | fold3 | random-removal p | removed trades net |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| none | 1592 | 0 | 24703 | +0 | 1.15 | 0.56 | 14477 | 7861 | 16842 |  |  |
| gate30 | 1592 | 0 | 24703 | +0 | 1.15 | 0.56 | 14477 | 7861 | 16842 | nan | 0 |
| gate60 | 1592 | 0 | 24703 | +0 | 1.15 | 0.56 | 14477 | 7861 | 16842 | nan | 0 |
| gate120 | 1540 | 52 | 21376 | -3327 | 1.13 | 0.56 | 11931 | 6594 | 14782 | 0.84 | 3327 |
| day | 1340 | 252 | 20274 | -4429 | 1.14 | 0.55 | 11346 | 3596 | 16678 | 0.54 | 4429 |
| hold | 1376 | 216 | 23877 | -826 | 1.16 | 0.55 | 10479 | 7300 | 16576 | 0.32 | 826 |

Walk-forward pick of the filter on fold 1: **none** (fold-1 nets: none 16119, gate30 16119, gate60 16119, gate120 12951, day 14370, hold 12253) -> OOS net 24703, folds [7861, 16842].


### Corrected overnight legs by news type in the hold (entry-60m .. exit)

| event in hold | legs | net | mean/leg | all-legs mean |
|---|---:|---:|---:|---:|
| FOMC | 0 | 0 | nan | 15.5 |
| CPI | 72 | 1716 | 23.8 | 15.5 |
| NFP | 72 | 3278 | 45.5 | 15.5 |
| PPI | 72 | -4167 | -57.9 | 15.5 |

Mean-reversion span 2026-01-31 -> 2026-08-27; OOS 2026-04-10 -> 2026-08-27.

## mean_reversion_zscore_1h

| filter | n | removed | net | Δ vs none | PF | WR | maxDD | fold2 | fold3 | random-removal p | removed trades net |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| none | 1754 | 0 | 1214 | +0 | 1.08 | 0.57 | 1645 | 1526 | -311 |  |  |
| gate30 | 1731 | 23 | 1122 | -93 | 1.07 | 0.57 | 1653 | 1458 | -336 | 0.71 | 93 |
| gate60 | 1729 | 25 | 1114 | -100 | 1.07 | 0.57 | 1653 | 1464 | -350 | 0.72 | 100 |
| gate120 | 1682 | 72 | 1189 | -26 | 1.08 | 0.57 | 1661 | 1632 | -443 | 0.44 | 26 |
| day | 1542 | 212 | 559 | -655 | 1.04 | 0.56 | 1776 | 1215 | -656 | 0.91 | 655 |

Walk-forward pick of the filter on fold 1: **day** (fold-1 nets: none -1691, gate30 -1104, gate60 -1104, gate120 -1122, day -1055) -> OOS net 559, folds [1215, -656].

