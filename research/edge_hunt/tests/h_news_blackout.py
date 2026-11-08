"""Hypothesis: skipping trades around high-impact US news (FOMC, CPI, NFP, PPI)
improves the best edge-hunt candidates.

Calendar: data/econ_calendar_2024_2026.csv (real release dates from BLS archive
URLs and the federalreserve.gov FOMC calendar; see the .md next to it).

Strategies (parameters frozen at what their own walk-forward picked on fold 1):
  A. overnight_drift basket (long MNQ/MES/MYM/MGC 16:00->09:00 ET, 1 ct),
     both the author's raw legs and the skeptic-corrected legs
     (roll-adjusted + 1 extra tick/side, verify_exec_D).
  B. mean_reversion_zscore 1h, HL 50 perps (K=2, thr=3.0, H=4), author's
     execution model (the realistic-fill version is ~0 and not re-run here).

Filters (entry-side, mirror signals/news_filter.py gate mode: |entry - event| <= N):
  gateN  N = 30, 60, 120 minutes
  day    skip entries whose ET calendar date has an event
  hold   (overnight only) skip legs with any event inside [entry-60m, exit]:
         the entry gate can never see an 08:30 print from a 16:00 entry, so
         this is the variant that actually removes news exposure.
Each filter is a fixed rule; additionally the filter itself is walk-forward
selected on fold 1 to see which one an honest process would have picked.
Null: removing the same NUMBER of trades at random from the OOS set (2,000
draws) -> p = P(random removal >= filtered net).
"""
from __future__ import annotations
import sys, json
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path('/Users/molt_bot/latpfn-trading/research/edge_hunt')
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / 'tests'))
import common as C
import h_overnight_drift as H
import verify_overnight_drift_execution as V
import h_mean_reversion_zscore as M

SCRATCH = Path('/private/tmp/claude-501/-Users-molt-bot/c2b5a353-cd35-4dae-8601-e9c6093cbb44/scratchpad')
V.SP = SCRATCH                                # ETF-proxy cache for roll detection
ET = 'America/New_York'
STRAT = 'news_blackout'
OUT_MD = Path(__file__).with_suffix('.md')
RNG = np.random.default_rng(11)

CAL = pd.read_csv(ROOT / 'data/econ_calendar_2024_2026.csv', parse_dates=['dt_utc'])
EV = pd.DatetimeIndex(pd.to_datetime(CAL['dt_utc'], utc=True)).sort_values()
EV_DATES = set(pd.to_datetime(CAL['date']).dt.date)
FILTERS = ['none', 'gate30', 'gate60', 'gate120', 'day']


def mask_keep(trades: pd.DataFrame, filt: str) -> np.ndarray:
    if filt == 'none' or not len(trades):
        return np.ones(len(trades), bool)
    et = pd.to_datetime(trades['entry_time'], utc=True)
    if filt.startswith('gate'):
        n = pd.Timedelta(minutes=int(filt[4:]))
        i = EV.searchsorted(et)
        nxt = EV[np.minimum(i, len(EV) - 1)]; prv = EV[np.maximum(i - 1, 0)]
        near = ((nxt - et).to_numpy() <= n.to_timedelta64()) & ((nxt - et).to_numpy() >= np.timedelta64(0)) | \
               ((et - prv).to_numpy() <= n.to_timedelta64()) & ((et - prv).to_numpy() >= np.timedelta64(0))
        return ~near
    if filt == 'day':
        d = et.dt.tz_convert(ET).dt.date
        return ~d.isin(EV_DATES).to_numpy()
    if filt == 'hold':
        xt = pd.to_datetime(trades['exit_time'], utc=True)
        lo = EV.searchsorted(et - pd.Timedelta(minutes=60)); hi = EV.searchsorted(xt)
        return (hi - lo) == 0
    raise ValueError(filt)


def apply(trades, filt):
    return trades[mask_keep(trades, filt)].reset_index(drop=True)


def null_p(oos: pd.DataFrame, filt_net: float, k_removed: int, span, draws=2000):
    net = C.add_pnl(oos)['net_pnl'].to_numpy()
    if k_removed == 0:
        return float('nan'), float('nan')
    tot = net.sum()
    sims = np.array([tot - net[RNG.choice(len(net), k_removed, replace=False)].sum() for _ in range(draws)])
    return float((sims >= filt_net).mean()), float(sims.mean())


