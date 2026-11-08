#!/usr/bin/env python3
"""h_fx_edges: FX carry / trend / Tokyo A+ / breakouts + US30, net of Genesis
costs and swap. Rules are pre-registered in h_fx_edges.md.

Usage: python h_fx_edges.py daily|intraday|us30|all
"""
from __future__ import annotations
import sys, json, math
from pathlib import Path
import numpy as np, pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import common as C  # noqa: E402

FX = HERE.parent / "data" / "fx"
OUT = HERE / "h_fx_edges.json"
RNG = np.random.default_rng(20260924)
N_CTRL = 300

PAIRS = ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD",
         "GBPJPY", "NZDJPY", "AUDJPY", "EURJPY", "CADJPY", "CHFJPY", "EURGBP"]
SPREAD_PIPS = {"EURUSD": 0.3, "GBPUSD": 0.5, "USDJPY": 0.4, "AUDUSD": 0.4,
               "USDCHF": 0.6, "USDCAD": 0.6, "NZDUSD": 0.6, "EURGBP": 0.6,
               "EURJPY": 0.8, "AUDJPY": 1.0, "GBPJPY": 1.5, "NZDJPY": 1.5,
               "CADJPY": 1.5, "CHFJPY": 1.5}
COMM_RT = 6.0          # USD per lot round trip (ASSUMPTION)
LOT = 100_000
MARKUP = 1.0           # %/yr swap markup each side (ASSUMPTION)
CCY_RATE = {"US": "USD", "JP": "JPY", "GB": "GBP", "EZ": "EUR", "AU": "AUD",
            "NZ": "NZD", "CA": "CAD", "CH": "CHF"}
FALLBACK = {"NZ": "alt_IR3TIB01NZM156N.csv", "CH": "alt_IR3TIB01CHM156N.csv",
            "EZ": "alt_ECBDFR.csv"}
COST_MULT = 1.0


def pip(pair):
    return 0.01 if pair.endswith("JPY") else 0.0001


# --------------------------------------------------------------------------
# data
# --------------------------------------------------------------------------
def _clean_daily(s: pd.Series) -> tuple[pd.Series, int]:
    r = np.log(s).diff()
    spike = (r.abs() > 0.06) & (r * r.shift(-1) < 0) & (r.shift(-1).abs() > 0.8 * r.abs())
    s = s.copy()
    s[spike] = np.nan
    return s.ffill(limit=3), int(spike.sum())


def load_daily_closes():
    cols, spikes = {}, {}
    for p in PAIRS:
        d = pd.read_parquet(FX / f"{p}_1d.parquet")
        s = d["close"].astype(float)
        s.index = s.index.tz_convert("UTC").normalize()
        s = s[~s.index.duplicated(keep="last")]
        s, k = _clean_daily(s)
        cols[p], spikes[p] = s, k
    df = pd.DataFrame(cols).sort_index()
    df = df[df.index.dayofweek < 5].ffill(limit=3)
    return df, spikes


def load_rates(index: pd.DatetimeIndex) -> pd.DataFrame:
    out = {}
    for code, ccy in CCY_RATE.items():
        s = pd.read_csv(FX / f"rate_{code}.csv")
        s.columns = ["date", "v"]
        s["date"] = pd.to_datetime(s["date"], utc=True)
        s = s.set_index("date")["v"].astype(float).dropna()
        if code in FALLBACK:
            f = pd.read_csv(FX / FALLBACK[code])
            f.columns = ["date", "v"]
            f["date"] = pd.to_datetime(f["date"], utc=True)
            f["v"] = pd.to_numeric(f["v"], errors="coerce")
            f = f.set_index("date")["v"].dropna()
            f = f[f.index > s.index[-1] + pd.offsets.MonthEnd(0)]
            s = pd.concat([s, f])
        out[ccy] = s
    idx = index.union(pd.DatetimeIndex(sorted(set().union(*[set(v.index) for v in out.values()]))))
    r = pd.DataFrame({k: v.reindex(idx).ffill() for k, v in out.items()}).reindex(index).ffill()
    return r


def conv_tables(Cl: pd.DataFrame):
    usdjpy, usdchf, usdcad, gbpusd = Cl["USDJPY"], Cl["USDCHF"], Cl["USDCAD"], Cl["GBPUSD"]
    q = {"USD": 1.0 + 0 * usdjpy, "JPY": 1 / usdjpy, "CHF": 1 / usdchf,
         "CAD": 1 / usdcad, "GBP": gbpusd}
    b = {"EUR": Cl["EURUSD"], "GBP": gbpusd, "AUD": Cl["AUDUSD"], "NZD": Cl["NZDUSD"],
         "USD": 1.0 + 0 * usdjpy, "CAD": 1 / usdcad, "CHF": 1 / usdchf}
    convq = pd.DataFrame({p: q[p[3:]] for p in PAIRS})
    baseusd = pd.DataFrame({p: b[p[:3]] for p in PAIRS})
    return convq.ffill(), baseusd.ffill()


# --------------------------------------------------------------------------
# position-strategy engine (daily)
# --------------------------------------------------------------------------
class Daily:
    def __init__(self):
        self.Cl, self.spikes = load_daily_closes()
        self.Cl = self.Cl.loc["2004-01-01":]
        self.R = load_rates(self.Cl.index)
        # signal rate: month m uses the monthly value of m-1 (published after m-1 ends)
        self.Rsig = self._lag_month(self.R)
        self.convq, self.baseusd = conv_tables(self.Cl)
        self.carry = pd.DataFrame({p: self.Rsig[p[:3]] - self.Rsig[p[3:]] for p in PAIRS})
        self.carry_now = pd.DataFrame({p: self.R[p[:3]] - self.R[p[3:]] for p in PAIRS})
        me = self.Cl.index.to_series().groupby(self.Cl.index.to_period("M")).max()
        self.month_ends = pd.DatetimeIndex(me.tolist())
        self.start, self.end = pd.Timestamp("2005-01-01", tz="UTC"), self.Cl.index[-1] + pd.Timedelta(days=1)

    @staticmethod
    def _lag_month(R):
        per = R.index.to_period("M")
        monthly = R.groupby(per).first()           # FRED monthly value (constant within month)
        lagged = monthly.shift(1)
        return lagged.reindex(per).set_axis(R.index)

    # decisions: DataFrame of desired lots (+1/-1/0) decided at close of each date
    def monthly_decision(self, fn):
        dec = pd.DataFrame(np.nan, index=self.Cl.index, columns=PAIRS)
        for d in self.month_ends:
            dec.loc[d] = fn(d)
        return dec.ffill().fillna(0.0)

    def simulate(self, dec: pd.DataFrame, cost_mult=1.0, extra_lag=0):
        pos = dec.shift(1 + extra_lag).fillna(0.0)          # held from close t to close t+1
        pos = pos.where(self.Cl.notna(), 0.0)
        dC = self.Cl.diff().shift(-1)                       # C[t+1]-C[t] on row t
        cq_next = self.convq.shift(-1)
        price = (pos * dC * LOT * cq_next).fillna(0.0)
        days = pd.Series(self.Cl.index, index=self.Cl.index).diff().shift(-1).dt.days.fillna(0)
        notional = LOT * self.baseusd
        sgn = np.sign(pos)
        carry_pt = (sgn * self.carry_now / 100 * notional).mul(days / 365, axis=0) * pos.abs()
        markup_pt = (-MARKUP / 100 * notional).mul(days / 365, axis=0) * pos.abs()
        dpos = pos.diff().abs().fillna(pos.abs())
        half_spread = pd.DataFrame({p: SPREAD_PIPS[p] * pip(p) * LOT * self.convq[p] / 2 for p in PAIRS})
        cost = dpos * (COMM_RT / 2 + half_spread) * cost_mult
        # shift price/swap to the date they are realised (t+1) for accounting
        daily = dict(price=price.shift(1).fillna(0), carry=carry_pt.shift(1).fillna(0),
                     markup=markup_pt.shift(1).fillna(0), cost=cost.fillna(0), pos=pos,
                     notional=notional)
        return daily

    def rows(self, sim, start=None, end=None):
        price, carry, markup, cost, pos = (sim[k] for k in ("price", "carry", "markup", "cost", "pos"))
        per = price.index.to_period("M")
        held = (pos.shift(1).fillna(0).abs() > 0) | (cost > 0)
        recs = []
        for p in PAIRS:
            g = pd.DataFrame({"price": price[p], "carry": carry[p], "markup": markup[p],
                              "cost": cost[p], "held": held[p], "sgn": np.sign(pos[p].shift(1).fillna(0)),
                              "notional": sim["notional"][p]}, index=price.index)
            for m, x in g.groupby(per):
                if not x["held"].any():
                    continue
                t0, t1 = x.index[x["held"]][0], x.index[x["held"]][-1]
                gross = x["price"].sum() + x["carry"].sum() + x["markup"].sum()
                recs.append(dict(entry_time=t0, exit_time=t1 + pd.Timedelta(hours=23), side=1.0,
                                 entry_px=0.0, exit_px=float(gross), qty=1.0,
                                 notional_usd=float(x["notional"].mean()), fee_usd=float(x["cost"].sum()),
                                 instrument=p, price_pnl=float(x["price"].sum()),
                                 carry_pnl=float(x["carry"].sum()), markup_pnl=float(x["markup"].sum()),
                                 dir=float(x["sgn"][x["held"]].iloc[-1])))
        t = pd.DataFrame(recs)
        if len(t) and start is not None:
            t = t[(t.entry_time >= start) & (t.entry_time < end)]
        return t

    def equity(self, sim, start, end):
        net = (sim["price"] + sim["carry"] + sim["markup"] - sim["cost"]).sum(axis=1)
        return net.loc[start:end]


