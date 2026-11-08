"""Overnight drift on GOLD ALONE, plus a beta control and position-scaling views.

Strategy (frozen, from h_overnight_drift walk-forward): long 16:00 ET -> 09:00 ET
next session, market at the bar open of the scheduled time. No stop.

Sources (each reported separately):
  MGC_1h   yfinance MGC=F 1h, 2024-04-05 -> 2026-08-27. Skeptic-corrected legs:
           roll-adjusted (verify_overnight_drift_execution) + 1 extra tick/side.
  XAU_1m   TradeLocker XAUUSD 1m (UTC clock), 2025-09-01 -> 2026-07-16. Sized 10 oz
           (= 1 MGC, $10/pt). Cost 1.2 bp/side of notional (tl-bot spread). CFD
           overnight financing is UNKNOWN for this account; shown at 0 and at an
           ASSUMED 6%/yr of notional per calendar day held.
  GLD_1d   GLD daily 2016-08-29 -> 2026-08-27, close(16:00) -> next open(09:30).
           Long history incl. the 2016-18 / 2020-22 down/flat years. Converted to
           1-MGC-equivalent USD with notional = 10 x GC=F daily close. Cost
           1 bp/side.

Beta control: overnight vs day session (09:00->16:00 / GLD open->close), vs a
24h hold over the same dates, and vs the overnight share expected pro-rata to
trading hours (futures/XAU 16 of 23 h; GLD 17.5 of 24 h). Excess per date =
on - s * (on + day); t-test mean excess = 0.
Regime: gold above/below its 50-day MA, using only the prior day's close.

Scaling (separate, after the fixed-size view): 1 contract; fixed-fractional
0.5/1/2% where "risk per contract" = 2 x the stdev of the previous 20 nights'
overnight $ move (a sizing unit - NO stop is placed); vol targeting 0.5/1%
of equity per night. Whole MGC contracts, or 0.1-contract steps (a 0.01-lot
XAUUSD CFD = 1 oz). Margin cap: contracts <= equity / (5.5% of notional).
Monte Carlo: stationary block bootstrap of nights (block 20), 1000 paths.
"""
from __future__ import annotations
import sys, json, math
from pathlib import Path
import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path('/Users/molt_bot/latpfn-trading/research/edge_hunt')
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / 'tests'))
import common as C
import h_overnight_drift as H
import verify_overnight_drift_execution as V

V.SP = Path('/private/tmp/claude-501/-Users-molt-bot/c2b5a353-cd35-4dae-8601-e9c6093cbb44/scratchpad')
ET = 'America/New_York'
STRAT = 'overnight_drift_gold'
OUT_MD = Path(__file__).with_suffix('.md')
XAU_CSV = Path.home() / 'tokyo-strategy/data/1min_multi/XAUUSD_TL_1m_2025-09-01_2026-07-17.csv'
XAU_BP_SIDE = 1.2e-4
XAU_SWAP_ASSUMED = 0.06          # per year of notional, per calendar day held - ASSUMPTION
GLD_BP_SIDE = 1.0e-4
MGC_MULT = 10.0
MGC_FEE = C.cme_fee('MGC', 1) + 2 * V.TICK_USD['MGC']   # corrected: +1 tick/side
MARGIN_FRAC = 0.055
RNG = np.random.default_rng(23)
LAB = []                          # (variant, instrument, tf, params, result, period, notes, baseline, trust)


# ------------------------------------------------------------------ helpers
def cust_trade(et, xt, ep, xp, qty, fee, inst, mult=1.0):
    return dict(entry_time=et, exit_time=xt, side=1, entry_px=ep, exit_px=xp, qty=qty,
                notional_usd=qty * ep * mult, fee_usd=fee, instrument=inst, multiplier=mult)


def per_year(t):
    t = C.add_pnl(t)
    return t.groupby(t.entry_time.dt.tz_convert(ET).dt.year)['net_pnl'].sum().round(0).to_dict()


def fmt(r):
    return (f"n={r['n']} net={r['net']:,.0f} pf={r['pf']:.2f} wr={r['wr']:.2f} "
            f"maxDD={r['max_dd']:,.0f} folds={[round(f) for f in r['folds']]}")


