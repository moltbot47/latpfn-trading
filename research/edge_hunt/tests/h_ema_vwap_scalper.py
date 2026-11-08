"""h_ema_vwap_scalper — EMA/VWAP pending-order scalper, 3 logics + regime gates.

Rules are pre-registered in h_ema_vwap_scalper.md. Data: range-rent 1m bars.
Run:  ../../../venv/bin/python h_ema_vwap_scalper.py [--draws 300] [--no-lab]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(Path.home() / "range-rent"))
import common  # noqa: E402
import rrdata  # noqa: E402

STRAT = "ema_vwap_scalper"
INSTR = ["US30", "XAUUSD", "GBPJPY"]
RISK_USD = 100.0
HOLD = 120            # max hold, minutes
PEND = 15             # pending lifetime, minutes
NO_NEW = 60           # no new orders in last N min of session
FLAT = 45             # flat N min before session end
ATR_N, ER_N = 14, 20
COST_MULT = 1.0       # set by stress run
OPTIMISTIC = False    # execution lens: touch fills, target-first, no fill-bar block

# ----------------------------------------------------------------------------
# data prep
# ----------------------------------------------------------------------------
def _resample(b1, rule):
    g = b1.resample(rule, label="left", closed="left")
    d = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(),
                      "low": g["low"].min(), "close": g["close"].last(),
                      "volume": g["volume"].sum()}).dropna(subset=["close"])
    d["close_time"] = d.index + pd.Timedelta(rule)
    return d


def _ema(x, n):
    return pd.Series(x).ewm(span=n, adjust=False).mean().to_numpy()


def _atr(d, n=ATR_N):
    pc = d["close"].shift(1)
    tr = np.maximum(d["high"] - d["low"], np.maximum((d["high"] - pc).abs(), (d["low"] - pc).abs()))
    return tr.ewm(alpha=1 / n, adjust=False).mean().to_numpy()


def _structure(d, k=2):
    """+1 HH+HL, -1 LH+LL, 0 otherwise; known at each bar's close (pivot
    confirmed k bars after it forms)."""
    h, l = d["high"].to_numpy(), d["low"].to_numpy()
    n = len(d)
    st = np.zeros(n, dtype=np.int8)
    sh, sl = [], []
    for i in range(2 * k, n):
        j = i - k  # candidate pivot, confirmed now at close of bar i
        if h[j] > h[j - k:j].max() and h[j] > h[j + 1:i + 1].max():
            sh.append(h[j]); sh = sh[-2:]
        if l[j] < l[j - k:j].min() and l[j] < l[j + 1:i + 1].min():
            sl.append(l[j]); sl = sl[-2:]
        if len(sh) == 2 and len(sl) == 2:
            if sh[1] > sh[0] and sl[1] > sl[0]:
                st[i] = 1
            elif sh[1] < sh[0] and sl[1] < sl[0]:
                st[i] = -1
    return st


def _asof(target_close, src_close, vals):
    """value of src at the last src bar whose close_time <= target close."""
    idx = np.searchsorted(src_close.to_numpy(), target_close.to_numpy(), side="right") - 1
    out = np.where(idx >= 0, vals[np.clip(idx, 0, None)], 0)
    return out


def prep(sym):
    b1 = rrdata.bars_1m(sym).copy()
    if b1.index.tz is None:
        b1.index = b1.index.tz_localize("UTC")
    t1 = b1.index
    m = pd.DataFrame(index=t1)
    m["hi"], m["lo"], m["op"], m["cl"] = b1.high.values, b1.low.values, b1.open.values, b1.close.values
    sday = b1["sday"].to_numpy()
    # per-minute session flat index / no-new cutoff
    last_t = b1.groupby("sday").apply(lambda g: g.index[-1])
    sess_end = pd.Series(sday).map(last_t).to_numpy()
    m["flat_t"] = pd.DatetimeIndex(sess_end) - pd.Timedelta(minutes=FLAT)
    m["sday"] = sday

    d5 = _resample(b1[["open", "high", "low", "close", "volume"]], "5min")
    d5["sday"] = (d5.index.tz_localize(None) + rrdata.SESSION_SHIFT).normalize()
    d5 = d5[d5["sday"].isin(set(pd.unique(sday)))]
    for n in (9, 14, 50, 200):
        d5[f"ema{n}"] = _ema(d5["close"], n)
    d5["atr"] = _atr(d5)
    tp = (d5.high + d5.low + d5.close) / 3
    v = d5["volume"].clip(lower=1e-9)
    d5["vwap"] = (tp * v).groupby(d5["sday"]).cumsum() / v.groupby(d5["sday"]).cumsum()
    ch = d5["close"].diff(ER_N).abs()
    vol = d5["close"].diff().abs().rolling(ER_N).sum()
    d5["er"] = (ch / vol).to_numpy()
    d5["volr"] = d5["atr"] / d5["close"]
    d5["hr"] = d5["close_time"].dt.hour
    d5["sess"] = np.select([(d5.hr >= 7) & (d5.hr < 13), (d5.hr >= 13) & (d5.hr < 21)], [1, 2], 0)
    d5["hh12"] = d5["high"].rolling(12).max()
    d5["ll12"] = d5["low"].rolling(12).min()
    d5["st5"] = _structure(d5)
    for rule, nm in (("15min", "st15"), ("1h", "st60")):
        dh = _resample(b1[["open", "high", "low", "close", "volume"]], rule)
        d5[nm] = _asof(d5["close_time"], dh["close_time"], _structure(dh))
    # prior-day / prior-week levels (session clock)
    ds = rrdata.sessions(sym)
    P = (ds.high + ds.low + ds.close) / 3
    lv = pd.DataFrame({"P": P, "R1": 2 * P - ds.low, "S1": 2 * P - ds.high,
                       "PDH": ds.high, "PDL": ds.low}).shift(1)
    wk = ds.index.to_period("W")
    wh, wl = ds.high.groupby(wk).max(), ds.low.groupby(wk).min()
    lv["PWH"] = pd.Series(wk, index=ds.index).map(wh.shift(1)).to_numpy()
    lv["PWL"] = pd.Series(wk, index=ds.index).map(wl.shift(1)).to_numpy()
    for c in lv.columns:
        d5[c] = d5["sday"].map(lv[c]).to_numpy()
    # first 1m index strictly after the 5m close
    d5["i1"] = np.searchsorted(t1.values, d5["close_time"].values, side="left")
    d5["flat_t"] = d5["sday"].map(pd.Series(last_t.values, index=last_t.index)).to_numpy()
    d5["flat_t"] = pd.to_datetime(d5["flat_t"]).dt.tz_localize("UTC") - pd.Timedelta(minutes=FLAT) \
        if pd.to_datetime(d5["flat_t"]).dt.tz is None else pd.to_datetime(d5["flat_t"]) - pd.Timedelta(minutes=FLAT)
    d5["can_new"] = d5["close_time"] <= d5["flat_t"] - pd.Timedelta(minutes=NO_NEW - FLAT)
    d5 = d5.iloc[250:]  # EMA200 warm-up
    d5 = d5[d5["i1"] < len(t1)]
    ft = pd.to_datetime(m["flat_t"])
    if ft.dt.tz is None:
        ft = ft.dt.tz_localize("UTC")
    flat_i = np.searchsorted(t1.values, ft.values, side="right") - 1
    return dict(sym=sym, t1=t1, hi=m.hi.to_numpy(), lo=m.lo.to_numpy(), op=m.op.to_numpy(),
                cl=m.cl.to_numpy(), flat_i=flat_i, d5=d5,
                cost=rrdata.COST[sym], ptv=rrdata.PT_VALUE[sym],
                start=t1[0], end=t1[-1])


# ----------------------------------------------------------------------------
# vectorised order mechanics
# ----------------------------------------------------------------------------
def _win(D, start_i, length):
    idx = start_i[:, None] + np.arange(length)[None, :]
    return np.clip(idx, 0, len(D["hi"]) - 1), idx


def fill_limits(D, p_i, side, level):
    """first 1m index in [p_i, p_i+PEND) where the bar trades THROUGH level,
    bounded by the session flat index; -1 if never."""
    idx, raw = _win(D, p_i, PEND)
    ok = raw <= D["flat_i"][np.clip(p_i, 0, len(D["hi"]) - 1)][:, None]
    if OPTIMISTIC:
        through = np.where(side[:, None] > 0, D["lo"][idx] <= level[:, None], D["hi"][idx] >= level[:, None]) & ok
    else:
        through = np.where(side[:, None] > 0, D["lo"][idx] < level[:, None], D["hi"][idx] > level[:, None]) & ok
    has = through.any(1)
    first = np.where(has, raw[np.arange(len(p_i)), through.argmax(1)], -1)
    return first


def resolve(D, f_i, side, entry, tp, sl, market=False):
    """exit index and price for positions filled at 1m index f_i."""
    n = len(f_i)
    if n == 0:
        return np.array([], int), np.array([])
    idx, raw = _win(D, f_i, HOLD + 1)
    last = np.minimum(f_i + HOLD, D["flat_i"][np.clip(f_i, 0, len(D["hi"]) - 1)])
    live = raw <= last[:, None]
    hi, lo = D["hi"][idx], D["lo"][idx]
    s = side[:, None] > 0
    sl_hit = np.where(s, lo <= sl[:, None], hi >= sl[:, None]) & live
    tp_hit = np.where(s, hi >= tp[:, None], lo <= tp[:, None]) & live
    if not market and not OPTIMISTIC:
        tp_hit[:, 0] = False  # limit fill bar: only the stop may trigger
    big = HOLD + 5
    fs = np.where(sl_hit.any(1), sl_hit.argmax(1), big)
    ftp = np.where(tp_hit.any(1), tp_hit.argmax(1), big)
    stop_first = (fs < ftp) if OPTIMISTIC else (fs <= ftp)
    ex_off = np.where(stop_first, fs, ftp)
    px = np.where(stop_first, sl, tp)
    none = ex_off >= big
    ex_i = np.where(none, last, f_i + ex_off)
    px = np.where(none, D["cl"][np.clip(last, 0, len(D["cl"]) - 1)], px)
    return ex_i, px


def make_trades(D, f_i, ex_i, side, entry, exit_px, stop_dist, risk=RISK_USD):
    if len(f_i) == 0:
        return pd.DataFrame(columns=common.REQUIRED_TRADE_COLS + ["multiplier"])
    qty = risk / (np.maximum(stop_dist, 1e-12) * D["ptv"])
    t1 = D["t1"]
    return pd.DataFrame(dict(
        entry_time=t1[f_i], exit_time=t1[ex_i], side=side.astype(float),
        entry_px=entry, exit_px=exit_px, qty=qty,
        notional_usd=entry * qty * D["ptv"],
        fee_usd=D["cost"] * COST_MULT * qty * D["ptv"],
        instrument=D["sym"], multiplier=D["ptv"]))


def sequential(sig_i1, fill_i, exit_i):
    """one position per logic: a candidate is taken only if its placement
    time is after the previous trade's exit (or pending expiry)."""
    keep = np.zeros(len(sig_i1), bool)
    busy = -1
    for k in np.argsort(sig_i1, kind="stable"):
        if sig_i1[k] <= busy:
            continue
        if fill_i[k] < 0:
            busy = sig_i1[k] + PEND - 1
            continue
        keep[k] = True
        busy = exit_i[k]
    return keep


