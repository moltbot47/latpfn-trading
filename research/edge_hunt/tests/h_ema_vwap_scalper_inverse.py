"""h_ema_vwap_scalper_inverse — the literal inverse of h_ema_vwap_scalper.

Same triggers, same levels, same timing. Direction reversed, TP/SL distances
swapped, fade LIMITS become break-direction STOP orders at the same price.
Mapping is documented in h_ema_vwap_scalper_inverse.md.

Run:  ../../../venv/bin/python h_ema_vwap_scalper_inverse.py [--instr XAUUSD,NAS100] [--draws 300] [--no-lab]
"""
from __future__ import annotations

import argparse
import json

import numpy as np
import pandas as pd

import h_ema_vwap_scalper as H

common = H.common
STRAT = "ema_vwap_scalper_inverse"
CONTROL_SYMS = ("XAUUSD", "NAS100", "US30")


# ----------------------------------------------------------------------------
# geometry guard: every trade's stop and target must sit on the correct side
# ----------------------------------------------------------------------------
def check_geometry(side, entry, tp, sl, tag):
    side, entry, tp, sl = map(np.asarray, (side, entry, tp, sl))
    bad_tp = side * (tp - entry) <= 0
    bad_sl = side * (entry - sl) <= 0
    if bad_tp.any() or bad_sl.any():
        k = int(np.flatnonzero(bad_tp | bad_sl)[0])
        raise AssertionError(f"{tag}: stop/target on wrong side at row {k}: side={side[k]} "
                             f"entry={entry[k]} tp={tp[k]} sl={sl[k]}")


# ----------------------------------------------------------------------------
# stop-entry fills (the literal inverse of a fade limit at the same price)
# ----------------------------------------------------------------------------
def fill_stops(D, p_i, side, level):
    """Buy stop (side>0) triggers when a 1m high reaches the level; sell stop
    when a 1m low reaches it. Fill = the level, or the bar open if the bar
    gapped past it (worse price). Returns (fill index or -1, fill price)."""
    idx, raw = H._win(D, p_i, H.PEND)
    ok = raw <= D["flat_i"][np.clip(p_i, 0, len(D["hi"]) - 1)][:, None]
    trig = np.where(side[:, None] > 0, D["hi"][idx] >= level[:, None], D["lo"][idx] <= level[:, None]) & ok
    has = trig.any(1)
    col = trig.argmax(1)
    first = np.where(has, raw[np.arange(len(p_i)), col], -1)
    op = D["op"][idx[np.arange(len(p_i)), col]]
    if H.OPTIMISTIC:
        px = level.astype(float).copy()
    else:
        px = np.where(side > 0, np.maximum(level, op), np.minimum(level, op))
    return first, px


# ----------------------------------------------------------------------------
# L1 / L2 inverse
# ----------------------------------------------------------------------------
def l1_inv(D, agree, retr, gate=None):
    c = H.l1_candidates(D, agree, retr)
    if gate is not None:
        c = c[gate[c.k]].reset_index(drop=True)
    p = D["d5"].i1.to_numpy()[c.k]
    side = -c.side.to_numpy()                      # reversed direction
    atr = c.sd.to_numpy()                          # original sd = 1.0 ATR
    f, px = fill_stops(D, p, side, c.level.to_numpy())
    tp = px + side * 1.0 * atr                     # old stop distance -> target
    sl = px - side * 0.5 * atr                     # old target distance -> stop
    return p, f, side, px, tp, sl, 0.5 * atr, atr


def l2_inv(D, group, fib, gate=None):
    c = H.l2_candidates(D, group, fib)
    if gate is not None:
        c = c[gate[c.k]].reset_index(drop=True)
    p = D["d5"].i1.to_numpy()[c.k]
    n = len(c)
    atr = c.atr.to_numpy()
    lo_lv, hi_lv = c.buy.to_numpy(), c.sell.to_numpy()   # old buy-limit / sell-limit levels
    f_dn = np.full(n, -1); px_dn = np.full(n, np.nan)
    f_up = np.full(n, -1); px_up = np.full(n, np.nan)
    m = np.isfinite(lo_lv)
    if m.any():                                    # old buy limit below -> SELL STOP there
        f_dn[m], px_dn[m] = fill_stops(D, p[m], -np.ones(m.sum()), lo_lv[m])
    m = np.isfinite(hi_lv)
    if m.any():                                    # old sell limit above -> BUY STOP there
        f_up[m], px_up[m] = fill_stops(D, p[m], np.ones(m.sum()), hi_lv[m])
    BIG = 1 << 60
    a_, b_ = np.where(f_dn < 0, BIG, f_dn), np.where(f_up < 0, BIG, f_up)
    side = np.where(a_ < b_, -1, np.where(b_ < a_, 1, 0))  # same-minute double trigger -> skip
    side[(a_ == BIG) & (b_ == BIG)] = 0
    f = np.where(side == -1, f_dn, np.where(side == 1, f_up, -1))
    px = np.where(side == -1, px_dn, px_up)
    old_tp_dist = np.where(side == -1, c.tp_b.to_numpy() - lo_lv, hi_lv - c.tp_s.to_numpy())
    tp = px + side * 1.0 * atr                     # old stop distance (1 ATR) -> target
    sl = px - side * old_tp_dist                   # old fib-target distance -> stop
    return p, f, side, px, tp, sl, np.abs(old_tp_dist), atr


