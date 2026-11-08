"""h_ema_vwap_scalper_htf — 3 logics on 15m/1h signals, E1/E2(FVG)/E3(OB) entries,
R:R 1:1 / 2:1 / 3:1 (stop = rr x fixed target), fixed 1.0 lot, 3 cost scenarios.
Rules pre-registered in h_ema_vwap_scalper_htf.md.

  ../../../venv/bin/python h_ema_vwap_scalper_htf.py --part a
  ../../../venv/bin/python h_ema_vwap_scalper_htf.py --instr XAUUSD,NAS100 [--draws 300] [--no-lab]
"""
from __future__ import annotations

import argparse
import json

import numpy as np
import pandas as pd

import h_ema_vwap_scalper as H
import h_ema_vwap_scalper_inverse as I

common, rrdata = H.common, H.rrdata
STRAT = "ema_vwap_scalper_htf"

# USD per 1.0 price move for 1.0 lot (Genesis FX / TradeLocker; NAS100 + XAUUSD confirmed from live P&L)
LOT_VALUE = {"NAS100": 10.0, "XAUUSD": 100.0, "GBPJPY": 670.0, "US30": 10.0}
LOT_NOTE = {"GBPJPY": "fixed $6.70/pip (no USDJPY series locally)", "US30": "ASSUMED $10/pt (not user-given)"}
TF_MIN = {"15min": 15, "1h": 60}
HIGHER = {"15min": "1h", "1h": "4h"}
HOLD_BARS = 24
K_E1, K_ZONE = 3, 6
TPFIRST = False     # execution lens only
CONTROL_SYMS = ("XAUUSD", "NAS100", "US30")


# ----------------------------------------------------------------------------
# 1.0-lot pricing under cost scenarios (USD per round trip per 1.0 lot)
#   a        = commission only (user's Genesis screenshot: NAS100 $6, XAUUSD $10)
#   b        = commission + spread = HEADLINE. NAS100 spread 1.15 pts (live quote);
#              gold $0.20 (raw-spread assumption: the TL gold 1m file has no bid/ask)
#   b_prop   = NAS100 commission + 0.38 bp of price (live spread scaled to the 2024 ~18k level)
#   b_sprd35 = XAUUSD commission + $0.35 spread stress
#   c        = old model (rrdata.COST points x lot value)
# US30 / GBPJPY have no broker quote -> headline = c.
# Slippage stress: +1 pt NAS100/US30, +$0.10 gold, +0.01 GBPJPY on STOP-LOSS exits only.
# ----------------------------------------------------------------------------
def scenario_fees(sym, entry_px):
    lv = LOT_VALUE[sym]
    one = np.ones(len(entry_px))
    c = rrdata.COST[sym] * lv * one
    if sym == "NAS100":
        return {"a": 6.0 * one, "b": (6.0 + 1.15 * lv) * one, "b_prop": 6.0 + 0.38e-4 * entry_px * lv, "c": c}
    if sym == "XAUUSD":
        return {"a": 10.0 * one, "b": (10.0 + 0.20 * lv) * one, "b_sprd35": (10.0 + 0.35 * lv) * one, "c": c}
    return {"c": c}


HEADLINE = {"NAS100": "b", "XAUUSD": "b", "US30": "c", "GBPJPY": "c"}
SLIP_PTS = {"NAS100": 1.0, "XAUUSD": 0.10, "US30": 1.0, "GBPJPY": 0.01}


def price(tr, sym, scen=None, mult=1.0, is_sl=None, slip=False):
    t = tr.copy()
    if len(t) == 0:
        return t
    lv = LOT_VALUE[sym]
    scen = scen or HEADLINE[sym]
    t["qty"] = 1.0
    t["multiplier"] = lv
    t["notional_usd"] = t["entry_px"].astype(float) * lv
    fee = scenario_fees(sym, t["entry_px"].to_numpy(float))[scen] * mult
    if slip and is_sl is not None:
        fee = fee + np.where(is_sl, SLIP_PTS[sym] * lv, 0.0)
    t["fee_usd"] = fee
    return t


# ----------------------------------------------------------------------------
# signal-TF frame
# ----------------------------------------------------------------------------
def structure_vals(d, k=2):
    """HH+HL status plus last confirmed swing high / low VALUES, all known at
    each bar's close."""
    h, l = d["high"].to_numpy(), d["low"].to_numpy()
    n = len(d)
    st = np.zeros(n, np.int8)
    lsh = np.full(n, np.nan); lsl = np.full(n, np.nan)
    sh, sl = [], []
    for i in range(2 * k, n):
        j = i - k
        if h[j] > h[j - k:j].max() and h[j] > h[j + 1:i + 1].max():
            sh.append(h[j]); sh = sh[-2:]
        if l[j] < l[j - k:j].min() and l[j] < l[j + 1:i + 1].min():
            sl.append(l[j]); sl = sl[-2:]
        if sh:
            lsh[i] = sh[-1]
        if sl:
            lsl[i] = sl[-1]
        if len(sh) == 2 and len(sl) == 2:
            st[i] = 1 if (sh[1] > sh[0] and sl[1] > sl[0]) else (-1 if (sh[1] < sh[0] and sl[1] < sl[0]) else 0)
    return st, lsh, lsl