def run_block(name, oos_all, span, lines, filters, trades_full=None):
    """oos_all = unfiltered trades in folds 2+3. trades_full = all folds (for WF selection)."""
    base = C.evaluate(oos_all, 3, start=span[0], end=span[1])
    lines += [f"## {name}", "",
              "| filter | n | removed | net | Δ vs none | PF | WR | maxDD | fold2 | fold3 | random-removal p | removed trades net |",
              "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    out = {}
    for f in filters:
        tr = apply(oos_all, f)
        r = C.evaluate(tr, 3, start=span[0], end=span[1])
        k = base['n'] - r['n']
        p, _ = null_p(oos_all, r['net'], k, span) if f != 'none' else (float('nan'), 0)
        removed_net = base['net'] - r['net']
        out[f] = dict(r, removed=k, p=p)
        lines.append(f"| {f} | {r['n']} | {k} | {r['net']:.0f} | {r['net']-base['net']:+.0f} | {r['pf']:.2f} | {r['wr']:.2f} | "
                     f"{r['max_dd']:.0f} | {r['folds'][1]:.0f} | {r['folds'][2]:.0f} | "
                     f"{'' if f=='none' else f'{p:.2f}'} | {'' if f=='none' else f'{removed_net:.0f}'} |")
        C.record_to_lab(STRAT, f"{name}__{f}", 'BASKET' if 'overnight' in name else 'HL_basket50', '1h',
                        dict(filter=f, calendar='econ_calendar_2024_2026.csv'), r, period=span,
                        source=__file__, baseline_net=base['net'],
                        notes=f"OOS folds 2+3 of the frozen fold-1 params; removed={k}; random-removal p={p}")
        print(f"{name:32s} {f:8s} n={r['n']:5d} net={r['net']:9.1f} d={r['net']-base['net']:+8.1f} "
              f"pf={r['pf']:.3f} folds={[round(x) for x in r['folds'][1:]]} p={p}")
    # walk-forward selection of the filter itself
    if trades_full is not None:
        def run_fn(p, s, e):
            t = trades_full[(pd.to_datetime(trades_full['entry_time'], utc=True) >= s) &
                            (pd.to_datetime(trades_full['entry_time'], utc=True) < e)]
            return apply(t, p['filter'])
        best, wf_oos, table = C.walk_forward([dict(filter=f) for f in filters], run_fn, span, n_folds=3, min_trades=10)
        wr = C.oos_result(wf_oos, span, 3)
        lines += ["", f"Walk-forward pick of the filter on fold 1: **{best['filter']}** "
                  f"(fold-1 nets: " + ", ".join(f"{json.loads(rw.params)['filter']} {rw.is_net:.0f}" for rw in table.itertuples())
                  + f") -> OOS net {wr['net']:.0f}, folds {[round(x) for x in wr['folds'][1:]]}.", ""]
        C.record_to_lab(STRAT, f"{name}__WF_pick_{best['filter']}", 'BASKET' if 'overnight' in name else 'HL_basket50', '1h',
                        best, wr, period=span, source=__file__, baseline_net=base['net'],
                        notes='filter chosen on fold 1 among ' + ','.join(filters))
        out['_wf'] = (best['filter'], wr)
    lines.append("")
    return out


def main():
    lines = ["# News blackout on the best edge-hunt candidates", "",
             "Calendar: `data/econ_calendar_2024_2026.csv` - FOMC (14:00 ET), CPI/NFP/PPI (08:30 ET), real release dates "
             "(BLS archive + federalreserve.gov), incl. the 2025 shutdown shifts. Retail sales / GDP not included.",
             "All numbers net of fees, walk-forward OOS (folds 2+3) with each strategy's own fold-1 parameters; "
             "`random-removal p` = share of 2,000 random removals of the same number of OOS trades that leave net >= the filtered net "
             "(small p = the news trades really were worse than average).", ""]

    # ---------------- A. overnight drift
    starts = [H.bars(i).index.min() for i in H.INSTS]; ends = [H.bars(i).index.max() for i in H.INSTS]
    span = (max(starts), min(ends)); bounds = C.fold_bounds(span, 3)
    oos_s, oos_e = bounds[1][0], bounds[2][1]
    run = H.run_fn_factory(H.INSTS)
    raw_full = run(V.BEST, span[0], span[1] + pd.Timedelta(hours=1))
    raw_oos = raw_full[(raw_full.entry_time >= oos_s) & (raw_full.entry_time < oos_e)].reset_index(drop=True)
    etf = V.etf_daily()
    legs = {i: V.overnight_legs_with_proxy(i, etf) for i in H.INSTS}
    cor_full = pd.concat([V.build_trades(i, legs[i], extra_ticks_per_side=1, roll_adjust=True) for i in H.INSTS],
                         ignore_index=True)
    cor_full['entry_time'] = pd.to_datetime(cor_full['entry_time'], utc=True)
    cor_oos = cor_full[(cor_full.entry_time >= oos_s) & (cor_full.entry_time < oos_e)].reset_index(drop=True)
    lines.append(f"Overnight span {span[0]:%Y-%m-%d} -> {span[1]:%Y-%m-%d}; OOS {oos_s:%Y-%m-%d} -> {oos_e:%Y-%m-%d}; "
                 f"events in OOS: {int(((EV >= oos_s) & (EV < oos_e)).sum())}.")
    lines.append("")
    ofilt = FILTERS + ['hold']
    resA = run_block('overnight_drift_raw', raw_oos, span, lines, ofilt, raw_full)
    resD = run_block('overnight_drift_corrected', cor_oos, span, lines, ofilt, cor_full)
    # per-event-type breakdown on the corrected legs: net of legs whose hold contains each type
    lines += ["### Corrected overnight legs by news type in the hold (entry-60m .. exit)", "",
              "| event in hold | legs | net | mean/leg | all-legs mean |", "|---|---:|---:|---:|---:|"]
    c = C.add_pnl(cor_oos)
    et = pd.to_datetime(c['entry_time'], utc=True); xt = pd.to_datetime(c['exit_time'], utc=True)
    for typ in ['FOMC', 'CPI', 'NFP', 'PPI']:
        evt = pd.DatetimeIndex(pd.to_datetime(CAL.loc[CAL.event == typ, 'dt_utc'], utc=True)).sort_values()
        hit = (evt.searchsorted(xt) - evt.searchsorted(et - pd.Timedelta(minutes=60))) > 0
        lines.append(f"| {typ} | {int(hit.sum())} | {c.net_pnl[hit].sum():.0f} | {c.net_pnl[hit].mean():.1f} | {c.net_pnl.mean():.1f} |")
    lines.append("")

    # ---------------- B. mean reversion z-score 1h
    coins = C.list_hl_coins()
    lo = min(M.bars(cn, '1h').index.min() for cn in coins); hi = max(M.bars(cn, '1h').index.max() for cn in coins)
    mspan = (lo, hi); mb = C.fold_bounds(mspan, 3)
    best = dict(K=2, thr=3.0, H=4, tgt=0.5, vol_filter=1.0)
    m_full = M.all_trades('1h', best, coins)
    m_oos = M.in_window(m_full, mb[1][0], mb[2][1])
    lines.append(f"Mean-reversion span {lo:%Y-%m-%d} -> {hi:%Y-%m-%d}; OOS {mb[1][0]:%Y-%m-%d} -> {mb[2][1]:%Y-%m-%d}.")
    lines.append("")
    resB = run_block('mean_reversion_zscore_1h', m_oos, mspan, lines, FILTERS, m_full)

    json.dump(dict(A={k: v for k, v in resA.items() if k != '_wf'}, D={k: v for k, v in resD.items() if k != '_wf'},
                   B={k: v for k, v in resB.items() if k != '_wf'}),
              open(OUT_MD.with_suffix('.json'), 'w'), default=str, indent=1)
    OUT_MD.with_suffix('.tables.md').write_text("\n".join(lines))
    print("\n".join(lines))


if __name__ == '__main__':
    main()