def run_simple_inv(D, v, gate=None, return_geom=False):
    fn = l1_inv if v[0] == "L1" else l2_inv
    p, f, side, px, tp, sl, sd, atr = fn(D, v[1], v[2], gate=gate)
    m = (f >= 0) & (side != 0)
    check_geometry(side[m], px[m], tp[m], sl[m], f"{v}")
    ex = np.full(len(f), -1)
    xp = np.full(len(f), np.nan)
    if H.OPTIMISTIC:
        # best case for stop entries: ignore the fill bar entirely (its adverse
        # extreme is assumed to precede the trigger); judge from the next bar
        fm = f[m]
        e2, x2 = H.resolve(D, fm + 1, side[m], px[m], tp[m], sl[m], market=True)
        ex[m], xp[m] = e2, x2
    else:
        ex[m], xp[m] = H.resolve(D, f[m], side[m], px[m], tp[m], sl[m])
    keep = H.sequential(p, np.where(m, f, -1), ex) & m
    tr = H.make_trades(D, f[keep], ex[keep], side[keep], px[keep], xp[keep], sd[keep])
    if return_geom:
        return tr, float(np.median(sd[keep] / atr[keep])) if keep.any() else 0.5
    return tr


# ----------------------------------------------------------------------------
# L3 inverse: breakout ladder of buy/sell STOPS at the old fade prices
# ----------------------------------------------------------------------------
def _chain_inv(D, p, side0, level, atr, n_add, wick_x, market=False):
    """side0 = the ORIGINAL chain side at this level; the inverse trades -side0.
    Old rungs (same prices) become stop orders adding WITH the break.
    Target = old chain stop price; stop = old moving target formula (avg -/+ 0.4 ATR)."""
    hi, lo, op, cl = D["hi"], D["lo"], D["op"], D["cl"]
    side = -side0
    flat = D["flat_i"][p]
    base = op[p] if market else level
    rungs = [base - side0 * 0.25 * atr * j for j in range(n_add + 1)]   # identical prices
    target = rungs[-1] - side0 * 1.0 * atr                              # = old stop price
    risk_each = H.RISK_USD / (n_add + 1)
    filled = []   # (idx, px, stop_at_fill)
    nxt = 0       # next rung to arm
    exp = min(p + H.PEND - 1, flat)
    last = min(p + H.HOLD, flat)
    trades = []
    i = p
    while i <= last:
        h, l = hi[i], lo[i]
        new_fill = False
        if market and i == p and nxt == 0:
            filled.append([i, op[p], None]); new_fill = True; nxt = 1
        while nxt < len(rungs) and i <= exp:
            r = rungs[nxt]
            if not ((side > 0 and h >= r) or (side < 0 and l <= r)):
                break
            fp = r if H.OPTIMISTIC else (max(r, op[i]) if side > 0 else min(r, op[i]))
            nxt += 1
            if side * (target - fp) <= 0:
                GAP_SKIPS[0] += 1      # gapped through the target: order treated as cancelled
                continue
            filled.append([i, fp, None]); new_fill = True
        if not filled:
            if i >= exp:
                return trades, exp, "nofill"
            i += 1
            continue
        avg = float(np.mean([x[1] for x in filled]))
        stop = avg - side * 0.4 * atr                                   # old target formula, mirrored
        for x in filled:
            if x[2] is None:
                x[2] = stop
        hit_sl = (side > 0 and l <= stop) or (side < 0 and h >= stop)
        if H.OPTIMISTIC and new_fill:
            hit_sl = False     # best case: the bar's adverse extreme came BEFORE the stop triggered
        hit_tp = (not (new_fill and not market and not H.OPTIMISTIC)) and \
                 ((side > 0 and h >= target) or (side < 0 and l <= target))
        exit_px, reason = None, None
        if H.OPTIMISTIC and hit_tp:
            exit_px, reason = target, "tp"
        elif hit_sl:
            exit_px, reason = stop, "sl"
        elif hit_tp:
            exit_px, reason = target, "tp"
        else:
            rng = h - l
            if rng >= 0.2 * atr and rng > 0:
                # exhaustion of the move IN OUR FAVOUR: upper wick for a long, lower for a short
                wick = (h - max(op[i], cl[i])) if side > 0 else (min(op[i], cl[i]) - l)
                in_profit = (side > 0 and cl[i] > avg) or (side < 0 and cl[i] < avg)
                if in_profit and wick / rng >= wick_x:
                    exit_px, reason = cl[i], "wick"
        if exit_px is None and i == last:
            exit_px, reason = cl[i], "time"
        if exit_px is not None:
            check_geometry([side] * len(filled), [x[1] for x in filled],
                           [target] * len(filled), [x[2] for x in filled], "L3 chain")
            for fi, fp, st in filled:
                trades.append((fi, i, side, fp, exit_px, abs(fp - st), risk_each))
            return trades, i, reason
        i += 1
    return trades, last, "none"