def prep_tf(D, sym, rule):
    b1 = rrdata.bars_1m(sym).copy()
    if b1.index.tz is None:
        b1.index = b1.index.tz_localize("UTC")
    ohlcv = b1[["open", "high", "low", "close", "volume"]]
    d = H._resample(ohlcv, rule)
    d["sday"] = (d.index.tz_localize(None) + rrdata.SESSION_SHIFT).normalize()
    d = d[d["sday"].isin(set(pd.unique(b1["sday"])))]
    for n in (9, 14, 50, 200):
        d[f"ema{n}"] = H._ema(d["close"], n)
    d["atr"] = H._atr(d)
    tp = (d.high + d.low + d.close) / 3
    v = d["volume"].clip(lower=1e-9)
    d["vwap"] = (tp * v).groupby(d["sday"]).cumsum() / v.groupby(d["sday"]).cumsum()
    d["er"] = (d["close"].diff(H.ER_N).abs() / d["close"].diff().abs().rolling(H.ER_N).sum()).to_numpy()
    d["volr"] = d["atr"] / d["close"]
    hr = d["close_time"].dt.hour
    d["sess"] = np.select([(hr >= 7) & (hr < 13), (hr >= 13) & (hr < 21)], [1, 2], 0)
    d["hh12"] = d["high"].rolling(12).max()
    d["ll12"] = d["low"].rolling(12).min()
    st, lsh, lsl = structure_vals(d)
    d["st"], d["lsh"], d["lsl"] = st, lsh, lsl
    dh = H._resample(ohlcv, HIGHER[rule])
    sth, _, _ = structure_vals(dh)
    d["st_hi"] = H._asof(d["close_time"], dh["close_time"], sth)
    # levels from the 5m frame's per-sday mapping
    d5 = D["d5"]
    lv = d5.groupby("sday")[["P", "R1", "S1", "PDH", "PDL", "PWH", "PWL"]].first()
    for c in lv.columns:
        d[c] = d["sday"].map(lv[c]).to_numpy()
    t1 = D["t1"]
    d["i1"] = np.searchsorted(t1.values, d["close_time"].values, side="left")
    last_t = b1.groupby("sday").apply(lambda g: g.index[-1])
    ft = pd.to_datetime(d["sday"].map(last_t))
    d["flat_t"] = ft - pd.Timedelta(minutes=H.FLAT)
    d["can_new"] = d["close_time"] <= d["flat_t"] - pd.Timedelta(minutes=H.NO_NEW - H.FLAT)
    d = d.iloc[220:]
    d = d[(d["i1"] < len(t1)) & d["atr"].gt(0)].reset_index()
    d = d.rename(columns={"time": "open_time"})
    return d


# ----------------------------------------------------------------------------
# guards
# ----------------------------------------------------------------------------
def check_geometry(side, entry, tp, sl, tag):
    I.check_geometry(side, entry, tp, sl, tag)


def check_no_lookahead(d, cand, D, tag):
    """every pattern-based order is placed at a 1m time >= close of the bar
    that completes the pattern, and the pattern bars precede that bar."""
    if len(cand) == 0:
        return
    place_t = D["t1"][d.i1.to_numpy()[cand.k]]
    known_t = d.close_time.values[cand.known_k.to_numpy()]
    assert (cand.known_k.to_numpy() <= cand.k.to_numpy()).all(), f"{tag}: known bar after placement bar"
    assert (place_t.values >= known_t).all(), f"{tag}: order placed before the pattern was complete"
    assert (cand.first_k.to_numpy() <= cand.known_k.to_numpy()).all(), f"{tag}: pattern uses later bars"


# ----------------------------------------------------------------------------
# pattern detection (vectorised, all known at bar k close)
# ----------------------------------------------------------------------------
def fvgs(d):
    h, l = d.high.to_numpy(), d.low.to_numpy()
    n = len(d)
    k = np.arange(2, n)
    bull = l[k] > h[k - 2]
    bear = h[k] < l[k - 2]
    out = []
    kb = k[bull]
    out.append(pd.DataFrame(dict(k=kb, side=1, near=l[kb], far=h[kb - 2], stop=l[kb - 2], first_k=kb - 2, known_k=kb)))
    ks = k[bear]
    out.append(pd.DataFrame(dict(k=ks, side=-1, near=h[ks], far=l[ks - 2], stop=h[ks - 2], first_k=ks - 2, known_k=ks)))
    return pd.concat(out).sort_values("k").reset_index(drop=True)


