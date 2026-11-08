"""Fetch FX + US30 bars for h_fx_edges (yfinance). Writes data/fx/*.parquet."""
import time, json
from pathlib import Path
import pandas as pd, yfinance as yf
OUT = Path(__file__).resolve().parent.parent / "data" / "fx"
OUT.mkdir(exist_ok=True)
PAIRS = ["EURUSD","GBPUSD","USDJPY","USDCHF","AUDUSD","USDCAD","NZDUSD",
         "GBPJPY","NZDJPY","AUDJPY","EURJPY","CADJPY","CHFJPY","EURGBP"]
EXTRA = {"DJI": "^DJI", "YM": "YM=F"}
def norm(df):
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.rename(columns=str.lower)[["open","high","low","close"]].dropna()
    df.index = pd.to_datetime(df.index, utc=True); df.index.name = "time"
    return df[(df["high"] >= df["low"]) & (df["close"] > 0)]
log = {}
jobs = [(p, p + "=X") for p in PAIRS] + list(EXTRA.items())
for name, tk in jobs:
    for iv, per in (("1d", "max"), ("1h", "730d")):
        for attempt in range(3):
            try:
                df = norm(yf.download(tk, period=per, interval=iv, progress=False, auto_adjust=False))
                break
            except Exception as e:
                df = None; time.sleep(3)
        if df is None or df.empty:
            log[f"{name}_{iv}"] = "EMPTY"; continue
        df.to_parquet(OUT / f"{name}_{iv}.parquet")
        log[f"{name}_{iv}"] = f"{len(df)} rows {df.index[0]} -> {df.index[-1]}"
        print(name, iv, log[f"{name}_{iv}"], flush=True)
json.dump(log, open(OUT / "_fetch_log.json", "w"), indent=1)