# ----------------------------------------------------------------------------
# L1 trend pullback
# ----------------------------------------------------------------------------
def l1_candidates(D, agree, retr):
    d = D["d5"]
    c, e14 = d.close.to_numpy(), d.ema14.to_numpy()
    pc, pe = np.roll(c, 1), np.roll(e14, 1)
    up_st = (d.st15.to_numpy() == 1) & (d.st60.to_numpy() == 1)
    dn_st = (d.st15.to_numpy() == -1) & (d.st60.to_numpy() == -1)
    if agree == "all":
        up_st &= d.st5.to_numpy() == 1
        dn_st &= d.st5.to_numpy() == -1
    up = up_st & (pc <= pe) & (c > e14)
    dn = dn_st & (pc >= pe) & (c < e14)
    h, l, rng = d.high.to_numpy(), d.low.to_numpy(), (d.high - d.low).to_numpy()
    if retr == "ema9":
        lv_up = lv_dn = d.ema9.to_numpy()
    else:
        f = float(retr)
        lv_up, lv_dn = h - f * rng, l + f * rng
    ok = d.can_new.to_numpy()
    rows = []
    for mask, s, lv in ((up & ok & (lv_up < c), 1, lv_up), (dn & ok & (lv_dn > c), -1, lv_dn)):
        k = np.flatnonzero(mask)
        rows.append(pd.DataFrame(dict(k=k, side=s, level=lv[k])))
    cand = pd.concat(rows).sort_values("k").reset_index(drop=True)
    atr = d.atr.to_numpy()[cand.k]
    cand["tp"] = cand.level + cand.side * 0.5 * atr
    cand["sl"] = cand.level - cand.side * 1.0 * atr
    cand["sd"] = 1.0 * atr
    return cand