def _flip_leg_inv(D, i0, side, atr, wick_x):
    """Flip leg, geometry swapped vs the original (TP 1.0 ATR, SL 0.4 ATR)."""
    hi, lo, op, cl = D["hi"], D["lo"], D["op"], D["cl"]
    p = i0 + 1
    if p >= len(hi) or p > D["flat_i"][i0]:
        return None
    e = op[p]
    tp, sl = e + side * 1.0 * atr, e - side * 0.4 * atr
    check_geometry([side], [e], [tp], [sl], "L3 flip")
    last = min(p + H.HOLD, D["flat_i"][p])
    for i in range(p, last + 1):
        h, l = hi[i], lo[i]
        s_hit = (side > 0 and l <= sl) or (side < 0 and h >= sl)
        t_hit = (side > 0 and h >= tp) or (side < 0 and l <= tp)
        if H.OPTIMISTIC and t_hit:
            return (p, i, side, e, tp, abs(e - sl), H.RISK_USD)
        if s_hit:
            return (p, i, side, e, sl, abs(e - sl), H.RISK_USD)
        if t_hit:
            return (p, i, side, e, tp, abs(e - sl), H.RISK_USD)
        rng = h - l
        if rng >= 0.2 * atr and rng > 0:
            wick = (h - max(op[i], cl[i])) if side > 0 else (min(op[i], cl[i]) - l)
            if ((side > 0 and cl[i] > e) or (side < 0 and cl[i] < e)) and wick / rng >= wick_x:
                return (p, i, side, e, cl[i], abs(e - sl), H.RISK_USD)
    return (p, last, side, e, cl[last], abs(e - sl), H.RISK_USD)


LAST_L3 = []
GAP_SKIPS = [0]


def run_l3_inv(D, n_add, wick_x, gate=None, setups=None, market=False):
    s = H.l3_setups(D, gate) if setups is None else setups
    busy = -1
    rows, taken = [], []
    for p, side0, lv, a in zip(s.p.to_numpy(), s.side.to_numpy(), s.level.to_numpy(), s.atr.to_numpy()):
        if p <= busy or p >= len(D["hi"]):
            continue
        tr, end, reason = _chain_inv(D, int(p), int(side0), float(lv), float(a), n_add, wick_x, market)
        if tr and reason == "wick":
            fl = _flip_leg_inv(D, end, -int(tr[0][2]), float(a), wick_x)
            if fl is not None:
                tr = tr + [fl]
                end = fl[1]
        busy = end
        if tr:
            rows.extend(tr)
            taken.append((int(p), int(side0)))
    LAST_L3[:] = taken
    if not rows:
        e = np.array([], int)
        return H.make_trades(D, e, e, np.array([]), np.array([]), np.array([]), np.array([]))
    a = np.array(rows, dtype=float)
    return H.make_trades(D, a[:, 0].astype(int), a[:, 1].astype(int), a[:, 2], a[:, 3], a[:, 4], a[:, 5], risk=a[:, 6])


def run_variant(D, v, gate=None):
    if v[0] == "L3":
        return run_l3_inv(D, v[1], v[2], gate=gate)
    return run_simple_inv(D, v, gate=gate)