def gold_daily_close():
    g = C.yf_bars('GC=F', '1d')['close'].dropna()
    g.index = g.index.date          # yfinance daily bars are stamped 00:00 UTC of the trading date
    return g


def ma50_regime(dates, closes: pd.Series):
    """True = prior day's close above its 50-day MA (both known before entry)."""
    ma = closes.rolling(50).mean()
    up = (closes > ma).shift(1)          # value usable on the NEXT date
    s = pd.Series(up.values, index=list(closes.index))
    out = []
    keys = np.array(list(closes.index))
    for d in dates:
        # last close date strictly before d (= the entry date of the overnight leg ending on d);
        # shift(1) then uses the close BEFORE that, so nothing settles after the 16:00 entry
        j = np.searchsorted(keys, d, side='left') - 1
        out.append(s.iloc[j] if j >= 0 else np.nan)
    return np.array(out, dtype=object)


# ------------------------------------------------------------------ sources
def src_mgc():
    etf = V.etf_daily()
    L = V.overnight_legs_with_proxy('MGC', etf)
    on = V.build_trades('MGC', L, extra_ticks_per_side=1, roll_adjust=True)
    on_2x = on.copy(); on_2x['fee_usd'] *= 2
    D = H.legs('MGC', 9, 16, False)
    day = pd.DataFrame([C.cme_trade(r.entry_time, r.exit_time, 1, r.entry_px, r.exit_px, 1, 'MGC') for r in D.itertuples()])
    day['fee_usd'] += 2 * V.TICK_USD['MGC']
    on_d = pd.to_datetime(on.exit_time).dt.tz_convert(ET).dt.date.values   # overnight leg ending on date d
    return dict(name='MGC_1h', on=on, on_2x=on_2x, day=day,
                on_date=on_d, day_date=D.entry_date.values, share=16 / 23,
                span=(H.bars('MGC').index.min(), H.bars('MGC').index.max()), tf='1h')


def src_xau():
    d = pd.read_csv(XAU_CSV, parse_dates=['datetime']).set_index('datetime').sort_index()
    d.index = d.index.tz_localize('UTC')
    d = d[~d.index.duplicated()]
    et = d.index.tz_convert(ET)
    d['date'] = et.date; d['hm'] = et.hour * 60 + et.minute
    rows_on, rows_day = [], []
    dates = sorted(set(d['date']))
    first_at = {}
    for tgt in (16 * 60, 9 * 60):
        s = d[(d.hm >= tgt) & (d.hm < tgt + 5)]          # first print within 5 min of the scheduled time
        first_at[tgt] = s.groupby('date').head(1)
    ent = first_at[16 * 60]; ex = first_at[9 * 60]
    ex_by_date = {r.date: (t, r.open) for t, r in ex.iterrows()}
    ent_by_date = {r.date: (t, r.open) for t, r in ent.iterrows()}
    ex_dates = sorted(ex_by_date)
    for t, r in ent.iterrows():
        j = np.searchsorted(ex_dates, r.date, side='right')
        if j >= len(ex_dates):
            continue
        xd = ex_dates[j]; xt, xp = ex_by_date[xd]
        if (xt - t) > pd.Timedelta(days=4):
            continue
        n = 10 * r.open
        fee = XAU_BP_SIDE * (n + 10 * xp)
        days = (xd - r.date).days
        rows_on.append(dict(cust_trade(t, xt, r.open, xp, 10, fee, 'XAUUSD'), swap=XAU_SWAP_ASSUMED / 365 * n * days, d_out=xd))
    for dd in dates:
        if dd in ex_by_date and dd in ent_by_date:
            (t0, p0), (t1, p1) = ex_by_date[dd], ent_by_date[dd]
            if t1 > t0:
                rows_day.append(dict(cust_trade(t0, t1, p0, p1, 10, XAU_BP_SIDE * 10 * (p0 + p1), 'XAUUSD'), d=dd))
    on = pd.DataFrame(rows_on); day = pd.DataFrame(rows_day)
    on_2x = on.copy(); on_2x['fee_usd'] *= 2
    on_sw = on.copy(); on_sw['fee_usd'] += on_sw['swap']
    return dict(name='XAU_1m', on=on, on_2x=on_2x, on_swap=on_sw, day=day,
                on_date=on.d_out.values, day_date=day.d.values, share=16 / 23,
                span=(d.index.min(), d.index.max()), tf='1m')