# ----------------------------------------------------------------------------
# L2 level reversal
# ----------------------------------------------------------------------------
GROUPS = {"G1_vwap": ["vwap"], "G2_pivots": ["P", "R1", "S1"],
          "G3_htf_sr": ["PDH", "PDL", "PWH", "PWL"], "G4_ema50_200": ["ema50", "ema200"]}


def l2_candidates(D, group, fib):
    d = D["d5"]
    c, atr = d.close.to_numpy(), d.atr.to_numpy()
    L = np.column_stack([d[x].to_numpy(dtype=float) for x in GROUPS[group]])
    dist = c[:, None] - L                       # >0: level below price
    lo_ok = (dist >= 0.1 * atr[:, None]) & (dist <= 1.5 * atr[:, None])
    hi_ok = (-dist >= 0.1 * atr[:, None]) & (-dist <= 1.5 * atr[:, None])
    buy_lv = np.where(lo_ok, L, -np.inf).max(1)
    sell_lv = np.where(hi_ok, L, np.inf).min(1)
    ok = d.can_new.to_numpy()
    hh, ll = d.hh12.to_numpy(), d.ll12.to_numpy()
    k = np.flatnonzero(ok & (np.isfinite(buy_lv) | np.isfinite(sell_lv)))
    out = pd.DataFrame(dict(k=k, buy=buy_lv[k], sell=sell_lv[k],
                            tp_b=buy_lv[k] + fib * (hh[k] - buy_lv[k]),
                            tp_s=sell_lv[k] - fib * (sell_lv[k] - ll[k]), atr=atr[k]))
    out.loc[~np.isfinite(out.buy) | (out.tp_b - out.buy < 0.25 * out.atr), "buy"] = np.nan
    out.loc[~np.isfinite(out.sell) | (out.sell - out.tp_s < 0.25 * out.atr), "sell"] = np.nan
    return out.dropna(subset=["buy", "sell"], how="all").reset_index(drop=True)