def max_dd(series):
    eq = series.cumsum()
    return float((eq.cummax().clip(lower=0) - eq).max()) if len(eq) else 0.0


def summarize(t, eq=None, extra=None):
    r = C.evaluate(t, n_folds=3, start=FOLD_START, end=FOLD_END) if len(t) else C.empty_result()
    out = {k: r[k] for k in ("n", "net", "gross", "fees", "pf", "wr", "avg_win", "avg_loss",
                              "folds", "fold_n", "fold_consistent", "sharpe", "max_dd", "avg_hold_min")}
    if eq is not None and len(eq):
        out["daily_max_dd"] = max_dd(eq)
        yrs = (eq.index[-1] - eq.index[0]).days / 365.25
        out["per_month"] = float(eq.sum() / max(yrs * 12, 1e-9))
        out["daily_sharpe"] = float(eq.mean() / eq.std() * math.sqrt(252)) if eq.std() > 0 else 0.0
        out["per_year"] = {int(y): round(float(v), 0) for y, v in eq.groupby(eq.index.year).sum().items()}
    if extra:
        out.update(extra)
    return out


FOLD_START = FOLD_END = None


def run_daily():
    global FOLD_START, FOLD_END
    D = Daily()
    FOLD_START, FOLD_END = D.start, D.end
    bounds = C.fold_bounds((D.start, D.end), 3)
    Cl = D.Cl

    def carry_xs(K):
        def f(d):
            c = D.carry.loc[d].dropna()
            c = c[Cl.loc[d, c.index].notna()]
            top = c.abs().sort_values(ascending=False).index[:K]
            v = pd.Series(0.0, index=PAIRS)
            v[top] = np.sign(c[top])
            return v
        return f

    def carry_thr(thr, trendL=None):
        def f(d):
            c = D.carry.loc[d]
            v = pd.Series(0.0, index=PAIRS)
            ok = c.abs() >= thr
            v[ok] = np.sign(c[ok])
            if trendL:
                i = Cl.index.get_loc(d)
                if i >= trendL:
                    tr = np.sign(Cl.iloc[i] - Cl.iloc[i - trendL])
                    v = v.where(np.sign(v) == tr, 0.0)
                else:
                    v[:] = 0
            return v.fillna(0.0)
        return f

    def tsmom(L):
        def f(d):
            i = Cl.index.get_loc(d)
            if i < L:
                return pd.Series(0.0, index=PAIRS)
            return np.sign(Cl.iloc[i] - Cl.iloc[i - L]).fillna(0.0)
        return f

    variants = {}
    for K in (3, 5):
        variants[f"C1_carry_top{K}"] = ("carry", D.monthly_decision(carry_xs(K)))
    for thr in (1.0, 2.0):
        variants[f"C1_carry_thr{thr:g}"] = ("carry", D.monthly_decision(carry_thr(thr)))
    for L in (63, 126, 252):
        variants[f"C2_tsmom{L}"] = ("trend", D.monthly_decision(tsmom(L)))
    ma50, ma200 = Cl.rolling(50).mean(), Cl.rolling(200).mean()
    variants["C2_ma50_200"] = ("trend", np.sign(ma50 - ma200).fillna(0.0))
    for L in (63, 126, 252):
        variants[f"C2c_carry_trend{L}"] = ("carry_trend", D.monthly_decision(carry_thr(1.0, L)))

    sims, res = {}, {}
    for name, (fam, dec) in variants.items():
        sim = D.simulate(dec)
        sims[name] = (fam, dec, sim)
        t = D.rows(sim, D.start, D.end)
        eq = D.equity(sim, D.start, D.end)
        res[name] = summarize(t, eq, dict(
            family=fam, price=float(t.price_pnl.sum()), carry=float(t.carry_pnl.sum()),
            markup=float(t.markup_pnl.sum()), avg_positions=float((dec.abs().sum(axis=1)).loc[D.start:].mean())))
        print(f"{name:22s} net={res[name]['net']:>10,.0f} folds={[round(x) for x in res[name]['folds']]} "
              f"price={res[name]['price']:>9,.0f} carry={res[name]['carry']:>9,.0f} markup={res[name]['markup']:>8,.0f} "
              f"fees={res[name]['fees']:>7,.0f} dd={res[name]['daily_max_dd']:>8,.0f}", flush=True)

    # walk-forward pick per family on fold 1, judge folds 2-3
    picks = {}
    for fam in ("carry", "trend", "carry_trend"):
        names = [n for n in variants if variants[n][0] == fam]
        best = max(names, key=lambda n: res[n]["folds"][0])
        fam_, dec, sim = sims[best]
        oos_t = D.rows(sim, bounds[1][0], bounds[2][1])
        oos_eq = D.equity(sim, bounds[1][0], bounds[2][1])
        s = summarize(oos_t, oos_eq)
        # stress: 2x cost, 1 extra day of lag
        sim2 = D.simulate(dec, cost_mult=2.0)
        s2 = float(D.equity(sim2, bounds[1][0], bounds[2][1]).sum())
        sim3 = D.simulate(dec, extra_lag=1)
        s3 = float(D.equity(sim3, bounds[1][0], bounds[2][1]).sum())
        # control: random sign per pair-month on OOS rows
        ctrl = []
        pr, ca, mk, fe = (oos_t[c].values for c in ("price_pnl", "carry_pnl", "markup_pnl", "fee_usd"))
        for _ in range(N_CTRL):
            sg = RNG.choice([-1.0, 1.0], size=len(pr))
            ctrl.append(float((sg * pr + sg * ca + mk - fe).sum()))
        ctrl = np.array(ctrl)
        oos_net = float(oos_eq.sum())
        crash = {}
        for lbl, a, b in [("2008 GFC", "2008-08-01", "2008-12-31"), ("2015 SNB", "2015-01-14", "2015-01-20"),
                          ("2020 Covid", "2020-02-20", "2020-03-31"), ("2024 yen unwind", "2024-07-10", "2024-08-09")]:
            crash[lbl] = round(float(D.equity(sim, pd.Timestamp(a, tz="UTC"), pd.Timestamp(b, tz="UTC")).sum()), 0)
        picks[fam] = dict(pick=best, fold1=res[best]["folds"][0], oos=s, oos_net=oos_net,
                          oos_folds=[float(D.equity(sim, *bounds[k]).sum()) for k in (1, 2)],
                          oos_net_2x_cost=s2, oos_net_extra_day_lag=s3,
                          ctrl_pct=float((ctrl < oos_net).mean() * 100), ctrl_median=float(np.median(ctrl)),
                          ctrl_p95=float(np.percentile(ctrl, 95)), crash=crash,
                          t_stat=float(oos_eq.mean() / oos_eq.std() * math.sqrt(len(oos_eq))) if oos_eq.std() > 0 else 0.0,
                          price=float(oos_t.price_pnl.sum()), carry=float(oos_t.carry_pnl.sum()),
                          markup=float(oos_t.markup_pnl.sum()), fees=float(oos_t.fee_usd.sum()))
        print(f"PICK {fam}: {best} OOS net={oos_net:,.0f} folds={[round(x) for x in picks[fam]['oos_folds']]} "
              f"2x={s2:,.0f} lag+1={s3:,.0f} ctrl%={picks[fam]['ctrl_pct']:.0f} crash={crash}", flush=True)

    # record every variant
    for name, r in res.items():
        fam = variants[name][0]
        t = D.rows(sims[name][2], D.start, D.end)
        rr = C.evaluate(t, 3, D.start, D.end)
        C.record_to_lab(f"fx_{fam}", name, "FX14", "1d", {"variant": name}, rr, (D.start, D.end),
                        source="tests/h_fx_edges.py", notes="Genesis cost+swap ASSUMED; monthly pair rows")
    return dict(variants=res, picks=picks, spikes_removed=D.spikes,
                bounds=[[str(a), str(b)] for a, b in bounds])


