"""Diagnostic: reproduce Tokyo's original A+ timing (Yahoo daily bar incl. its
high/low + entry at its 'close', forward path from hourly bars after the daily
label time) vs the strict timing used in h_fx_edges. No costs, overlapping
setups allowed, score>=75, hold-bounce (+0.5 ATR / -2.5 ATR / 72h)."""
import sys, json
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
from h_fx_edges import PAIRS, FX, rsi_series

def run(p):
    d = pd.read_parquet(FX / f"{p}_1d.parquet").astype(float).loc["2024-01-01":"2026-09-20"]
    h = pd.read_parquet(FX / f"{p}_1h.parquet").astype(float)
    c = d.close; drsi = rsi_series(c)
    tr = pd.concat([d.high - d.low, (d.high - c.shift()).abs(), (d.low - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()
    hi20, lo20 = d.high.rolling(20).max(), d.low.rolling(20).min()
    pos = (c - lo20) / (hi20 - lo20)
    h4 = h.resample("4h", origin="epoch").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    r4 = rsi_series(h4.close)
    res = []
    for k in range(40, len(d) - 1):
        t = d.index[k]
        j = h4.index.searchsorted(t, side="right") - 1          # original: 4H bars with start <= daily label
        if j < 20 or np.isnan(atr.iloc[k]):
            continue
        ps, dr, a, px = pos.iloc[k], drsi.iloc[k], atr.iloc[k], c.iloc[k]
        for side, cond in ((1, ps <= 0.30 and dr < 45), (-1, ps >= 0.70 and dr > 55)):
            if not cond:
                continue
            if side > 0:
                sc = (0.30 - ps) / 0.30 * 35 + max(0, 45 - dr) / 45 * 25 + (20 if r4.iloc[j] > r4.iloc[j-1] else 0) + (20 if h4.close.iloc[j] > h4.open.iloc[j] else 0)
            else:
                sc = (ps - 0.70) / 0.30 * 35 + max(0, dr - 55) / 45 * 25 + (20 if r4.iloc[j] < r4.iloc[j-1] else 0) + (20 if h4.close.iloc[j] < h4.open.iloc[j] else 0)
            if sc < 75:
                continue
            fwd = h[h.index > t].iloc[:72]
            out = None
            for _, b in fwd.iterrows():
                adv = (px - b.low) if side > 0 else (b.high - px)
                fav = (b.high - px) if side > 0 else (px - b.low)
                if adv >= 2.5 * a:
                    out = -2.5; break
                if fav >= 0.5 * a:
                    out = 0.5; break
            if out is None and len(fwd):
                out = side * (fwd.close.iloc[-1] - px) / a
            if out is not None:
                res.append(out)
    return res

allr = []
for p in PAIRS:
    allr += run(p)
r = np.array(allr)
print(json.dumps(dict(n=len(r), win=float((r > 0).mean()), exp_R=float(r.mean()))))