def l2_fill(D, cand):
    p = D["d5"].i1.to_numpy()[cand.k]
    n = len(cand)
    fb = np.full(n, -1); fs = np.full(n, -1)
    mb, ms = cand.buy.notna().to_numpy(), cand.sell.notna().to_numpy()
    if mb.any():
        fb[mb] = fill_limits(D, p[mb], np.ones(mb.sum()), cand.buy.to_numpy()[mb])
    if ms.any():
        fs[ms] = fill_limits(D, p[ms], -np.ones(ms.sum()), cand.sell.to_numpy()[ms])
    BIG = 1 << 60
    b_, s_ = np.where(fb < 0, BIG, fb), np.where(fs < 0, BIG, fs)
    side = np.where(b_ < s_, 1, np.where(s_ < b_, -1, 0))
    side[(b_ == BIG) & (s_ == BIG)] = 0
    f_i = np.where(side == 1, fb, np.where(side == -1, fs, -1))
    lvl = np.where(side == 1, cand.buy, cand.sell)
    tp = np.where(side == 1, cand.tp_b, cand.tp_s)
    sl = lvl - side * 1.0 * cand.atr.to_numpy()
    return p, f_i, side, lvl, tp, sl, cand.atr.to_numpy()


# ----------------------------------------------------------------------------
# generic run for L1/L2
# ----------------------------------------------------------------------------
def run_simple(D, cand_fn, gate=None):
    d = D["d5"]
    if cand_fn[0] == "L1":
        cand = l1_candidates(D, *cand_fn[1:])
        if gate is not None:
            cand = cand[gate[cand.k]].reset_index(drop=True)
        p = d.i1.to_numpy()[cand.k]
        f = fill_limits(D, p, cand.side.to_numpy(), cand.level.to_numpy())
        side, lvl, tp, sl, sd = cand.side.to_numpy(), cand.level.to_numpy(), cand.tp.to_numpy(), cand.sl.to_numpy(), cand.sd.to_numpy()
    else:
        cand = l2_candidates(D, *cand_fn[1:])
        if gate is not None:
            cand = cand[gate[cand.k]].reset_index(drop=True)
        p, f, side, lvl, tp, sl, atr = l2_fill(D, cand)
        sd = atr
    ex = np.full(len(f), -1)
    px = np.full(len(f), np.nan)
    m = f >= 0
    ex[m], px[m] = resolve(D, f[m], side[m], lvl[m], tp[m], sl[m])
    keep = sequential(p, f, ex) & m
    return make_trades(D, f[keep], ex[keep], side[keep], lvl[keep], px[keep], sd[keep])