def obs(d):
    o, h, l, c, atr = (d[x].to_numpy() for x in ("open", "high", "low", "close", "atr"))
    lsh_prev, lsl_prev = np.roll(d.lsh.to_numpy(), 1), np.roll(d.lsl.to_numpy(), 1)
    body = np.abs(c - o)
    rows = []
    for kk in np.flatnonzero((c > lsh_prev) & (c > o) & (body >= atr) & np.isfinite(lsh_prev)):
        if kk < 6:
            continue
        for j in range(kk - 1, kk - 6, -1):
            if c[j] < o[j]:
                rows.append((kk, 1, o[j], h[j], l[j], j)); break
    for kk in np.flatnonzero((c < lsl_prev) & (c < o) & (body >= atr) & np.isfinite(lsl_prev)):
        if kk < 6:
            continue
        for j in range(kk - 1, kk - 6, -1):
            if c[j] > o[j]:
                rows.append((kk, -1, o[j], h[j], l[j], j)); break
    df = pd.DataFrame(rows, columns=["k", "side", "ob_open", "ob_high", "ob_low", "first_k"])
    df["known_k"] = df["k"]
    return df.sort_values("k").reset_index(drop=True)


LEVELS = ["vwap", "P", "R1", "S1", "PDH", "PDL", "PWH", "PWL"]


def near_level(d, k, lo, hi, tol):
    L = np.column_stack([d[x].to_numpy(float)[k] for x in LEVELS])
    a = d.atr.to_numpy()[k][:, None]
    return ((L >= lo[:, None] - tol * a) & (L <= hi[:, None] + tol * a)).any(1)


# ----------------------------------------------------------------------------
# candidates per (logic, entry, variant)  -> DataFrame k, side, entry, stop, K, known_k, first_k
# ----------------------------------------------------------------------------
def zone_entries(z, mode, kind):
    if kind == "fvg":
        e = z.near if mode == "edge" else (z.near + z.far) / 2
    else:
        e = z.ob_open if mode == "edge" else (z.ob_high + z.ob_low) / 2
        z = z.assign(stop=np.where(z.side > 0, z.ob_low, z.ob_high))
    return z.assign(entry=e)


def candidates(d, logic, entry, mode):
    c, atr = d.close.to_numpy(), d.atr.to_numpy()
    ok = d.can_new.to_numpy()
    if entry == "E1":
        if logic == "L1":
            e14, e9 = d.ema14.to_numpy(), d.ema9.to_numpy()
            pc, pe = np.roll(c, 1), np.roll(e14, 1)
            st, sth = d.st.to_numpy(), d.st_hi.to_numpy()
            up = (st == 1) & (sth == 1) & (pc <= pe) & (c > e14) & (e9 < c)
            dn = (st == -1) & (sth == -1) & (pc >= pe) & (c < e14) & (e9 > c)
            k = np.flatnonzero((up | dn) & ok)
            side = np.where(up[k], 1, -1)
            z = pd.DataFrame(dict(k=k, side=side, entry=e9[k]))
        elif logic == "L2":
            L = np.column_stack([d[x].to_numpy(float) for x in LEVELS])
            dist = c[:, None] - L
            lo_ok = (dist >= 0.1 * atr[:, None]) & (dist <= 1.5 * atr[:, None])
            hi_ok = (-dist >= 0.1 * atr[:, None]) & (-dist <= 1.5 * atr[:, None])
            buy = np.where(lo_ok, L, -np.inf).max(1)
            sell = np.where(hi_ok, L, np.inf).min(1)
            k = np.flatnonzero(ok & (np.isfinite(buy) | np.isfinite(sell)))
            z = pd.DataFrame(dict(k=k, buy=buy[k], sell=sell[k]))
            z["side"] = 0
            z["entry"] = np.nan
        else:  # L3 native
            hh, ll = d.hh12.to_numpy(), d.ll12.to_numpy()
            nh = ok & (hh - c <= 0.5 * atr) & (hh - c > 0)
            nl = ok & (c - ll <= 0.5 * atr) & (c - ll > 0)
            k = np.flatnonzero(nh | nl)
            side = np.where(nh[k], -1, 1)
            z = pd.DataFrame(dict(k=k, side=side, entry=np.where(side < 0, hh[k], ll[k])))
        z["stop_dist"] = atr[z.k]
        z["K"] = K_E1
        z["known_k"] = z["k"]; z["first_k"] = z["k"]
        return z
    kind = "fvg" if entry == "E2" else "ob"
    base = fvgs(d) if kind == "fvg" else obs(d)
    z = zone_entries(base, mode, kind)
    k = z.k.to_numpy()
    if logic == "L1":
        sth = d.st_hi.to_numpy()[k]
        need = (d.st.to_numpy()[k] == z.side.to_numpy()) if kind == "fvg" else True
        keep = (sth == z.side.to_numpy()) & need
    elif logic == "L2":
        if kind == "fvg":
            lo, hi = np.minimum(z.near, z.far).to_numpy(), np.maximum(z.near, z.far).to_numpy()
        else:
            lo, hi = z.ob_low.to_numpy(), z.ob_high.to_numpy()
        keep = near_level(d, k, lo, hi, 0.25)
    else:  # L3 FVG pointing back into the range, formed at the extreme
        if kind == "ob":
            return pd.DataFrame(columns=["k"])
        hh3 = np.roll(d.hh12.to_numpy(), 3)[k]; ll3 = np.roll(d.ll12.to_numpy(), 3)[k]
        hmax = np.maximum.reduce([d.high.to_numpy()[k - j] for j in range(3)])
        lmin = np.minimum.reduce([d.low.to_numpy()[k - j] for j in range(3)])
        a = atr[k]
        keep = np.where(z.side < 0, hmax >= hh3 - 0.25 * a, lmin <= ll3 + 0.25 * a)
    z = z[keep & ok[k]].copy()
    k = z.k.to_numpy()
    # pending limit must be on the pullback side of the close
    z = z[np.where(z.side > 0, z.entry < c[k], z.entry > c[k])]
    sd = np.abs(z.entry - z.stop).to_numpy()
    a = atr[z.k]
    z = z[(sd >= 0.25 * a) & (sd <= 3 * a) & (np.sign(z.entry - z.stop) == z.side)].copy()
    z["stop_dist"] = np.abs(z.entry - z.stop)
    z["K"] = K_ZONE
    return z.reset_index(drop=True)