# ==========================================================================
# INTRADAY (hourly, 2023-12 -> 2026-09): C3 Tokyo A+, C4 tight range, C5 Asia/London
# ==========================================================================
def load_hourly():
    H = {}
    for p in PAIRS:
        h = pd.read_parquet(FX / f"{p}_1h.parquet").astype(float)
        h.index = h.index.tz_convert("UTC")
        h = h[~h.index.duplicated(keep="last")].sort_index()
        # drop bad prints: bar range > 8x median range, or close jump > 3% that reverts
        rg = (h.high - h.low)
        med = rg.rolling(500, min_periods=50).median()
        bad = rg > 12 * med
        h = h[~bad]
        H[p] = h
    return H


def rebuilt_daily(h):
    """daily bars on the 22:00 UTC (5pm NY) boundary; label = session date;
    'end' = time the day's close is known."""
    lab = (h.index + pd.Timedelta(hours=2)).floor("D")
    g = h.groupby(lab)
    d = pd.DataFrame({"open": g.open.first(), "high": g.high.max(), "low": g.low.min(),
                      "close": g.close.last(), "n": g.close.size(),
                      "end": g.apply(lambda x: x.index[-1] + pd.Timedelta(hours=1))})
    d = d[d.n >= 12]
    tr = pd.concat([d.high - d.low, (d.high - d.close.shift()).abs(), (d.low - d.close.shift()).abs()], axis=1).max(axis=1)
    d["atr"] = tr.rolling(14).mean()
    return d


def rsi_series(c, n=14):
    """Tokyo's RSI: simple average of last n gains/losses."""
    dlt = c.diff()
    g = dlt.clip(lower=0).rolling(n).mean()
    l = (-dlt.clip(upper=0)).rolling(n).mean()
    r = 100 - 100 / (1 + g / l)
    return r.where(l > 0, 100.0)