# ----------------------------------------------------------------------------
# L3 chop both-ways scalp (per-chain loop)
# ----------------------------------------------------------------------------
def _chain(D, p, side, level, atr, n_add, wick_x, market=False):
    """simulate one ladder chain + optional flip. Returns list of trade dicts
    (one per unit) and end index."""
    hi, lo, op, cl = D["hi"], D["lo"], D["op"], D["cl"]
    flat = D["flat_i"][p]
    base = op[p] if market else level
    # adds sit further AGAINST the position (above for a short, below for a long)
    rungs = [base - side * 0.25 * atr * j for j in range(n_add + 1)]
    stop = rungs[-1] - side * 1.0 * atr
    risk_each = RISK_USD / (n_add + 1)
    filled = []  # (idx, px)
    exp = min(p + PEND - 1, flat)
    last = min(p + HOLD, flat)
    i = p
    trades = []
    while i <= last:
        h, l = hi[i], lo[i]
        if market and i == p and not filled:
            filled.append((i, rungs[0]))
        for r in rungs[len(filled):]:
            if i <= exp and ((side < 0 and h > r) or (side > 0 and l < r)):
                filled.append((i, r))
        if not filled:
            if i >= exp:
                return trades, exp, "nofill"
            i += 1
            continue
        avg = np.mean([x[1] for x in filled])
        tgt = avg + side * 0.4 * atr
        hit_sl = (side < 0 and h >= stop) or (side > 0 and l <= stop)
        on_fill_bar = any(fi == i for fi, _ in filled) and not market
        hit_tp = (not on_fill_bar) and ((side < 0 and l <= tgt) or (side > 0 and h >= tgt))
        exit_px = None
        if OPTIMISTIC and hit_tp:
            exit_px, hit_sl = tgt, False
        elif hit_sl:
            exit_px = stop
        elif hit_tp:
            exit_px = tgt
        else:
            rng = h - l
            if rng >= 0.2 * atr and rng > 0:
                wick = (min(op[i], cl[i]) - l) if side < 0 else (h - max(op[i], cl[i]))
                in_profit = (side < 0 and cl[i] < avg) or (side > 0 and cl[i] > avg)
                if in_profit and wick / rng >= wick_x:
                    exit_px, reason = cl[i], "wick"
        if exit_px is None and i == last:
            exit_px, reason = cl[i], "time"
        if exit_px is not None:
            if hit_sl:
                reason = "sl"
            elif hit_tp:
                reason = "tp"
            for fi, fp in filled:
                trades.append((fi, i, side, fp, exit_px, abs(stop - fp), risk_each))
            return trades, i, reason
        i += 1
    return trades, last, "none"


def _flip_leg(D, i0, side, atr, wick_x):
    """single-unit market leg opened at next 1m open, no further flips."""
    hi, lo, op, cl = D["hi"], D["lo"], D["op"], D["cl"]
    p = i0 + 1
    if p >= len(hi) or p > D["flat_i"][i0]:
        return None
    e = op[p]
    tp, sl = e + side * 0.4 * atr, e - side * 1.0 * atr
    last = min(p + HOLD, D["flat_i"][p])
    for i in range(p, last + 1):
        h, l = hi[i], lo[i]
        if (side > 0 and l <= sl) or (side < 0 and h >= sl):
            return (p, i, side, e, sl, abs(e - sl), RISK_USD)
        if (side > 0 and h >= tp) or (side < 0 and l <= tp):
            return (p, i, side, e, tp, abs(e - sl), RISK_USD)
        rng = h - l
        if rng >= 0.2 * atr and rng > 0:
            wick = (h - max(op[i], cl[i])) if side > 0 else (min(op[i], cl[i]) - l)
            if ((side > 0 and cl[i] > e) or (side < 0 and cl[i] < e)) and wick / rng >= wick_x:
                return (p, i, side, e, cl[i], abs(e - sl), RISK_USD)
    return (p, last, side, e, cl[last], abs(e - sl), RISK_USD)


def _run_chain_full(D, p, side, level, atr, n_add, wick_x, market=False):
    tr, end, reason = _chain(D, p, side, level, atr, n_add, wick_x, market)
    out = list(tr)
    if tr:
        if reason == "wick":
            f = _flip_leg(D, end, -side, atr, wick_x)
            if f is not None:
                out.append(f)
                end = f[1]
    return out, end


def l3_setups(D, gate=None):
    d = D["d5"]
    c, atr, hh, ll = d.close.to_numpy(), d.atr.to_numpy(), d.hh12.to_numpy(), d.ll12.to_numpy()
    ok = d.can_new.to_numpy() & np.isfinite(hh)
    near_hi = ok & (hh - c <= 0.5 * atr) & (hh - c > 0)
    near_lo = ok & (c - ll <= 0.5 * atr) & (c - ll > 0)
    if gate is not None:
        near_hi &= gate; near_lo &= gate
    rows = [pd.DataFrame(dict(k=np.flatnonzero(near_hi), side=-1)),
            pd.DataFrame(dict(k=np.flatnonzero(near_lo), side=1))]
    s = pd.concat(rows).sort_values(["k", "side"]).drop_duplicates("k").reset_index(drop=True)
    s["level"] = np.where(s.side < 0, hh[s.k], ll[s.k])
    s["atr"] = atr[s.k]
    s["p"] = d.i1.to_numpy()[s.k]
    return s


