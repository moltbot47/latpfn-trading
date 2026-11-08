"""Adversarial lenses for positive h_ema_vwap_scalper_htf variants.

leakage   : place every order ONE signal bar later (pattern must survive a delay; a
            same-bar leak collapses). Also re-check the no-lookahead assertion.
drift     : split net by side; compare with a pure-drift benchmark (same side, same
            session, same target/stop, entry at a random bar) = the random control.
execution : headline x2, +slip on stops, spread stress, and fold-by-fold under each.
statistics: fold consistency, cells tested, Bonferroni-style note.

  ../../../venv/bin/python h_ema_vwap_scalper_htf_lenses.py XAUUSD 15min_L2_E2_ce50_rr2to1 ...
"""
from __future__ import annotations

import sys

import numpy as np

import h_ema_vwap_scalper_htf as X

common, H = X.common, X.H


def parse(vn):
    a = vn.split("_")
    return (a[0], a[1], a[2], a[3], int(a[4].replace("rr", "").replace("to1", "")))


def main():
    sym = sys.argv[1]
    D = H.prep(sym)
    frames = {tf: X.prep_tf(D, sym, tf) for tf in X.TF_MIN}
    for vn in sys.argv[2:]:
        v = parse(vn)
        d = frames[v[0]]
        tr, ex = X.run(D, d, sym, *v)
        base = common.evaluate(X.price(tr, sym), 3, start=D["start"], end=D["end"])
        t = common.add_pnl(X.price(tr, sym))
        lg, sh = t[t.side > 0], t[t.side < 0]
        print(f"\n== {sym} {vn}: n={base['n']} net={base['net']:.0f} folds={[round(x) for x in base['folds']]}")
        print(f"  drift: long n={len(lg)} net={lg.net_pnl.sum():.0f} | short n={len(sh)} net={sh.net_pnl.sum():.0f}")
        # leakage lens: delay by one signal bar
        d2 = d.copy()
        d2["i1"] = np.r_[d["i1"].to_numpy()[1:], d["i1"].to_numpy()[-1]]
        d2["can_new"] = np.r_[d["can_new"].to_numpy()[1:], False]
        tr2, _ = X.run(D, d2, sym, *v)
        r2 = common.evaluate(X.price(tr2, sym), 3, start=D["start"], end=D["end"])
        print(f"  leakage (orders 1 signal bar late): n={r2['n']} net={r2['net']:.0f} folds={[round(x) for x in r2['folds']]}")
        for sc, x in X.scen_table(D, sym, tr, ex).items():
            print(f"  exec {sc:14s} net={x['net']:.0f} folds={[round(y) for y in x['folds']]}")


if __name__ == "__main__":
    main()