def src_gld():
    g = C.yf_bars('GLD', '1d').dropna(subset=['open', 'close'])
    gc = gold_daily_close()
    dts = [ts.date() for ts in g.index]
    rows_on, rows_day = [], []
    for i in range(len(g) - 1):
        d0, d1 = dts[i], dts[i + 1]
        c0, o1 = g['close'].iloc[i], g['open'].iloc[i + 1]
        o0 = g['open'].iloc[i]
        px = gc.get(d0, np.nan)
        if not np.isfinite(px):
            continue
        # express as 1 MGC-equivalent: notional 10*px, pnl = ret * notional
        t_in = pd.Timestamp(d0).tz_localize(ET) + pd.Timedelta(hours=16)
        t_out = pd.Timestamp(d1).tz_localize(ET) + pd.Timedelta(hours=9, minutes=30)
        qty = 10 * px / c0                              # GLD shares worth 10 oz of gold
        rows_on.append(dict(cust_trade(t_in.tz_convert('UTC'), t_out.tz_convert('UTC'), c0, o1, qty,
                                       GLD_BP_SIDE * qty * (c0 + o1), 'GLD'), d_out=d1))
        t_o = pd.Timestamp(d0).tz_localize(ET) + pd.Timedelta(hours=9, minutes=30)
        rows_day.append(dict(cust_trade(t_o.tz_convert('UTC'), t_in.tz_convert('UTC'), o0, c0, qty,
                                        GLD_BP_SIDE * qty * (o0 + c0), 'GLD'), d=d0))
    on = pd.DataFrame(rows_on); day = pd.DataFrame(rows_day)
    on_2x = on.copy(); on_2x['fee_usd'] *= 2
    on_mgc = on.copy(); on_mgc['fee_usd'] = MGC_FEE      # same nights, charged the corrected MGC round trip
    return dict(name='GLD_1d', on=on, on_2x=on_2x, on_mgccost=on_mgc, day=day,
                on_date=on.d_out.values, day_date=day.d.values, share=17.5 / 24,
                span=(g.index.min(), g.index.max()), tf='1d')


# ------------------------------------------------------------------ analysis
def beta_block(S, lines):
    on = C.add_pnl(S['on']); day = C.add_pnl(S['day'])
    a = pd.Series(on.gross_pnl.values, index=S['on_date']).groupby(level=0).sum()
    b = pd.Series(day.gross_pnl.values, index=S['day_date']).groupby(level=0).sum()
    pair = pd.concat([a.rename('on'), b.rename('day')], axis=1).dropna()
    s = S['share']
    hold = pair.on + pair.day
    excess = pair.on - s * hold
    t, p = stats.ttest_1samp(excess, 0)
    beta = float(np.polyfit(hold, pair.on, 1)[0]) if len(pair) > 5 else np.nan
    out = dict(pairs=len(pair), on=float(pair.on.sum()), day=float(pair.day.sum()), hold=float(hold.sum()),
               expected_on=float(s * hold.sum()), excess=float(excess.sum()), t=float(t), p=float(p),
               on_share=float(pair.on.sum() / hold.sum()) if hold.sum() else np.nan, beta=beta)
    lines += [f"- **{S['name']}** ({len(pair)} paired dates, gross $ per 1-MGC-equivalent): overnight {out['on']:,.0f}, "
              f"day {out['day']:,.0f}, 24h hold {out['hold']:,.0f}. Pro-rata share {s:.2f} -> expected overnight "
              f"{out['expected_on']:,.0f}; actual share {out['on_share']:.2f}. **Excess over beta {out['excess']:,.0f}** "
              f"(t={t:.2f}, p={p:.3f})."]
    # regime split + per-year excess
    gc = gold_daily_close()
    up = ma50_regime(list(pair.index), gc)
    pr = pair.assign(up=up, ex=excess.values, yr=[d.year for d in pair.index])
    for lab, m in (('gold > 50DMA', pr.up == True), ('gold < 50DMA', pr.up == False)):
        sub = pr[m]
        if len(sub) > 5:
            tt, pp = stats.ttest_1samp(sub.ex, 0)
            lines.append(f"  - {lab}: {len(sub)} dates, overnight {sub.on.sum():,.0f}, day {sub.day.sum():,.0f}, "
                         f"excess {sub.ex.sum():,.0f} (t={tt:.2f})")
            out[f'regime_{"up" if "> " in lab else "dn"}'] = dict(n=len(sub), on=float(sub.on.sum()), day=float(sub.day.sum()),
                                                                   excess=float(sub.ex.sum()), t=float(tt))
    yy = pr.groupby('yr').agg(on=('on', 'sum'), day=('day', 'sum'), ex=('ex', 'sum'))
    lines.append("  - per year (overnight / day / excess): " +
                 "; ".join(f"{y}: {r.on:,.0f} / {r.day:,.0f} / {r.ex:,.0f}" for y, r in yy.iterrows()))
    out['years'] = {int(y): dict(on=float(r.on), day=float(r.day), ex=float(r.ex)) for y, r in yy.iterrows()}
    return out, excess