def run_l3(D, n_add, wick_x, gate=None, setups=None, market=False):
    s = l3_setups(D, gate) if setups is None else setups
    busy = -1
    rows, taken = [], []
    for p, side, lv, a in zip(s.p.to_numpy(), s.side.to_numpy(), s.level.to_numpy(), s.atr.to_numpy()):
        if p <= busy or p >= len(D["hi"]):
            continue
        tr, end = _run_chain_full(D, int(p), int(side), float(lv), float(a), n_add, wick_x, market)
        busy = end
        rows.extend(tr)
        if tr:
            taken.append((int(p), int(side)))
    LAST_L3[:] = taken
    if not rows:
        return make_trades(D, np.array([], int), np.array([], int), np.array([]), np.array([]), np.array([]), np.array([]))
    a = np.array(rows, dtype=float)
    return make_trades(D, a[:, 0].astype(int), a[:, 1].astype(int), a[:, 2], a[:, 3], a[:, 4], a[:, 5], risk=a[:, 6])


# ----------------------------------------------------------------------------
# event study: 1h-open push against prior hour
# ----------------------------------------------------------------------------
def hour_open_study(D):
    t1 = D["t1"]
    df = pd.DataFrame({"op": D["op"], "cl": D["cl"]}, index=t1)
    h = df.resample("1h").agg({"op": "first", "cl": "last"}).dropna()
    prev_dir = np.sign(h.cl - h.op).shift(1)
    # close of the 15th minute of each hour
    pos0 = np.searchsorted(t1.values, h.index.values)
    pos15 = np.searchsorted(t1.values, (h.index + pd.Timedelta(minutes=15)).values) - 1
    ok = (pos15 > pos0) & (pos15 < len(t1))
    r = pd.Series(np.nan, index=h.index)
    r[ok] = D["cl"][pos15[ok]] - D["op"][pos0[ok]]
    opp = (-prev_dir * r).dropna()
    opp = opp[prev_dir.loc[opp.index] != 0]
    hr = opp.index.hour
    sess = np.select([(hr >= 7) & (hr < 13), (hr >= 13) & (hr < 21)], ["London", "NY"], "Asia")
    out = {}
    for name, x in [("all", opp)] + [(s_, opp[sess == s_]) for s_ in ("Asia", "London", "NY")]:
        out[name] = dict(n=int(len(x)), mean_pts=float(x.mean()), frac_opposite=float((x > 0).mean()),
                         t=float(x.mean() / x.std(ddof=1) * np.sqrt(len(x))) if len(x) > 2 else 0.0,
                         cost_pts=D["cost"], mean_abs_move=float(x.abs().mean()))
    return out


# ----------------------------------------------------------------------------
# regime gates
# ----------------------------------------------------------------------------
def fold1_mask(D):
    d = D["d5"]
    lo, hi = D["start"], D["end"]
    b = lo + (hi - lo) / 3
    return (d.close_time < b).to_numpy()


def gates(D):
    d = D["d5"]
    f1 = fold1_mask(D)
    er, vr = d.er.to_numpy(), d.volr.to_numpy()
    e33, e67 = np.nanpercentile(er[f1], [33.3, 66.7])
    v33, v67 = np.nanpercentile(vr[f1], [33.3, 66.7])
    g = {"er_lo": er <= e33, "er_mid": (er > e33) & (er < e67), "er_hi": er >= e67,
         "vol_lo": vr <= v33, "vol_mid": (vr > v33) & (vr < v67), "vol_hi": vr >= v67,
         "asia": d.sess.to_numpy() == 0, "london": d.sess.to_numpy() == 1, "ny": d.sess.to_numpy() == 2}
    return g


# ----------------------------------------------------------------------------
def ev(D, tr):
    r = common.evaluate(tr, 3, start=D["start"], end=D["end"])
    if r["n"]:
        r["be_cost_mult"] = float(r["gross"] / r["fees"]) if r["fees"] > 0 else float("nan")
    else:
        r["be_cost_mult"] = float("nan")
    return r


def grid():
    g = []
    for a in ("all", "15m1h"):
        for rt in ("0.25", "0.5", "ema9"):
            g.append(("L1", a, rt))
    for grp in GROUPS:
        for fb in (0.382, 0.5, 0.618):
            g.append(("L2", grp, fb))
    for na in (0, 2):
        for wx in (0.5, 0.7):
            g.append(("L3", na, wx))
    return g