# ----------------------------------------------------------------------------
# fills / exits on 1m, chunked
# ----------------------------------------------------------------------------
def _fill(D, p, side, lvl, win):
    out = np.full(len(p), -1)
    for s in range(0, len(p), 4000):
        sl_ = slice(s, s + 4000)
        pp = p[sl_]
        idx = np.clip(pp[:, None] + np.arange(win)[None, :], 0, len(D["hi"]) - 1)
        raw = pp[:, None] + np.arange(win)[None, :]
        okm = raw <= D["flat_i"][np.clip(pp, 0, len(D["hi"]) - 1)][:, None]
        th = np.where(side[sl_][:, None] > 0, D["lo"][idx] < lvl[sl_][:, None], D["hi"][idx] > lvl[sl_][:, None]) & okm
        has = th.any(1)
        out[sl_] = np.where(has, pp + th.argmax(1), -1)
    return out




def _resolve(D, f, side, entry, tp, sl, hold, market=False):
    n = len(f)
    ex = np.zeros(n, int); px = np.zeros(n); mae = np.zeros(n); mfe = np.zeros(n); isl = np.zeros(n, bool)
    N = len(D["hi"])
    for s in range(0, n, 1500):
        sl_ = slice(s, s + 1500)
        ff = f[sl_]
        raw = ff[:, None] + np.arange(hold + 1)[None, :]
        idx = np.clip(raw, 0, N - 1)
        last = np.minimum(ff + hold, D["flat_i"][np.clip(ff, 0, N - 1)])
        live = raw <= last[:, None]
        hi, lo = D["hi"][idx], D["lo"][idx]
        sd = side[sl_][:, None] > 0
        slh = np.where(sd, lo <= sl[sl_][:, None], hi >= sl[sl_][:, None]) & live
        tph = np.where(sd, hi >= tp[sl_][:, None], lo <= tp[sl_][:, None]) & live
        if not market and not TPFIRST:
            tph[:, 0] = False
        big = hold + 5
        fs = np.where(slh.any(1), slh.argmax(1), big)
        ft = np.where(tph.any(1), tph.argmax(1), big)
        stop_first = (fs < ft) if TPFIRST else (fs <= ft)
        off = np.where(stop_first, fs, ft)
        p_ = np.where(stop_first, sl[sl_], tp[sl_])
        none = off >= big
        e = np.where(none, last, ff + off)
        p_ = np.where(none, D["cl"][np.clip(last, 0, N - 1)], p_)
        ex[sl_], px[sl_] = e, p_
        isl[sl_] = stop_first & ~none
        after = (np.arange(hold + 1)[None, :] >= 1) & (raw <= e[:, None]) & live
        adv = np.where(sd, entry[sl_][:, None] - lo, hi - entry[sl_][:, None])
        fav = np.where(sd, hi - entry[sl_][:, None], entry[sl_][:, None] - lo)
        mae[sl_] = np.where(after, adv, -np.inf).max(1).clip(min=0)
        mfe[sl_] = np.where(after, fav, -np.inf).max(1).clip(min=0)
    return ex, px, mae, mfe, isl