def fixed_block(S, lines):
    span = S['span']
    res = {}
    lines += [f"### {S['name']}  ({span[0]:%Y-%m-%d} -> {span[1]:%Y-%m-%d})", ""]
    for key, lab in (('on', 'overnight long, base cost'), ('on_2x', 'overnight long, 2x cost'),
                     ('on_swap', 'overnight long, base cost + ASSUMED 6%/yr CFD financing'),
                     ('on_mgccost', 'overnight long, charged the corrected MGC cost ($%.2f/night)' % MGC_FEE), ('day', 'day session long 09:00->16:00 (control)')):
        if key not in S:
            continue
        t = S[key][C.REQUIRED_TRADE_COLS + ['multiplier']]
        r = C.evaluate(t, 3, start=span[0], end=span[1])
        res[key] = r
        lines.append(f"- {lab}: {fmt(r)}; per-year {per_year(t)}")
    lines.append("")
    return res


# ------------------------------------------------------------------ scaling
def night_table(S):
    """Per-night gross $ per 1 contract (MGC-equivalent), fee per contract, entry price,
    and prior-20-night stdev of the $ move (strictly before this night)."""
    t = C.add_pnl(S['on'][C.REQUIRED_TRADE_COLS + ['multiplier']])
    # every source's trade is already exactly 1 MGC-equivalent (10 oz of gold notional)
    q = pd.Series(1.0, index=t.index)
    g = t.gross_pnl / q
    px = t.notional_usd / t.qty / t.multiplier       # gold price per oz at entry
    if S['name'] == 'GLD_1d':
        px = t.notional_usd / 10.0
    # sizing view assumes execution as MGC (corrected fee); XAU keeps its own spread cost
    fee = (t.fee_usd / q) if S['name'] == 'XAU_1m' else pd.Series(MGC_FEE, index=t.index)
    sd = g.shift(1).rolling(20).std()
    df = pd.DataFrame(dict(time=t.entry_time, g=g.values, fee=np.asarray(fee, float),
                           px=np.asarray(px, float), sd=sd.values)).dropna().reset_index(drop=True)
    return df


POLICIES = ['fixed_1ct', 'ff_0.5', 'ff_1', 'ff_2', 'vt_3', 'vt_5']   # note ff_X == vt_(X/2) by construction


def size(policy, eq, sd, px, step):
    if policy == 'fixed_1ct':
        n = 1.0
    elif policy.startswith('ff_'):
        f = float(policy[3:]) / 100
        n = f * eq / (2 * sd)
    else:
        x = float(policy[3:]) / 100
        n = x * eq / sd
    n = math.floor(n / step + 1e-9) * step
    cap = math.floor(eq / (MARGIN_FRAC * 10 * px) / step + 1e-9) * step
    return max(0.0, min(n, cap))