class Intra:
    def __init__(self):
        self.H = load_hourly()
        Dy = Daily()
        self.convq, self.baseusd, self.R = Dy.convq, Dy.baseusd, Dy.R
        self.D = {p: rebuilt_daily(self.H[p]) for p in PAIRS}
        self.start = pd.Timestamp("2024-02-01", tz="UTC")      # after 40 daily bars of warm-up
        self.end = max(h.index[-1] for h in self.H.values()) + pd.Timedelta(hours=1)
        self.arr = {p: (h.index.values, h.open.values, h.high.values, h.low.values, h.close.values)
                    for p, h in self.H.items()}

    def conv(self, p, t):
        s = self.convq[p]
        i = s.index.searchsorted(t.normalize(), side="right") - 1
        return float(s.iloc[max(i, 0)])

    def swap_usd(self, p, side, t0, t1):
        """rollover at 22:00 UTC; Wednesday rollover counts 3 nights."""
        rolls = pd.date_range(t0.floor("D") + pd.Timedelta(hours=22), t1, freq="D")
        rolls = rolls[(rolls > t0) & (rolls <= t1) & (rolls.dayofweek < 5)]
        if len(rolls) == 0:
            return 0.0
        nights = sum(3 if r.dayofweek == 2 else 1 for r in rolls)
        d = t0.normalize()
        i = self.R.index.searchsorted(d, side="right") - 1
        rb, rq = self.R[p[:3]].iloc[i], self.R[p[3:]].iloc[i]
        bu = self.baseusd[p]
        notional = LOT * float(bu.iloc[bu.index.searchsorted(d, side="right") - 1])
        return notional * (side * (rb - rq) - MARKUP) / 100 * nights / 365

    def cost_usd(self, p, t, mult=1.0):
        return (COMM_RT + SPREAD_PIPS[p] * pip(p) * LOT * self.conv(p, t)) * mult

    def manage(self, p, i0, side, entry, sl, tp, max_bars, tp_from_bar=0):
        """walk hourly bars from index i0 (entry bar, entered at its open or at a
        stop level inside it). stop checked first. Returns exit idx, px, reason, mae, mfe."""
        T, O, Hh, L, Cc = self.arr[p]
        n = len(T)
        last = min(i0 + max_bars - 1, n - 1)
        mae = mfe = 0.0
        for i in range(i0, last + 1):
            adv = (entry - L[i]) if side > 0 else (Hh[i] - entry)
            fav = (Hh[i] - entry) if side > 0 else (entry - L[i])
            hit_sl = (L[i] <= sl) if side > 0 else (Hh[i] >= sl)
            if hit_sl:
                px = sl
                if i > i0 and ((side > 0 and O[i] < sl) or (side < 0 and O[i] > sl)):
                    px = O[i]                                        # gap through the stop
                return i, px, "sl", max(mae, adv), mfe
            mae, mfe = max(mae, adv), max(mfe, fav)
            if i >= i0 + tp_from_bar:
                hit_tp = (Hh[i] >= tp) if side > 0 else (L[i] <= tp)
                if hit_tp:
                    return i, tp, "tp", mae, mfe
        return last, Cc[last], "time", mae, mfe

    def trade_row(self, p, side, t_in, t_out, e, x, sl_dist, mae, mfe, reason, mult=1.0, swap=True,
                  tp_dist=1e9, hold_cap=72):
        cv = self.conv(p, t_in)
        sw = self.swap_usd(p, side, t_in, t_out) if swap else 0.0
        cost = self.cost_usd(p, t_in, mult)
        return dict(entry_time=t_in, exit_time=t_out, side=float(side), entry_px=float(e),
                    exit_px=float(x + side * sw / (LOT * cv)), qty=float(LOT), multiplier=cv,
                    notional_usd=float(LOT * cv * e), fee_usd=float(cost), instrument=p,
                    swap_usd=float(sw), raw_exit=float(x), reason=reason,
                    mae_r=float(mae / sl_dist) if sl_dist > 0 else 0.0,
                    mfe_r=float(mfe / sl_dist) if sl_dist > 0 else 0.0,
                    sl_dist=float(sl_dist), tp_dist=float(tp_dist), hold_cap=int(hold_cap))

    # ---------------- C3 Tokyo A+ ----------------
    def a_plus_setups(self, p):
        d = self.D[p]
        h = self.H[p]
        c = d.close
        drsi = rsi_series(c)
        hi20, lo20 = d.high.rolling(20).max(), d.low.rolling(20).min()
        pos = (c - lo20) / (hi20 - lo20)
        # 4H bars on UTC buckets; a 4H bar is usable once its end <= day end
        h4 = h.resample("4h", origin="epoch").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
        h4_end = h4.index + pd.Timedelta(hours=4)
        r4 = rsi_series(h4.close)
        out = []
        for k in range(40, len(d)):
            T = d["end"].iloc[k]
            j = h4_end.searchsorted(T, side="right") - 1
            if j < 20 or np.isnan(pos.iloc[k]) or np.isnan(d.atr.iloc[k]):
                continue
            ps, dr = pos.iloc[k], drsi.iloc[k]
            h4r, h4rp = r4.iloc[j], r4.iloc[j - 1]
            o4, c4 = h4.open.iloc[j], h4.close.iloc[j]
            if ps <= 0.30 and dr < 45:
                sc = (0.30 - ps) / 0.30 * 35 + max(0, 45 - dr) / 45 * 25 + (20 if h4r > h4rp else 0) + (20 if c4 > o4 else 0)
                out.append((T, 1, sc, d.atr.iloc[k]))
            elif ps >= 0.70 and dr > 55:
                sc = (ps - 0.70) / 0.30 * 35 + max(0, dr - 55) / 45 * 25 + (20 if h4r < h4rp else 0) + (20 if c4 < o4 else 0)
                out.append((T, -1, sc, d.atr.iloc[k]))
        return out

    def run_a_plus(self, params, start, end, mult=1.0, setups_cache={}):
        thr, scheme = params["score"], params["scheme"]
        tp_a, sl_a = (0.5, 2.5) if scheme == "hold_bounce" else (1.5, 1.0)
        rows = []
        for p in PAIRS:
            if p not in setups_cache:
                setups_cache[p] = self.a_plus_setups(p)
            T_, O = self.arr[p][0], self.arr[p][1]
            busy_until = None
            for (T, side, sc, atr) in setups_cache[p]:
                if sc < thr or T < start or T >= end:
                    continue
                if busy_until is not None and T < busy_until:
                    continue
                i0 = np.searchsorted(T_, np.datetime64(T.tz_convert(None)), side="left")
                if i0 >= len(T_):
                    continue
                e = O[i0]
                sl, tp = e - side * sl_a * atr, e + side * tp_a * atr
                i, x, why, mae, mfe = self.manage(p, i0, side, e, sl, tp, 72)
                t_in, t_out = pd.Timestamp(T_[i0], tz="UTC"), pd.Timestamp(T_[i], tz="UTC") + pd.Timedelta(hours=1)
                rows.append(self.trade_row(p, side, t_in, t_out, e, x, sl_a * atr, mae, mfe, why, mult,
                                           tp_dist=tp_a * atr, hold_cap=72))
                busy_until = t_out
        return pd.DataFrame(rows)

    # ---------------- C4 tight-range breakout ----------------
    def run_tight(self, params, start, end, mult=1.0):
        tf, stopm = params["tf"], params["stop"]
        rows = []
        for p in PAIRS:
            h = self.H[p]
            b = h if tf == "1h" else h.resample("4h", origin="epoch").agg(
                {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
            step = pd.Timedelta(hours=1 if tf == "1h" else 4)
            tr = pd.concat([b.high - b.low, (b.high - b.close.shift()).abs(), (b.low - b.close.shift()).abs()], axis=1).max(axis=1)
            atr = tr.rolling(14).mean()
            hi, lo = b.high.rolling(20).max(), b.low.rolling(20).min()
            tight = (hi - lo) < 3 * atr
            T_, O, Hh, L, Cc = self.arr[p]
            free_at = pd.Timestamp(start)
            bidx = b.index
            for k in np.where(tight.values)[0]:
                t_arm = bidx[k] + step                         # bar k closed
                if t_arm < free_at or t_arm < start or t_arm >= end:
                    continue
                H_, L_, w = hi.iloc[k], lo.iloc[k], hi.iloc[k] - lo.iloc[k]
                if w <= 0:
                    continue
                i_a = np.searchsorted(T_, np.datetime64(t_arm.tz_convert(None)), side="left")
                i_exp = np.searchsorted(T_, np.datetime64((t_arm + 5 * step).tz_convert(None)), side="left")
                filled = None
                for i in range(i_a, min(i_exp, len(T_))):
                    up, dn = Hh[i] >= H_, L[i] <= L_
                    if up and dn:                                 # both sides in one bar: fill + stop
                        side = 1
                        e = max(O[i], H_)
                        sl = L_ if stopm == "opposite" else (H_ + L_) / 2
                        t_in = pd.Timestamp(T_[i], tz="UTC")
                        rows.append(self.trade_row(p, side, t_in, t_in + pd.Timedelta(hours=1), e, sl, abs(e - sl), abs(e - sl), 0, "sl", mult,
                                                   tp_dist=w, hold_cap=30 * (1 if tf == "1h" else 4)))
                        filled = (i, None)
                        break
                    if up or dn:
                        side = 1 if up else -1
                        lvl = H_ if up else L_
                        e = max(O[i], lvl) if up else min(O[i], lvl)
                        sl = (L_ if up else H_) if stopm == "opposite" else (H_ + L_) / 2
                        tp = e + side * w
                        mb = 30 * (1 if tf == "1h" else 4)
                        j, x, why, mae, mfe = self.manage(p, i, side, e, sl, tp, mb, tp_from_bar=1)
                        t_in = pd.Timestamp(T_[i], tz="UTC")
                        t_out = pd.Timestamp(T_[j], tz="UTC") + pd.Timedelta(hours=1)
                        rows.append(self.trade_row(p, side, t_in, t_out, e, x, abs(e - sl), mae, mfe, why, mult,
                                                   tp_dist=w, hold_cap=mb))
                        filled = (j, t_out)
                        break
                if filled is None:
                    free_at = t_arm + 5 * step
                else:
                    free_at = pd.Timestamp(T_[filled[0]], tz="UTC") + pd.Timedelta(hours=1)
        return pd.DataFrame(rows)

    # ---------------- C5 Asia range -> London breakout ----------------
    def run_asia(self, params, start, end, mult=1.0):
        ex, flt = params["exit"], params["filter"]
        rows = []
        for p in PAIRS:
            h = self.H[p]
            T_, O, Hh, L, Cc = self.arr[p]
            d = self.D[p]
            day = h.index.floor("D")
            for dt_, x in h.groupby(day):
                if dt_.dayofweek >= 5 or dt_ < start or dt_ >= end:
                    continue
                asia = x[x.index.hour < 7]
                if len(asia) < 6:
                    continue
                H_, L_ = asia.high.max(), asia.low.min()
                w = H_ - L_
                if w <= 0:
                    continue
                if flt == "narrow":
                    k = d.index.searchsorted(dt_, side="left") - 1     # prior session's ATR
                    if k < 14 or not (w < 0.5 * d.atr.iloc[k]):
                        continue
                i_a = np.searchsorted(T_, np.datetime64((dt_ + pd.Timedelta(hours=7)).tz_convert(None)), side="left")
                i_end = np.searchsorted(T_, np.datetime64((dt_ + pd.Timedelta(hours=16)).tz_convert(None)), side="left")
                for i in range(i_a, i_end):
                    up, dn = Hh[i] >= H_, L[i] <= L_
                    if up and dn:
                        e = max(O[i], H_)
                        t_in = pd.Timestamp(T_[i], tz="UTC")
                        rows.append(self.trade_row(p, 1, t_in, t_in + pd.Timedelta(hours=1), e, L_, e - L_, e - L_, 0, "sl", mult, swap=False,
                                                   tp_dist=w if ex == "tp1" else 1e9, hold_cap=max(i_end - i, 1)))
                        break
                    if up or dn:
                        side = 1 if up else -1
                        lvl = H_ if up else L_
                        e = max(O[i], lvl) if up else min(O[i], lvl)
                        sl = L_ if up else H_
                        tp = e + side * w if ex == "tp1" else (e + side * 1e9)
                        j, xp, why, mae, mfe = self.manage(p, i, side, e, sl, tp, i_end - i, tp_from_bar=1)
                        t_in = pd.Timestamp(T_[i], tz="UTC")
                        rows.append(self.trade_row(p, side, t_in, pd.Timestamp(T_[j], tz="UTC") + pd.Timedelta(hours=1),
                                                   e, xp, abs(e - sl), mae, mfe, why, mult, swap=False,
                                                   tp_dist=w if ex == "tp1" else 1e9, hold_cap=max(i_end - i, 1)))
                        break
        return pd.DataFrame(rows)

    # ---------------- random-entry control ----------------
    def control(self, trades, geom, n_draws=N_CTRL):
        """random hour on the same pair inside the same window, random side,
        same SL/TP distance (in price) and hold cap. Returns array of net sums."""
        if trades is None or len(trades) == 0:
            return np.zeros(n_draws)
        by = trades.groupby("instrument")
        prepared = []
        for p, t in by:
            T_ = self.arr[p][0]
            lo_i = np.searchsorted(T_, np.datetime64(trades.entry_time.min().tz_convert(None)))
            hi_i = np.searchsorted(T_, np.datetime64(trades.entry_time.max().tz_convert(None)))
            prepared.append((p, t, lo_i, max(hi_i, lo_i + 1)))
        sums = np.zeros(n_draws)
        for p, t, lo_i, hi_i in prepared:
            T_, O, Hh, L, Cc = self.arr[p]
            sl_dist = t["sl_dist"].values
            tp_dist = t["tp_dist"].values
            hold = t["hold_cap"].values.astype(int)
            fee = t["fee_usd"].values
            cv = t["multiplier"].values
            for dd in range(n_draws):
                idx = RNG.integers(lo_i, hi_i, size=len(t))
                sides = RNG.choice([-1, 1], size=len(t))
                tot = 0.0
                for m in range(len(t)):
                    i0, s = idx[m], sides[m]
                    e = O[i0]
                    last = min(i0 + hold[m], len(T_)) 
                    hh, ll = Hh[i0:last], L[i0:last]
                    if s > 0:
                        slh = np.nonzero(ll <= e - sl_dist[m])[0]
                        tph = np.nonzero(hh[1:] >= e + tp_dist[m])[0] + 1 if tp_dist[m] < 1e8 else np.array([], int)
                    else:
                        slh = np.nonzero(hh >= e + sl_dist[m])[0]
                        tph = np.nonzero(ll[1:] <= e - tp_dist[m])[0] + 1 if tp_dist[m] < 1e8 else np.array([], int)
                    a = slh[0] if len(slh) else 10**9
                    b = tph[0] if len(tph) else 10**9
                    if a <= b and a < 10**9:
                        pnl = -sl_dist[m]
                    elif b < 10**9:
                        pnl = tp_dist[m]
                    else:
                        pnl = s * (Cc[last - 1] - e)
                    tot += pnl * LOT * cv[m] - fee[m]
                sums[dd] += tot
        return sums


def intraday_eval(I, name, fn, grid, n_ctrl=N_CTRL):
    global FOLD_START, FOLD_END
    FOLD_START, FOLD_END = I.start, I.end
    bounds = C.fold_bounds((I.start, I.end), 3)
    table = {}
    full = {}
    for g in grid:
        key = json.dumps(g, sort_keys=True)
        t = fn(g, I.start, I.end)
        full[key] = t
        r = C.evaluate(t, 3, I.start, I.end) if len(t) else C.empty_result()
        table[key] = r
        print(f"  {name} {key:45s} n={r['n']:5d} net={r['net']:>10,.0f} folds={[round(x) for x in r['folds']]} wr={r['wr']:.2f}", flush=True)
    best = max(table, key=lambda k: table[k]["folds"][0])
    t = full[best]
    oos = t[(t.entry_time >= bounds[1][0])]
    r_oos = C.evaluate(oos, 3, I.start, I.end) if len(oos) else C.empty_result()
    g = json.loads(best)
    t2 = fn(g, bounds[1][0], I.end, mult=2.0) if len(oos) else oos
    net2 = float(C.evaluate(t2, 1)["net"]) if len(t2) else 0.0
    out = dict(grid={k: {kk: table[k][kk] for kk in ("n", "net", "folds", "wr", "pf", "avg_win", "avg_loss")} for k in table},
               pick=g, fold1=table[best]["folds"][0], oos=r_oos, oos_net=r_oos["net"], oos_folds=r_oos["folds"][1:],
               oos_net_2x_cost=net2)
    if len(oos):
        pnl = C.add_pnl(oos)
        wins = pnl[pnl.net_pnl > 0]
        out.update(
            trades_per_month=float(len(oos) / ((I.end - bounds[1][0]).days / 30.44)),
            avg_hold_h=float(pnl.hold_min.mean() / 60), median_hold_h=float(pnl.hold_min.median() / 60),
            winners_underwater_any=float((wins.mae_r > 0).mean()) if len(wins) else 0.0,
            winners_underwater_half_r=float((wins.mae_r >= 0.5).mean()) if len(wins) else 0.0,
            losers_in_profit_half_r=float((pnl[pnl.net_pnl <= 0].mfe_r >= 0.5).mean()) if (pnl.net_pnl <= 0).any() else 0.0,
            swap_total=float(oos.swap_usd.sum()),
            per_month=float(r_oos["net"] / ((I.end - bounds[1][0]).days / 30.44)),
            by_pair={p: round(float(v), 0) for p, v in pnl.groupby("instrument").net_pnl.sum().items()},
            t_stat=float(pnl.net_pnl.mean() / pnl.net_pnl.std() * math.sqrt(len(pnl))) if pnl.net_pnl.std() > 0 else 0.0,
        )
        if n_ctrl:
            ctrl = I.control(oos, None, n_ctrl)
            out.update(ctrl_pct=float((ctrl < r_oos["net"]).mean() * 100), ctrl_median=float(np.median(ctrl)),
                       ctrl_p95=float(np.percentile(ctrl, 95)))
    for k, r in table.items():
        C.record_to_lab(f"fx_{name}", k, "FX14", "1h", json.loads(k), r, (I.start, I.end),
                        source="tests/h_fx_edges.py", notes="Genesis cost+swap ASSUMED; hourly Yahoo")
    print(f"PICK {name}: {best} OOS net={r_oos['net']:,.0f} folds={[round(x) for x in r_oos['folds']]} 2x={net2:,.0f} "
          f"ctrl%={out.get('ctrl_pct')}", flush=True)
    return out


def run_intraday():
    I = Intra()
    res = {}
    res["C3_a_plus"] = intraday_eval(I, "a_plus", I.run_a_plus,
                                     [dict(score=sc, scheme=m) for sc in (60, 75) for m in ("hold_bounce", "fixed1.5")])
    res["C4_tight_range"] = intraday_eval(I, "tight_range", I.run_tight,
                                          [dict(tf=tf, stop=st) for tf in ("1h", "4h") for st in ("opposite", "mid")])
    res["C5_asia_london"] = intraday_eval(I, "asia_london", I.run_asia,
                                          [dict(exit=ex, filter=f) for ex in ("tp1", "eod") for f in ("none", "narrow")])
    return res



# ==========================================================================
# US30: trend (^DJI daily), overnight drift (DIA daily + US30 1m), ORB (US30 1m)
# ==========================================================================
US30_PT = 1.0                 # USD per point per 1.0 lot (ASSUMPTION - confirm with Genesis)
US30_RT = 6.0 + 2.0 * US30_PT # $6 commission + 2 pt spread per lot round trip (ASSUMPTION)
US30_FIN = 2.5                # %/yr financing markup over the US rate (ASSUMPTION)


def us_rate(index):
    s = pd.read_csv(FX / "rate_US.csv")
    s.columns = ["date", "v"]
    s["date"] = pd.to_datetime(s["date"], utc=True)
    s = s.set_index("date")["v"].astype(float)
    return s.reindex(index.union(s.index)).ffill().reindex(index)


def run_us30():
    global FOLD_START, FOLD_END
    out = {}
    # ---------------- U1 trend on ^DJI ----------------
    dj = pd.read_parquet(FX / "DJI_1d.parquet").astype(float)
    dj.index = dj.index.tz_convert("UTC").normalize()
    c = dj.close
    r_us = us_rate(c.index)
    start, end = pd.Timestamp("1993-01-01", tz="UTC"), c.index[-1] + pd.Timedelta(days=1)
    FOLD_START, FOLD_END = start, end
    bounds = C.fold_bounds((start, end), 3)
    me = pd.DatetimeIndex(c.index.to_series().groupby(c.index.to_period("M")).max().tolist())
    days = pd.Series(c.index, index=c.index).diff().shift(-1).dt.days.fillna(0)

    def sim(dec, mult=1.0):
        pos = dec.shift(1).fillna(0.0)
        price = pos * c.diff().shift(-1) * US30_PT
        fin = np.where(pos > 0, -(r_us + US30_FIN), np.where(pos < 0, (r_us - US30_FIN), 0.0)) / 100 \
            * c * US30_PT * days / 365 * pos.abs()
        cost = pos.diff().abs().fillna(pos.abs()) * US30_RT / 2 * mult
        net = (price.fillna(0) + pd.Series(fin, index=c.index).fillna(0)).shift(1).fillna(0) - cost
        return net, pos

    def rows(net, pos, s, e):
        per = net.index.to_period("M")
        recs = []
        for m_, x in net.groupby(per):
            ps = pos.loc[x.index]
            if not (ps.abs() > 0).any():
                continue
            recs.append(dict(entry_time=x.index[0], exit_time=x.index[-1] + pd.Timedelta(hours=23), side=1.0,
                             entry_px=0.0, exit_px=float(x.sum()), qty=1.0, notional_usd=float(c.loc[x.index].mean()),
                             fee_usd=0.0, instrument="US30", dir=float(np.sign(ps.iloc[-1]))))
        t = pd.DataFrame(recs)
        return t[(t.entry_time >= s) & (t.entry_time < e)] if len(t) else t

    def monthly(fn):
        dec = pd.Series(np.nan, index=c.index)
        for d in me:
            dec.loc[d] = fn(d)
        return dec.ffill().fillna(0.0)

    def tsm(L, longflat):
        def f(d):
            i = c.index.get_loc(d)
            if i < L:
                return 0.0
            sg = np.sign(c.iloc[i] - c.iloc[i - L])
            return max(sg, 0.0) if longflat else sg
        return f

    decs = {}
    for lf in (False, True):
        tag = "lf" if lf else "ls"
        for L in (63, 126, 252):
            decs[f"U1_tsmom{L}_{tag}"] = monthly(tsm(L, lf))
        ma = np.sign(c.rolling(50).mean() - c.rolling(200).mean()).fillna(0.0)
        decs[f"U1_ma50_200_{tag}"] = ma.clip(lower=0) if lf else ma
    decs["U1_buy_hold"] = pd.Series(1.0, index=c.index)
    u1 = {}
    for k, dec in decs.items():
        net, pos = sim(dec)
        eq = net.loc[start:end]
        t = rows(net, pos, start, end)
        u1[k] = summarize(t, eq)
        u1[k]["folds_daily"] = [float(net.loc[a:b].sum()) for a, b in bounds]
        print(f"  {k:22s} net={eq.sum():>9,.0f} folds={[round(x) for x in u1[k]['folds_daily']]} dd={u1[k]['daily_max_dd']:>8,.0f}", flush=True)
        C.record_to_lab("us30_trend", k, "US30", "1d", {"variant": k, "pt_value": US30_PT}, C.evaluate(t, 3, start, end),
                        (start, end), source="tests/h_fx_edges.py", notes="US30 $1/pt + costs/financing ASSUMED",
                        baseline_net=float(sim(decs["U1_buy_hold"])[0].loc[start:end].sum()) if k != "U1_buy_hold" else None)
    cand = [k for k in decs if k != "U1_buy_hold"]
    best = max(cand, key=lambda k: u1[k]["folds_daily"][0])
    net, pos = sim(decs[best])
    oos = float(net.loc[bounds[1][0]:end].sum())
    bh = float(sim(decs["U1_buy_hold"])[0].loc[bounds[1][0]:end].sum())
    net2, _ = sim(decs[best], 2.0)
    # control: random monthly position from the variant's own alphabet, same long share
    lf = best.endswith("_lf")
    held = pos.loc[bounds[1][0]:end]
    mon = held.groupby(held.index.to_period("M"))
    pr = (c.diff().shift(-1) * US30_PT).loc[bounds[1][0]:end]
    fin_l = (-(r_us + US30_FIN) / 100 * c * US30_PT * days / 365).loc[bounds[1][0]:end]
    fin_s = ((r_us - US30_FIN) / 100 * c * US30_PT * days / 365).loc[bounds[1][0]:end]
    pl = (pr + fin_l).groupby(pr.index.to_period("M")).sum()
    ps_ = (-pr + fin_s).groupby(pr.index.to_period("M")).sum()
    p_long = float((mon.last() > 0).mean())
    ctrl = []
    for _ in range(N_CTRL):
        if lf:
            z = RNG.random(len(pl)) < p_long
            ctrl.append(float(pl[z].sum()))
        else:
            z = RNG.random(len(pl)) < p_long
            ctrl.append(float(pl[z].sum() + ps_[~z].sum()))
    ctrl = np.array(ctrl)
    out["U1_trend"] = dict(variants=u1, pick=best, fold1=u1[best]["folds_daily"][0], oos_net=oos,
                           oos_folds=u1[best]["folds_daily"][1:], oos_buy_hold=bh,
                           oos_net_2x_cost=float(net2.loc[bounds[1][0]:end].sum()),
                           ctrl_pct=float((ctrl < oos).mean() * 100), ctrl_median=float(np.median(ctrl)),
                           per_month_oos=oos / ((end - bounds[1][0]).days / 30.44),
                           oos_max_dd=max_dd(net.loc[bounds[1][0]:end]))
    print(f"PICK U1: {best} OOS={oos:,.0f} folds={[round(x) for x in u1[best]['folds_daily'][1:]]} buyhold={bh:,.0f} ctrl%={out['U1_trend']['ctrl_pct']:.0f}", flush=True)

    # ---------------- U2 overnight drift ----------------
    dia = pd.read_parquet(FX / "DIA_1d.parquet").astype(float)
    dia = dia[dia.close > 0]
    lvl = c.reindex(dia.index).ffill()
    prev_c = dia.close.shift()
    on_ret = (dia.open + dia.dividends) / prev_c - 1
    day_ret = dia.close / dia.open - 1
    ok = (dia.open - prev_c).abs() / prev_c > 1e-5            # drop stale opens
    nights = pd.Series(dia.index, index=dia.index).diff().dt.days.fillna(1)
    lvl_prev = lvl.shift()
    ru = us_rate(dia.index)
    on_pts = (on_ret * lvl_prev * US30_PT)
    on_fin = -(ru + US30_FIN) / 100 * lvl_prev * US30_PT * nights / 365
    on_net = (on_pts + on_fin - US30_RT)[ok].dropna()
    day_net = (day_ret * lvl * US30_PT - US30_RT)[ok].dropna()
    hold_pts = (dia.close / prev_c - 1 + dia.dividends / prev_c) * lvl_prev * US30_PT
    hold_net = (hold_pts + on_fin).dropna()
    s2, e2 = on_net.index[0], on_net.index[-1] + pd.Timedelta(days=1)
    b2 = C.fold_bounds((s2, e2), 3)

    def folds(x):
        return [round(float(x.loc[a:b].sum()), 0) for a, b in b2]
    on_gross = (on_pts + on_fin)[ok].dropna()
    tstat = float(on_ret[ok].mean() / on_ret[ok].std() * math.sqrt(ok.sum()))
    diff = (on_ret - day_ret)[ok].dropna()
    out["U2_overnight_DIA"] = dict(
        period=[str(s2), str(e2)], n=int(len(on_net)), net=float(on_net.sum()), folds=folds(on_net),
        net_2x=float((on_pts + on_fin - 2 * US30_RT)[ok].sum()), gross_before_costs=float(on_gross.sum()),
        cost_total=float(US30_RT * len(on_net)), financing_total=float(on_fin[ok].sum()),
        day_session_net=float(day_net.sum()), day_folds=folds(day_net),
        buy_hold_net=float(hold_net.sum()), buy_hold_folds=folds(hold_net),
        overnight_share_of_hold_pts=float(on_pts[ok].sum() / hold_pts.sum()),
        overnight_ret_t=tstat, overnight_minus_day_t=float(diff.mean() / diff.std() * math.sqrt(len(diff))),
        win_rate=float((on_net > 0).mean()), per_month=float(on_net.sum() / ((e2 - s2).days / 30.44)),
        max_dd=max_dd(on_net), per_year={int(y): round(float(v), 0) for y, v in on_net.groupby(on_net.index.year).sum().items()})
    print("U2 DIA:", {k: v for k, v in out["U2_overnight_DIA"].items() if k != "per_year"}, flush=True)
    C.record_to_lab("us30_overnight", "U2_long_16to0930_DIA", "US30", "1d", {"pt_value": US30_PT},
                    dict(n=len(on_net), net=float(on_net.sum()), wr=float((on_net > 0).mean()), folds=folds(on_net)),
                    (s2, e2), source="tests/h_fx_edges.py", baseline_net=float(hold_net.sum()),
                    notes="DIA open/close scaled to DJI points; $1/pt, costs, financing ASSUMED")

    # ---------------- US30 1m: overnight + ORB ----------------
    sys.path.insert(0, str(Path.home() / "range-rent"))
    import rrdata
    b = rrdata.bars_1m("US30")[["open", "high", "low", "close"]].copy()
    b.index = b.index.tz_localize("UTC").tz_convert("America/New_York")      # broker clock verified = UTC
    et_day = b.index.normalize()
    mins = b.index.hour * 60 + b.index.minute
    rec_on, rec_day = [], []
    g_open = b[mins == 570].groupby(et_day[mins == 570]).open.first()          # 09:30 bar open
    g_close = b[mins == 959].groupby(et_day[mins == 959]).close.last()         # 15:59 bar close = 16:00
    both = g_open.index.intersection(g_close.index)
    g_open, g_close = g_open.loc[both], g_close.loc[both]
    ru2 = us_rate(pd.DatetimeIndex(both.tz_convert("UTC").normalize()))
    on1 = []
    for k in range(1, len(both)):
        d0, d1 = both[k - 1], both[k]
        if (d1 - d0).days > 4:
            continue
        nts = (d1 - d0).days
        pts = (g_open.iloc[k] - g_close.iloc[k - 1]) * US30_PT
        fin = -(ru2.iloc[k] + US30_FIN) / 100 * g_close.iloc[k - 1] * US30_PT * nts / 365
        on1.append((d1, pts, fin, (g_close.iloc[k] - g_open.iloc[k]) * US30_PT, (g_close.iloc[k] - g_close.iloc[k - 1]) * US30_PT))
    o = pd.DataFrame(on1, columns=["d", "pts", "fin", "day", "hold"]).set_index("d")
    o_net = o.pts + o.fin - US30_RT
    s3, e3 = o.index[0], o.index[-1] + pd.Timedelta(days=1)
    b3 = C.fold_bounds((s3, e3), 3)
    f3 = lambda x: [round(float(x.loc[a:b_].sum()), 0) for a, b_ in b3]
    out["U2_overnight_US30_1m"] = dict(
        period=[str(s3), str(e3)], n=int(len(o)), net=float(o_net.sum()), folds=f3(o_net),
        net_2x=float((o.pts + o.fin - 2 * US30_RT).sum()), gross_pts=float(o.pts.sum()),
        financing=float(o.fin.sum()), costs=float(US30_RT * len(o)),
        day_session_net=float((o.day - US30_RT).sum()), day_folds=f3(o.day - US30_RT),
        buy_hold_pts=float(o.hold.sum()), win_rate=float((o_net > 0).mean()),
        per_month=float(o_net.sum() / ((e3 - s3).days / 30.44)), max_dd=max_dd(o_net),
        overnight_t=float(o.pts.mean() / o.pts.std() * math.sqrt(len(o))))
    print("U2 1m:", out["U2_overnight_US30_1m"], flush=True)
    C.record_to_lab("us30_overnight", "U2_long_16to0930_1m", "US30", "1m", {"pt_value": US30_PT},
                    dict(n=len(o), net=float(o_net.sum()), wr=float((o_net > 0).mean()), folds=f3(o_net)),
                    (s3, e3), source="tests/h_fx_edges.py", baseline_net=float(o.hold.sum()),
                    notes="US30 TradeLocker 1m; $1/pt, costs, financing ASSUMED")

    # ORB
    FOLD_START, FOLD_END = s3, e3
    O_, H_, L_, C_ = (b[x].values for x in ("open", "high", "low", "close"))
    T_ = b.index
    day_first = {}
    for d, idx in pd.Series(np.arange(len(b)), index=et_day).groupby(level=0):
        day_first[d] = idx.values

    def orb(g, s, e, mult=1.0):
        rng_m, ex = g["range_min"], g["exit"]
        rows = []
        for d, ix in day_first.items():
            if d < s or d >= e:
                continue
            mm = mins[ix]
            r_ix = ix[(mm >= 570) & (mm < 570 + rng_m)]
            t_ix = ix[(mm >= 570 + rng_m) & (mm < 955)]
            if len(r_ix) < rng_m * 0.8 or len(t_ix) < 30:
                continue
            hi, lo = H_[r_ix].max(), L_[r_ix].min()
            w = hi - lo
            if w <= 0:
                continue
            for n_, i in enumerate(t_ix):
                up, dn = H_[i] >= hi, L_[i] <= lo
                if up and dn:
                    rows.append(dict(entry_time=T_[i].tz_convert("UTC"), exit_time=T_[i].tz_convert("UTC") + pd.Timedelta(minutes=1),
                                     side=1.0, entry_px=max(O_[i], hi), exit_px=lo, qty=1.0, multiplier=US30_PT,
                                     notional_usd=hi * US30_PT, fee_usd=US30_RT * mult, instrument="US30",
                                     sl_dist=max(O_[i], hi) - lo, tp_dist=w, mae_r=1.0, mfe_r=0.0))
                    break
                if up or dn:
                    sd = 1 if up else -1
                    en = max(O_[i], hi) if up else min(O_[i], lo)
                    sl = lo if up else hi
                    tp = en + sd * w if ex == "tp1" else en + sd * 1e9
                    mae = mfe = 0.0
                    xp, xi = C_[t_ix[-1]], t_ix[-1]
                    for j in t_ix[n_:]:
                        adv = (en - L_[j]) if sd > 0 else (H_[j] - en)
                        fav = (H_[j] - en) if sd > 0 else (en - L_[j])
                        if (L_[j] <= sl) if sd > 0 else (H_[j] >= sl):
                            xp, xi = sl, j
                            if j > i and ((sd > 0 and O_[j] < sl) or (sd < 0 and O_[j] > sl)):
                                xp = O_[j]
                            mae = max(mae, adv)
                            break
                        mae, mfe = max(mae, adv), max(mfe, fav)
                        if j > i and ((H_[j] >= tp) if sd > 0 else (L_[j] <= tp)):
                            xp, xi = tp, j
                            break
                    sld = abs(en - sl)
                    rows.append(dict(entry_time=T_[i].tz_convert("UTC"), exit_time=T_[xi].tz_convert("UTC") + pd.Timedelta(minutes=1),
                                     side=float(sd), entry_px=en, exit_px=xp, qty=1.0, multiplier=US30_PT,
                                     notional_usd=en * US30_PT, fee_usd=US30_RT * mult, instrument="US30",
                                     sl_dist=sld, tp_dist=w, mae_r=mae / sld if sld else 0, mfe_r=mfe / sld if sld else 0))
                    break
        return pd.DataFrame(rows)

    grid = [dict(range_min=m_, exit=x_) for m_ in (15, 30) for x_ in ("tp1", "eod")]
    tab, full = {}, {}
    for g in grid:
        k = json.dumps(g, sort_keys=True)
        t = orb(g, s3, e3)
        full[k] = t
        tab[k] = C.evaluate(t, 3, s3, e3)
        print(f"  ORB {k} n={tab[k]['n']} net={tab[k]['net']:,.0f} folds={[round(x) for x in tab[k]['folds']]}", flush=True)
        C.record_to_lab("us30_orb", k, "US30", "1m", g, tab[k], (s3, e3), source="tests/h_fx_edges.py",
                        notes="$1/pt + $8/lot RT ASSUMED")
    best = max(tab, key=lambda k: tab[k]["folds"][0])
    t = full[best]
    oos = t[t.entry_time >= b3[1][0]]
    r = C.evaluate(oos, 3, s3, e3)
    pnl = C.add_pnl(oos)
    # control: same entry minutes, random side, same distances
    ctrl = []
    gross_long = None
    for _ in range(N_CTRL):
        sg = RNG.choice([-1.0, 1.0], size=len(oos))
        # approximate: flipping side of a symmetric bracket maps win<->loss only if tp==sl; use realised path sign
        ctrl.append(float((sg * pnl.side * (pnl.exit_px - pnl.entry_px) * US30_PT - pnl.fee_usd).sum()))
    ctrl = np.array(ctrl)
    wins = pnl[pnl.net_pnl > 0]
    t2 = orb(json.loads(best), b3[1][0], e3, 2.0)
    out["U3_orb"] = dict(grid={k: {kk: v[kk] for kk in ("n", "net", "folds", "wr", "pf")} for k, v in tab.items()},
                         pick=json.loads(best), fold1=tab[best]["folds"][0], oos=r, oos_net=r["net"], oos_folds=r["folds"][1:],
                         oos_net_2x_cost=float(C.evaluate(t2, 1)["net"]) if len(t2) else 0.0,
                         ctrl_pct=float((ctrl < r["net"]).mean() * 100),
                         trades_per_month=float(len(oos) / ((e3 - b3[1][0]).days / 30.44)),
                         avg_hold_min=float(pnl.hold_min.mean()),
                         winners_underwater_any=float((wins.mae_r > 0).mean()) if len(wins) else 0.0,
                         winners_underwater_half_r=float((wins.mae_r >= 0.5).mean()) if len(wins) else 0.0,
                         per_month=float(r["net"] / ((e3 - b3[1][0]).days / 30.44)))
    print(f"PICK ORB {best} OOS={r['net']:,.0f} folds={[round(x) for x in r['folds']]} ctrl%={out['U3_orb']['ctrl_pct']:.0f}", flush=True)
    return out


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    out = json.load(open(OUT)) if OUT.exists() else {}
    if what in ("daily", "all"):
        out["daily"] = run_daily()
        json.dump(out, open(OUT, "w"), indent=1, default=str)
    if what in ("intraday", "all"):
        out["intraday"] = run_intraday()
        json.dump(out, open(OUT, "w"), indent=1, default=str)
    if what in ("us30", "all"):
        out["us30"] = run_us30()
        json.dump(out, open(OUT, "w"), indent=1, default=str)