def _trades(D, sym, f, ex, side, ent, px):
    t1 = D["t1"]
    return pd.DataFrame(dict(entry_time=t1[f], exit_time=t1[ex], side=side.astype(float), entry_px=ent,
                             exit_px=px, qty=1.0, notional_usd=0.0, fee_usd=0.0, instrument=sym, multiplier=1.0))


def run(D, d, sym, tf, logic, entry, mode, rr, gate=None):
    """rr = stop as a multiple of the FIXED target distance (1 -> 1:1, 2 -> risk 2 : reward 1).
    Returns unpriced 1-lot trades + extras."""
    z = candidates(d, logic, entry, mode)
    if len(z) == 0:
        return pd.DataFrame(), {}
    if gate is not None:
        z = z[gate[z.k.to_numpy()]].reset_index(drop=True)
        if len(z) == 0:
            return pd.DataFrame(), {}
    if entry != "E1":
        check_no_lookahead(d, z, D, f"{sym} {tf} {logic} {entry}")
    tfm = TF_MIN[tf]
    p = d.i1.to_numpy()[z.k.to_numpy()]
    if logic == "L2" and entry == "E1":
        win = K_E1 * tfm
        m_b, m_s = np.isfinite(z.buy.to_numpy()), np.isfinite(z.sell.to_numpy())
        fb = np.full(len(z), -1); fs = np.full(len(z), -1)
        if m_b.any():
            fb[m_b] = _fill(D, p[m_b], np.ones(m_b.sum()), z.buy.to_numpy()[m_b], win)
        if m_s.any():
            fs[m_s] = _fill(D, p[m_s], -np.ones(m_s.sum()), z.sell.to_numpy()[m_s], win)
        BIG = 1 << 60
        b_, s_ = np.where(fb < 0, BIG, fb), np.where(fs < 0, BIG, fs)
        side = np.where(b_ < s_, 1, np.where(s_ < b_, -1, 0)); side[(b_ == BIG) & (s_ == BIG)] = 0
        f = np.where(side == 1, fb, np.where(side == -1, fs, -1))
        ent = np.where(side == 1, z.buy.to_numpy(), z.sell.to_numpy())
    else:
        side = z.side.to_numpy().astype(int)
        ent = z.entry.to_numpy(float)
        f = np.full(len(z), -1)
        for Kv in np.unique(z.K):
            m = z.K.to_numpy() == Kv
            f[m] = _fill(D, p[m], side[m], ent[m], int(Kv) * tfm)
    tgt = z.stop_dist.to_numpy(float)          # base distance = the FIXED target distance
    sd = rr * tgt                               # stop = rr x target
    tp = ent + side * tgt
    sl = ent - side * sd
    m = (f >= 0) & (side != 0)
    check_geometry(side[m], ent[m], tp[m], sl[m], f"{sym} {tf} {logic} {entry} {mode} rr{rr}")
    n = len(f)
    ex = np.full(n, -1); px = np.full(n, np.nan)
    mae = np.zeros(n); mfe = np.zeros(n); isl = np.zeros(n, bool)
    if m.any():
        ex[m], px[m], mae[m], mfe[m], isl[m] = _resolve(D, f[m], side[m], ent[m], tp[m], sl[m], HOLD_BARS * tfm)
    Kmin = z.K.to_numpy() * tfm
    keep = np.zeros(n, bool); busy = -1
    for j in np.argsort(p, kind="stable"):
        if p[j] <= busy:
            continue
        if not m[j]:
            busy = p[j] + Kmin[j] - 1
            continue
        keep[j] = True; busy = ex[j]
    tr = _trades(D, sym, f[keep], ex[keep], side[keep], ent[keep], px[keep])
    extra = dict(R=sd[keep], tgt=tgt[keep], mae=mae[keep], mfe=mfe[keep], is_sl=isl[keep],
                 sig_k=z.k.to_numpy()[keep], rr=rr)
    return tr, extra