def simulate(df, policy, eq0, step):
    eq = eq0; path = [eq]; nights = []
    for g, fee, px, sd in zip(df.g.values, df.fee.values, df.px.values, df.sd.values):
        n = size(policy, eq, sd, px, step)
        pnl = n * (g - fee)
        eq = eq + pnl
        path.append(eq); nights.append(pnl)
        if eq <= 0:
            break
    path = np.array(path); nights = np.array(nights)
    peak = np.maximum.accumulate(path)
    dd = float(((peak - path) / peak).max())
    streak = cur = 0
    for x in nights:
        cur = cur + 1 if x < 0 else 0
        streak = max(streak, cur)
    return dict(final=float(path[-1]), maxdd=dd, worst=float(nights.min()) if len(nights) else 0.0,
                worst_pct=float((nights / path[:-1][:len(nights)]).min()) if len(nights) else 0.0,
                streak=int(streak), traded=int((nights != 0).sum()), nights=nights, path=path)


def block_boot(df, n_paths=1000, block=20):
    n = len(df)
    for _ in range(n_paths):
        idx = []
        while len(idx) < n:
            s = RNG.integers(0, n)
            L = RNG.geometric(1 / block)
            idx.extend([(s + k) % n for k in range(L)])
        yield df.iloc[idx[:n]].reset_index(drop=True)


def scaling_block(S, lines, eqs=(10_000, 100_000)):
    df = night_table(S)
    yrs = (df.time.iloc[-1] - df.time.iloc[0]).days / 365.25
    boots = list(block_boot(df))
    out = {}
    lines += [f"### Scaling on {S['name']} ({len(df)} nights, {yrs:.1f} years; first 20 nights used only to seed the vol estimate)", "",
              "| start | granularity | policy | final | CAGR | maxDD | worst night | longest losing streak | nights traded | MC p5 / p50 / p95 final | P(DD>=30%) | P(DD>=50%) |",
              "|---:|---|---|---:|---:|---:|---:|---:|---:|---|---:|---:|"]
    for eq0 in eqs:
        for step, glab in ((1.0, 'whole MGC'), (0.1, '0.1 ct (1 oz CFD)')):
            for pol in POLICIES:
                if pol == 'fixed_1ct' and step != 1.0:
                    continue
                r = simulate(df, pol, eq0, step)
                cagr = (r['final'] / eq0) ** (1 / yrs) - 1 if r['final'] > 0 else -1.0
                mc = [simulate(b, pol, eq0, step) for b in boots]
                fin = np.array([m['final'] for m in mc]); dds = np.array([m['maxdd'] for m in mc])
                p5, p50, p95 = np.percentile(fin, [5, 50, 95])
                row = dict(final=r['final'], cagr=cagr, maxdd=r['maxdd'], worst=r['worst'], worst_pct=r['worst_pct'],
                           streak=r['streak'], traded=r['traded'], p5=p5, p50=p50, p95=p95,
                           p_dd30=float((dds >= .30).mean()), p_dd50=float((dds >= .50).mean()))
                out[(eq0, glab, pol)] = row
                lines.append(f"| ${eq0:,} | {glab} | {pol} | ${r['final']:,.0f} | {cagr*100:.1f}% | {r['maxdd']*100:.1f}% | "
                             f"${r['worst']:,.0f} ({r['worst_pct']*100:.1f}%) | {r['streak']} | {r['traded']}/{len(df)} | "
                             f"${p5:,.0f} / ${p50:,.0f} / ${p95:,.0f} | {row['p_dd30']*100:.0f}% | {row['p_dd50']*100:.0f}% |")
                nn = r['nights']
                LAB.append((f"scale_{S['name']}_{pol}_{int(eq0/1000)}k_{'whole' if step == 1 else 'tenth'}", 'MGC', S['tf'],
                            dict(policy=pol, start_equity=eq0, step=step, margin_frac=MARGIN_FRAC, source=S['name']),
                            dict(C.empty_result(), n=int(r['traded']), net=float(r['final'] - eq0),
                                 wr=float((nn[nn != 0] > 0).mean()) if (nn != 0).any() else 0.0, max_dd=r['maxdd'] * eq0),
                            (df.time.iloc[0], df.time.iloc[-1]),
                            f"scaling sim; CAGR={cagr:.4f} maxDD%={r['maxdd']:.4f} MC p5/p50/p95={p5:.0f}/{p50:.0f}/{p95:.0f} "
                            f"P(DD>=30%)={row['p_dd30']:.3f} P(DD>=50%)={row['p_dd50']:.3f}", None, 'estimated'))
    # smallest account that can hold 1 whole contract under each policy (median sd, median px)
    sd, px = df.sd.median(), df.px.median()
    lines += ["", f"Smallest account to size >= 1 whole MGC at median conditions (overnight $ stdev {sd:,.0f}/ct, gold ${px:,.0f}): " +
              ", ".join(f"{p}: ${(2 * sd / (float(p[3:]) / 100)) if p.startswith('ff') else (sd / (float(p[3:]) / 100)):,.0f}"
                        for p in POLICIES[1:]) +
              f"; margin alone (~{MARGIN_FRAC*100:.1f}% of notional) needs ${MARGIN_FRAC * 10 * px:,.0f}.", ""]
    return out, df