def run_variant(D, v, gate=None):
    if v[0] == "L3":
        return run_l3(D, v[1], v[2], gate=gate)
    return run_simple(D, v, gate=gate)


def vname(v):
    return "_".join(str(x) for x in v)


def random_control(D, v, tr, draws, seed=0):
    """keep each trade's side + session day, random market entry minute in
    that session; replay identical TP/SL/hold/sizing."""
    rng = np.random.default_rng(seed)
    t1 = D["t1"]
    d = D["d5"]
    # eligible signal bars per session (can_new)
    dd = d.reset_index(drop=True)
    elig = {s_: np.asarray(ix) for s_, ix in dd[dd.can_new].groupby("sday").indices.items()}
    # map trades to their session day & side (for L3 use chain first units only approx: all units)
    if v[0] == "L3":
        run_l3(D, v[1], v[2])           # refresh LAST_L3 = chains actually taken
        ent_i = np.array([x[0] for x in LAST_L3])
        sides = np.array([x[1] for x in LAST_L3])
    else:
        ent_i = np.searchsorted(t1.values, pd.to_datetime(tr.entry_time).values)
        sides = tr.side.to_numpy().astype(int)
    tr_sday = pd.Series(D["d5"].sday.to_numpy())[np.clip(np.searchsorted(dd.i1.to_numpy(), ent_i, side="right") - 1, 0, len(dd) - 1)].to_numpy()
    nets = []
    atr_all = dd.atr.to_numpy()
    for _ in range(draws):
        ks = np.array([rng.choice(elig[s_]) if s_ in elig else -1 for s_ in tr_sday])
        m = ks >= 0
        ks, sd_ = ks[m], sides[m]
        p = dd.i1.to_numpy()[ks]
        atr = atr_all[ks]
        e = D["op"][np.clip(p, 0, len(D["op"]) - 1)]
        if v[0] == "L1":
            tp, sl, dist = e + sd_ * 0.5 * atr, e - sd_ * 1.0 * atr, 1.0 * atr
        elif v[0] == "L2":
            # same TP distance distribution as the strategy: use its realised tp/sl geometry
            tp, sl, dist = e + sd_ * RATIO_TP[v] * atr, e - sd_ * 1.0 * atr, 1.0 * atr
        if v[0] in ("L1", "L2"):
            ex, px = resolve(D, p, sd_, e, tp, sl, market=True)
            keep = sequential(p, p, ex)
            t = make_trades(D, p[keep], ex[keep], sd_[keep], e[keep], px[keep], dist[keep])
        else:
            s = pd.DataFrame(dict(k=ks, side=sd_, level=e, atr=atr, p=p)).sort_values("p")
            t = run_l3(D, v[1], v[2], setups=s, market=True)
        nets.append(common.evaluate(t, 3)["net"])
    return np.array(nets)


RATIO_TP = {}
LAST_L3 = []