def metrics(D, d, tr, extra):
    """tr must already be priced."""
    r = common.evaluate(tr, 3, start=D["start"], end=D["end"])
    if not r["n"]:
        return r
    t = common.add_pnl(tr)
    win = t.net_pnl.to_numpy() > 0
    R, mae, mfe = extra["R"], extra["mae"], extra["mfe"]
    lv, fee = t.multiplier.to_numpy(), t.fee_usd.to_numpy()
    w_, l_ = extra["tgt"] * lv - fee, extra["R"] * lv + fee
    r.update(
        trades_per_day=r["n"] / d.sday.nunique(),
        hold_avg=float(t.hold_min.mean()), hold_med=float(t.hold_min.median()),
        win_dd_any=float((mae[win] > 0).mean()) if win.any() else float("nan"),
        win_dd_half_r=float((mae[win] >= 0.5 * R[win]).mean()) if win.any() else float("nan"),
        loser_mfe_half_r=float((mfe[~win] >= 0.5 * R[~win]).mean()) if (~win).any() else float("nan"),
        loser_mfe_half_tgt=float((mfe[~win] >= 0.5 * extra["tgt"][~win]).mean()) if (~win).any() else float("nan"),
        long_share=float((t.side > 0).mean()),
        gross_over_fees=float(r["gross"] / r["fees"]) if r["fees"] else float("nan"),
        be_wr=float(l_.mean() / (w_.mean() + l_.mean())),
        fee_per_trade=float(fee.mean()),
    )
    return r


RRS = (1, 2, 3)


def grid():
    g = []
    for rr in RRS:
        for tf in ("15min", "1h"):
            for L in ("L1", "L2", "L3"):
                g.append((tf, L, "E1", "native" if L != "L1" else "ema9", rr))
                for mode in ("edge", "ce50"):
                    g.append((tf, L, "E2", mode, rr))
                if L != "L3":
                    for mode in ("edge", "ce50"):
                        g.append((tf, L, "E3", mode, rr))
    return g


def vname(v):
    return "_".join(map(str, v[:4])) + "_rr" + str(v[4]) + "to1"


def tf_gates(d, D):
    lo, hi = D["start"], D["end"]
    f1 = (d.close_time < lo + (hi - lo) / 3).to_numpy()
    er, vr, ss = d.er.to_numpy(), d.volr.to_numpy(), d.sess.to_numpy()
    e33, e67 = np.nanpercentile(er[f1], [33.3, 66.7]); v33, v67 = np.nanpercentile(vr[f1], [33.3, 66.7])
    return {"er_lo": er <= e33, "er_mid": (er > e33) & (er < e67), "er_hi": er >= e67,
            "vol_lo": vr <= v33, "vol_mid": (vr > v33) & (vr < v67), "vol_hi": vr >= v67,
            "asia": ss == 0, "london": ss == 1, "ny": ss == 2}


def random_control(D, d, sym, tr, extra, draws, tf, seed=0):
    """same session days + sides; random signal-bar close; market entry next 1m open;
    same target distance and same rr stop as the paired real trade; headline costs."""
    rng = np.random.default_rng(seed)
    if len(tr) == 0:
        return np.array([0.0])
    elig = {s_: np.asarray(ix) for s_, ix in d[d.can_new].groupby("sday").indices.items()}
    sday = d.sday.to_numpy()[extra["sig_k"]]
    sides = tr.side.to_numpy().astype(int)
    tg, R = extra["tgt"], extra["R"]
    hold = HOLD_BARS * TF_MIN[tf]
    nets = []
    for _ in range(draws):
        ks = np.array([rng.choice(elig[s_]) if s_ in elig else -1 for s_ in sday])
        m = ks >= 0
        p = d.i1.to_numpy()[ks[m]]
        e = D["op"][p]
        s_ = sides[m]
        tp, sl = e + s_ * tg[m], e - s_ * R[m]
        check_geometry(s_, e, tp, sl, "control")
        ex, px, _, _, _ = _resolve(D, p, s_, e, tp, sl, hold, market=True)
        keep = np.zeros(len(p), bool); busy = -1
        for j in np.argsort(p, kind="stable"):
            if p[j] <= busy:
                continue
            keep[j] = True; busy = ex[j]
        t = price(_trades(D, sym, p[keep], ex[keep], s_[keep], e[keep], px[keep]), sym)
        nets.append(common.evaluate(t, 3)["net"])
    return np.array(nets)


def scen_table(D, sym, tr, extra):
    out = {}
    for sc in scenario_fees(sym, np.array([1.0])):
        r = common.evaluate(price(tr, sym, sc), 3, start=D["start"], end=D["end"])
        out[sc] = dict(net=r["net"], fees=r["fees"], folds=r["folds"], max_dd=r["max_dd"], wr=r["wr"], pf=r["pf"])
    r = common.evaluate(price(tr, sym, None, is_sl=extra.get("is_sl"), slip=True), 3, start=D["start"], end=D["end"])
    out["headline+slip"] = dict(net=r["net"], folds=r["folds"])
    r = common.evaluate(price(tr, sym, None, mult=2.0), 3, start=D["start"], end=D["end"])
    out["headline_x2"] = dict(net=r["net"], folds=r["folds"])
    return out