# ------------------------------------------------------------------ main
def main():
    lines = ["# Overnight drift on gold alone, with a beta control and scaling", "",
             "Rule (frozen from h_overnight_drift): long gold 16:00 ET -> 09:00 ET next session, market at the scheduled bar open, no stop. "
             "Sizes are 1 MGC-equivalent (10 oz, $10 per $1 of gold). See the script docstring for sources and costs.", ""]
    S_list = [src_mgc(), src_xau(), src_gld()]
    fixed = {}
    lines += ["## 1. Fixed size, net of costs", ""]
    for S in S_list:
        fixed[S['name']] = fixed_block(S, lines)
    lines += ["## 2. Beta control", ""]
    beta = {}
    for S in S_list:
        beta[S['name']], _ = beta_block(S, lines)
    lines.append("")
    # lab: fixed-size variants with the beta expectation as the baseline
    for S in S_list:
        exp_on = beta[S['name']]['expected_on']
        for key, r in fixed[S['name']].items():
            trust = 'estimated' if key == 'on_swap' else 'measured'
            base = None if key == 'day' else exp_on - (r['fees'] if key != 'day' else 0)
            LAB.append((f"{S['name']}_{key}", 'MGC' if S['name'] == 'MGC_1h' else ('XAUUSD' if S['name'] == 'XAU_1m' else 'GLD'),
                        S['tf'], dict(entry='16:00ET', exit='09:00ET' if S['name'] != 'GLD_1d' else '09:30ET', leg=key, size='1 MGC-equiv'),
                        r, S['span'],
                        f"baseline_net = hours-pro-rata share of the 24h hold, net of this variant's fees (beta expectation); "
                        f"excess t={beta[S['name']]['t']:.2f}", base, trust))
    lines += ["## 3. Scaling", "",
              "Risk unit for fixed-fractional = 2 x stdev of the previous 20 nights' overnight $ move per contract. "
              "It only sets size; no stop is placed, so a night can lose more than the 'risk'. "
              "Vol targeting sizes so one night's expected stdev = X% of equity. Contracts are capped by margin "
              f"(~{MARGIN_FRAC*100:.1f}% of notional per contract). Monte Carlo = 1000 stationary block-bootstrap paths (mean block 20 nights) of the same nights.", ""]
    scal = {}
    for S in (S_list[0], S_list[2]):
        scal[S['name']], _ = scaling_block(S, lines)
    for v, inst, tf, p, r, per, notes, base, trust in LAB:
        C.record_to_lab(STRAT, v, inst, tf, p, r, period=per, source=__file__, notes=notes, baseline_net=base, trust=trust)
    OUT_MD.write_text("\n".join(lines) + "\n")
    js = dict(fixed={k: {kk: {x: y for x, y in vv.items()} for kk, vv in v.items()} for k, v in fixed.items()},
              beta=beta, scaling={k: {f"{a}|{b}|{c}": vv for (a, b, c), vv in v.items()} for k, v in scal.items()})
    Path(str(OUT_MD).replace('.md', '.json')).write_text(json.dumps(js, default=float, indent=1))
    print("\n".join(lines))
    print(f"\nrecorded {len(LAB)} lab rows")


if __name__ == '__main__':
    main()