# ----------------------------------------------------------------------------
# random control with the NEW geometry
# ----------------------------------------------------------------------------
SL_RATIO = {}


def random_control(D, v, tr, draws, seed=0):
    rng = np.random.default_rng(seed)
    t1 = D["t1"]
    dd = D["d5"].reset_index(drop=True)
    elig = {s_: np.asarray(ix) for s_, ix in dd[dd.can_new].groupby("sday").indices.items()}
    if v[0] == "L3":
        run_l3_inv(D, v[1], v[2])
        ent_i = np.array([x[0] for x in LAST_L3])
        sides = np.array([x[1] for x in LAST_L3])       # original side0 (chain maps it)
    else:
        ent_i = np.searchsorted(t1.values, pd.to_datetime(tr.entry_time).values)
        sides = tr.side.to_numpy().astype(int)
    pos = np.clip(np.searchsorted(dd.i1.to_numpy(), ent_i, side="right") - 1, 0, len(dd) - 1)
    tr_sday = dd.sday.to_numpy()[pos]
    atr_all = dd.atr.to_numpy()
    nets = []
    for _ in range(draws):
        ks = np.array([rng.choice(elig[s_]) if s_ in elig else -1 for s_ in tr_sday])
        m = ks >= 0
        ks, sd_ = ks[m], sides[m]
        p = dd.i1.to_numpy()[ks]
        atr = atr_all[ks]
        e = D["op"][np.clip(p, 0, len(D["op"]) - 1)]
        if v[0] in ("L1", "L2"):
            slr = 0.5 if v[0] == "L1" else SL_RATIO[v]
            tp, sl = e + sd_ * 1.0 * atr, e - sd_ * slr * atr
            check_geometry(sd_, e, tp, sl, "control")
            ex, px = H.resolve(D, p, sd_, e, tp, sl, market=True)
            keep = H.sequential(p, p, ex)
            t = H.make_trades(D, p[keep], ex[keep], sd_[keep], e[keep], px[keep], (slr * atr)[keep])
        else:
            s = pd.DataFrame(dict(k=ks, side=sd_, level=e, atr=atr, p=p)).sort_values("p")
            t = run_l3_inv(D, v[1], v[2], setups=s, market=True)
        nets.append(common.evaluate(t, 3)["net"])
    return np.array(nets)


# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--draws", type=int, default=300)
    ap.add_argument("--no-lab", action="store_true")
    ap.add_argument("--instr", default="XAUUSD,NAS100")
    a = ap.parse_args()
    out = {"grid_size": len(H.grid()), "instruments": {}}
    for sym in a.instr.split(","):
        print(f"== {sym}: prep", flush=True)
        D = H.prep(sym)
        G = H.gates(D)
        res = {"variants": {}, "picks": {}}
        trades = {}
        for v in H.grid():
            if v[0] == "L2":
                tr, SL_RATIO[v] = run_simple_inv(D, v, return_geom=True)
            else:
                tr = run_variant(D, v)
            trades[v] = tr
            r = H.ev(D, tr)
            res["variants"][H.vname(v)] = r
            print(f"  {H.vname(v):28s} n={r['n']:5d} net={r['net']:10.0f} wr={r['wr']:.2f} "
                  f"aw={r['avg_win']:.0f} al={r['avg_loss']:.0f} folds={[round(x) for x in r['folds']]} "
                  f"gross/fees={r['be_cost_mult']:.2f}", flush=True)
        for L in ("L1", "L2", "L3"):
            vs = [v for v in H.grid() if v[0] == L]
            f1 = {v: res["variants"][H.vname(v)]["folds"][0] for v in vs}
            pick = max(vs, key=lambda v: f1[v])
            base = res["variants"][H.vname(pick)]
            # inverse "natural" regime: L1 inverse fades trend reclaims -> range; L2/L3 inverse trade breaks -> trend
            nat_key = "er_lo" if L == "L1" else "er_hi"
            nat = H.ev(D, run_variant(D, pick, gate=G[nat_key]))
            gres = {gk: H.ev(D, run_variant(D, pick, gate=gm)) for gk, gm in G.items()}
            f1n = {gk: (gr["folds"][0] if gr["fold_n"][0] >= 30 else -1e18) for gk, gr in gres.items()}
            best_g = max(f1n, key=f1n.get)
            H.COST_MULT = 2.0
            stress = H.ev(D, run_variant(D, pick))
            H.COST_MULT, H.OPTIMISTIC = 0.0, True
            best_case = H.ev(D, run_variant(D, pick))
            H.COST_MULT = 1.0
            opt_cost = H.ev(D, run_variant(D, pick))
            H.OPTIMISTIC = False
            info = dict(pick=H.vname(pick), pick_fold1=f1[pick], oos_f2f3=base["folds"][1] + base["folds"][2],
                        base=base, natural_gate=nat_key, natural=nat, best_gate=best_g,
                        best_gate_res=gres[best_g],
                        best_gate_oos_f2f3=gres[best_g]["folds"][1] + gres[best_g]["folds"][2],
                        all_gates={k: dict(net=g_["net"], folds=g_["folds"], n=g_["n"]) for k, g_ in gres.items()},
                        stress_2x=dict(net=stress["net"], folds=stress["folds"]),
                        best_case_zero_cost_touch_fills=dict(net=best_case["net"], folds=best_case["folds"],
                                                             wr=best_case["wr"], n=best_case["n"]),
                        optimistic_fills_full_cost=dict(net=opt_cost["net"], folds=opt_cost["folds"], wr=opt_cost["wr"],
                                                        n=opt_cost["n"], gross_over_fees=opt_cost["be_cost_mult"]))
            if sym in CONTROL_SYMS and a.draws > 0:
                print(f"  control {L} ({H.vname(pick)}) x{a.draws}", flush=True)
                nets = random_control(D, pick, trades[pick], a.draws)
                info["control"] = dict(mean=float(nets.mean()), p5=float(np.percentile(nets, 5)),
                                       p95=float(np.percentile(nets, 95)),
                                       rank_pct=float((nets < base["net"]).mean() * 100))
            t = common.add_pnl(trades[pick])
            if len(t):
                eq, peak, mdd = 10_000.0, 10_000.0, 0.0
                for rr in (t.net_pnl / H.RISK_USD).to_numpy():
                    eq += eq * 0.01 * rr
                    peak = max(peak, eq); mdd = max(mdd, 1 - eq / peak)
                info["scaling"] = dict(final_equity=eq, max_dd_pct=mdd * 100,
                                       fixed_final=10_000 + t.net_pnl.sum(), fixed_mdd=base["max_dd"])
            res["picks"][L] = info
            print(f"  {L} pick={H.vname(pick)} oos f2+f3={info['oos_f2f3']:.0f} nat({nat_key})={nat['net']:.0f}"
                  f"{[round(x) for x in nat['folds']]} bestgate={best_g} oos={info['best_gate_oos_f2f3']:.0f} "
                  f"stress2x={stress['net']:.0f} bestcase0cost={best_case['net']:.0f}"
                  f"{[round(x) for x in best_case['folds']]} optFullCost={opt_cost['net']:.0f}{[round(x) for x in opt_cost['folds']]} ctrl={info.get('control')} "
                  f"scal={ {k: round(v) for k, v in info.get('scaling', {}).items()} }", flush=True)
        if not a.no_lab:
            per = (D["start"], D["end"])
            src = "tests/h_ema_vwap_scalper_inverse.py"
            for v in H.grid():
                common.record_to_lab(STRAT, H.vname(v), sym, "5m/1m", dict(zip(("logic", "a", "b"), map(str, v))),
                                     res["variants"][H.vname(v)], period=per, source=src)
            for L, info in res["picks"].items():
                common.record_to_lab(STRAT, f"{info['pick']}__gate_{info['natural_gate']}", sym, "5m/1m",
                                     {"gate": info["natural_gate"]}, info["natural"], period=per, source=src,
                                     baseline_net=info["base"]["net"])
                common.record_to_lab(STRAT, f"{info['pick']}__gate_{info['best_gate']}_f1pick", sym, "5m/1m",
                                     {"gate": info["best_gate"]}, info["best_gate_res"], period=per, source=src,
                                     baseline_net=info["base"]["net"], notes="gate chosen on fold 1 only; judge folds 2-3")
        res["l3_gap_through_target_skips"] = GAP_SKIPS[0]
        print("  L3 rung fills skipped (gapped through target):", GAP_SKIPS[0], flush=True)
        GAP_SKIPS[0] = 0
        out["instruments"][sym] = res
    fn = H.HERE / f"h_ema_vwap_scalper_inverse_{a.instr.replace(',', '_')}.json"
    fn.write_text(json.dumps(out, indent=1, default=float))
    print("wrote", fn.name)


if __name__ == "__main__":
    main()