# ----------------------------------------------------------------------------
# part (a): restate the previous 5m/1m picks at 1.0 lot under every cost scenario
# ----------------------------------------------------------------------------
def part_a():
    rows, picks = [], {}
    for f, kind in (("h_ema_vwap_scalper_XAUUSD_NAS100.json", "orig"), ("h_ema_vwap_scalper.json", "orig"),
                    ("h_ema_vwap_scalper_inverse_XAUUSD_NAS100.json", "inv"),
                    ("h_ema_vwap_scalper_inverse_US30_GBPJPY.json", "inv")):
        js = json.load(open(H.HERE / f))
        for sym, r in js["instruments"].items():
            for L, info in r["picks"].items():
                picks.setdefault((kind, sym, L), info["pick"])
    Ds = {}
    for (kind, sym, L), pk in sorted(picks.items(), key=lambda x: (["XAUUSD", "NAS100", "US30", "GBPJPY"].index(x[0][1]), x[0][0], x[0][2])):
        D = Ds.setdefault(sym, H.prep(sym))
        parts = pk.split("_")
        v = (("L1", parts[1], parts[2]) if L == "L1" else
             (("L2", "_".join(parts[1:-1]), float(parts[-1])) if L == "L2" else ("L3", int(parts[1]), float(parts[2]))))
        tr = (H.run_variant if kind == "orig" else I.run_variant)(D, v)
        old = common.evaluate(tr, 3, start=D["start"], end=D["end"])
        row = dict(instr=sym, kind=kind, logic=L, pick=pk, n=old["n"], net_100usd_risk_oldcost=round(old["net"]))
        for sc in scenario_fees(sym, np.array([1.0])):
            r = common.evaluate(price(tr, sym, sc), 3, start=D["start"], end=D["end"])
            row[f"net_1lot_{sc}"] = round(r["net"]); row[f"fees_{sc}"] = round(r["fees"])
            row[f"maxdd_{sc}"] = round(r["max_dd"]); row[f"folds_{sc}"] = [round(x) for x in r["folds"]]
        rows.append(row)
        print(row, flush=True)
    (H.HERE / "h_ema_vwap_scalper_htf_partA.json").write_text(
        json.dumps(dict(lot_value=LOT_VALUE, notes=LOT_NOTE, rows=rows), indent=1))