def main():
    global COST_MULT
    ap = argparse.ArgumentParser()
    ap.add_argument("--draws", type=int, default=300)
    ap.add_argument("--no-lab", action="store_true")
    ap.add_argument("--instr", default=",".join(INSTR))
    a = ap.parse_args()
    out = {"grid_size": len(grid()), "instruments": {}}
    for sym in a.instr.split(","):
        print(f"== {sym}: prep", flush=True)
        D = prep(sym)
        G = gates(D)
        res = {"hour_open_study": hour_open_study(D), "variants": {}, "picks": {}}
        print(" hour-open:", json.dumps(res["hour_open_study"]["all"]), flush=True)
        trades = {}
        for v in grid():
            tr = run_variant(D, v)
            trades[v] = tr
            r = ev(D, tr)
            res["variants"][vname(v)] = r
            print(f"  {vname(v):28s} n={r['n']:5d} net={r['net']:10.0f} wr={r['wr']:.2f} "
                  f"aw={r['avg_win']:.0f} al={r['avg_loss']:.0f} folds={[round(x) for x in r['folds']]} be={r['be_cost_mult']:.2f}", flush=True)
            if v[0] == "L2" and r["n"]:
                t = common.add_pnl(tr)
                w = t.gross_pnl > 0
                RATIO_TP[v] = float(np.median((t.exit_px - t.entry_px).abs()[w] * t.qty[w] * D["ptv"] / RISK_USD)) if w.any() else 0.5
        # per-logic: fold-1 pick, natural gate, best gate, stress, control
        for L in ("L1", "L2", "L3"):
            vs = [v for v in grid() if v[0] == L]
            f1 = {v: res["variants"][vname(v)]["folds"][0] for v in vs}
            pick = max(vs, key=lambda v: f1[v])
            base = res["variants"][vname(pick)]
            nat_key = "er_hi" if L == "L1" else "er_lo"
            nat = ev(D, run_variant(D, pick, gate=G[nat_key]))
            # best single gate on fold 1
            gres = {}
            for gk, gm in G.items():
                gr = ev(D, run_variant(D, pick, gate=gm))
                gres[gk] = gr
            f1n = {gk: (gr["folds"][0] if gr["fold_n"][0] >= 30 else -1e18) for gk, gr in gres.items()}
            best_g = max(f1n, key=f1n.get)
            COST_MULT = 2.0
            stress = ev(D, run_variant(D, pick))
            COST_MULT, OPT_SAVE = 0.0, None
            globals()["OPTIMISTIC"] = True
            best_case = ev(D, run_variant(D, pick))
            globals()["OPTIMISTIC"] = False
            COST_MULT = 1.0
            info = dict(pick=vname(pick), pick_fold1=f1[pick], oos_f2f3=base["folds"][1] + base["folds"][2],
                        base=base, natural_gate=nat_key, natural=nat, best_gate=best_g,
                        best_gate_res=gres[best_g], best_gate_oos_f2f3=gres[best_g]["folds"][1] + gres[best_g]["folds"][2],
                        all_gates={k: dict(net=g_["net"], folds=g_["folds"], n=g_["n"]) for k, g_ in gres.items()},
                        stress_2x=dict(net=stress["net"], folds=stress["folds"]),
                        best_case_zero_cost_touch_fills=dict(net=best_case["net"], folds=best_case["folds"], wr=best_case["wr"], n=best_case["n"]))
            if sym in ("US30", "XAUUSD", "NAS100") and a.draws > 0:
                print(f"  control {L} ({vname(pick)}) x{a.draws}", flush=True)
                nets = random_control(D, pick, trades[pick], a.draws)
                info["control"] = dict(mean=float(nets.mean()), p5=float(np.percentile(nets, 5)),
                                       p95=float(np.percentile(nets, 95)),
                                       rank_pct=float((nets < base["net"]).mean() * 100))
            # proportional scaling view (1% of equity per trade from $10k)
            t = common.add_pnl(trades[pick])
            if len(t):
                eq, peak, mdd = 10_000.0, 10_000.0, 0.0
                for rr in (t.net_pnl / RISK_USD).to_numpy():
                    eq += eq * 0.01 * rr
                    peak = max(peak, eq); mdd = max(mdd, 1 - eq / peak)
                info["scaling"] = dict(final_equity=eq, max_dd_pct=mdd * 100,
                                       fixed_final=10_000 + t.net_pnl.sum(), fixed_mdd=base["max_dd"])
            res["picks"][L] = info
            print(f"  {L} pick={vname(pick)} oos f2+f3={info['oos_f2f3']:.0f} nat={nat['net']:.0f}{[round(x) for x in nat['folds']]} "
                  f"bestgate={best_g} oos={info['best_gate_oos_f2f3']:.0f} stress={stress['net']:.0f} bestcase0cost={best_case['net']:.0f}{[round(x) for x in best_case['folds']]} ctrl={info.get('control')}", flush=True)
        if not a.no_lab:
            per = (D["start"], D["end"])
            for v in grid():
                common.record_to_lab(STRAT, vname(v), sym, "5m/1m", dict(zip(("logic", "a", "b"), map(str, v))),
                                     res["variants"][vname(v)], period=per, source="tests/h_ema_vwap_scalper.py")
            for L, info in res["picks"].items():
                common.record_to_lab(STRAT, f"{info['pick']}__gate_{info['natural_gate']}", sym, "5m/1m",
                                     {"gate": info["natural_gate"]}, info["natural"], period=per,
                                     source="tests/h_ema_vwap_scalper.py", baseline_net=info["base"]["net"])
                common.record_to_lab(STRAT, f"{info['pick']}__gate_{info['best_gate']}_f1pick", sym, "5m/1m",
                                     {"gate": info["best_gate"]}, info["best_gate_res"], period=per,
                                     source="tests/h_ema_vwap_scalper.py", baseline_net=info["base"]["net"],
                                     notes="gate chosen on fold 1 only; judge folds 2-3")
        out["instruments"][sym] = res
    (HERE / f"h_ema_vwap_scalper_{a.instr.replace(',', '_')}.json").write_text(json.dumps(out, indent=1, default=float))
    print("wrote json")


if __name__ == "__main__":
    main()