# ----------------------------------------------------------------------------
def main():
    global TPFIRST
    ap = argparse.ArgumentParser()
    ap.add_argument("--part", default="b")
    ap.add_argument("--instr", default="XAUUSD,NAS100")
    ap.add_argument("--draws", type=int, default=300)
    ap.add_argument("--no-lab", action="store_true")
    a = ap.parse_args()
    if a.part == "a":
        return part_a()
    out = {"grid_size_per_instrument": len(grid()), "lot_value": LOT_VALUE, "notes": LOT_NOTE, "instruments": {}}
    for sym in a.instr.split(","):
        print(f"== {sym} (headline cost scenario {HEADLINE[sym]})", flush=True)
        D = H.prep(sym)
        frames = {tf: prep_tf(D, sym, tf) for tf in TF_MIN}
        res = {"variants": {}, "picks": {}, "headline": HEADLINE[sym]}
        cache = {}
        for v in grid():
            d = frames[v[0]]
            tr, ex = run(D, d, sym, *v)
            cache[v] = (tr, ex)
            r = metrics(D, d, price(tr, sym), ex) if len(tr) else common.empty_result()
            if len(tr):
                r["scenarios"] = scen_table(D, sym, tr, ex)
            res["variants"][vname(v)] = r
            if r["n"]:
                sc = r["scenarios"]
                print(f"  {vname(v):28s} n={r['n']:5d} /d={r['trades_per_day']:.2f} net={r['net']:9.0f} fee/t={r['fee_per_trade']:.0f} "
                      f"wr={r['wr']:.2f} be={r['be_wr']:.2f} aw={r['avg_win']:.0f} al={r['avg_loss']:.0f} pf={r['pf']:.2f} "
                      f"f={[round(x) for x in r['folds']]} dd={r['max_dd']:.0f} hold={r['hold_avg']:.0f}/{r['hold_med']:.0f} "
                      f"winDD={r['win_dd_any']:.2f}/{r['win_dd_half_r']:.2f} lossMFE={r['loser_mfe_half_r']:.2f}/{r['loser_mfe_half_tgt']:.2f} L%={r['long_share']:.2f} "
                      f"| " + " ".join(f"{k}={x['net']:.0f}" for k, x in sc.items()), flush=True)
            else:
                print(f"  {vname(v):28s} n=0", flush=True)
        for rr in RRS:
            for tf in TF_MIN:
                d = frames[tf]
                G = tf_gates(d, D)
                for L in ("L1", "L2", "L3"):
                    vs = [v for v in grid() if v[4] == rr and v[0] == tf and v[1] == L and res["variants"][vname(v)]["n"] > 0]
                    if not vs:
                        continue
                    pick = max(vs, key=lambda v: res["variants"][vname(v)]["folds"][0])
                    base = res["variants"][vname(pick)]
                    nat_key = "er_hi" if L == "L1" else "er_lo"
                    trn, exn = run(D, d, sym, *pick, gate=G[nat_key])
                    nat = common.evaluate(price(trn, sym), 3, start=D["start"], end=D["end"]) if len(trn) else common.empty_result()
                    gres = {}
                    for gk, gm in G.items():
                        tg, _ = run(D, d, sym, *pick, gate=gm)
                        gres[gk] = common.evaluate(price(tg, sym), 3, start=D["start"], end=D["end"]) if len(tg) else common.empty_result()
                    f1n = {gk: (g_["folds"][0] if g_["fold_n"][0] >= 20 else -1e18) for gk, g_ in gres.items()}
                    bg = max(f1n, key=f1n.get)
                    TPFIRST = True
                    tb, _ = run(D, d, sym, *pick)
                    TPFIRST = False
                    best = common.evaluate(price(tb, sym, mult=0.0), 3, start=D["start"], end=D["end"])
                    info = dict(pick=vname(pick), oos_f2f3=base["folds"][1] + base["folds"][2], base=base,
                                natural_gate=nat_key, natural=nat, best_gate=bg, best_gate_res=gres[bg],
                                best_gate_oos_f2f3=gres[bg]["folds"][1] + gres[bg]["folds"][2],
                                all_gates={k: dict(net=g_["net"], folds=g_["folds"], n=g_["n"]) for k, g_ in gres.items()},
                                best_case_0cost_tpfirst=dict(net=best["net"], folds=best["folds"]))
                    if sym in CONTROL_SYMS and a.draws > 0:
                        nets = random_control(D, d, sym, *cache[pick], a.draws, tf)
                        info["control"] = dict(mean=float(nets.mean()), p5=float(np.percentile(nets, 5)),
                                               p95=float(np.percentile(nets, 95)),
                                               rank_pct=float((nets < base["net"]).mean() * 100))
                    res["picks"][f"rr{rr}_{tf}_{L}"] = info
                    print(f"  PICK rr{rr} {tf} {L}: {vname(pick)} n={base['n']} net={base['net']:.0f} wr={base['wr']:.2f} be={base['be_wr']:.2f} "
                          f"oosF2F3={info['oos_f2f3']:.0f} nat({nat_key})={nat['net']:.0f}{[round(x) for x in nat['folds']]} "
                          f"bestgate={bg} gateOOS={info['best_gate_oos_f2f3']:.0f} best0cost={best['net']:.0f}"
                          f"{[round(x) for x in best['folds']]} ctrl={info.get('control')}", flush=True)
        if not a.no_lab:
            per = (D["start"], D["end"])
            src = "tests/h_ema_vwap_scalper_htf.py"
            for v in grid():
                r = res["variants"][vname(v)]
                common.record_to_lab(STRAT, vname(v), sym, v[0],
                                     dict(tf=v[0], logic=v[1], entry=v[2], mode=v[3], rr=v[4], lot=1.0, cost=HEADLINE[sym]),
                                     r, period=per, source=src,
                                     notes=f"1.0 lot, lot_value={LOT_VALUE[sym]}, cost scenario {HEADLINE[sym]}")
            for key, info in res["picks"].items():
                tf = key.split("_")[1]
                common.record_to_lab(STRAT, f"{info['pick']}__gate_{info['natural_gate']}", sym, tf,
                                     {"gate": info["natural_gate"]}, info["natural"], period=per, source=src,
                                     baseline_net=info["base"]["net"])
                common.record_to_lab(STRAT, f"{info['pick']}__gate_{info['best_gate']}_f1pick", sym, tf,
                                     {"gate": info["best_gate"]}, info["best_gate_res"], period=per, source=src,
                                     baseline_net=info["base"]["net"], notes="gate chosen on fold 1 only")
        out["instruments"][sym] = res
    fn = H.HERE / f"h_ema_vwap_scalper_htf_{a.instr.replace(',', '_')}.json"
    fn.write_text(json.dumps(out, indent=1, default=float))
    print("wrote", fn.name)


if __name__ == "__main__":
    main()
