"""Download/cache public Binance historical candles for AURELIS research.

Uses Binance's unauthenticated market-data API only. No trading credentials are
needed. Research data is cached locally and never used to place orders.
"""
from __future__ import annotations
import json, os, time
from pathlib import Path
from datetime import datetime, timezone, timedelta
import httpx
import pandas as pd

BASE = os.getenv("CRYPTO_API_URL", "https://data-api.binance.vision").rstrip("/")
CACHE_DIR = Path(os.getenv("AURELIS_HISTORY_DIR", "data/binance_history"))
DEFAULT_DAYS = int(os.getenv("AURELIS_HISTORY_DAYS", "180"))
LIMIT = 1000


def _normalize(rows):
    cols=["open_time","open","high","low","close","volume","close_time","quote_volume",
          "trades","taker_buy_base","taker_buy_quote","ignore"]
    df=pd.DataFrame(rows, columns=cols)
    if df.empty:
        return df
    for c in ["open","high","low","close","volume","quote_volume","taker_buy_base","taker_buy_quote"]:
        df[c]=pd.to_numeric(df[c], errors="coerce")
    df["trades"]=pd.to_numeric(df["trades"], errors="coerce")
    df["open_time"]=pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df["close_time"]=pd.to_datetime(df["close_time"], unit="ms", utc=True)
    return df.dropna(subset=["open_time","close"]).sort_values("open_time").drop_duplicates("open_time")


def fetch_klines(symbol, interval="4h", days=DEFAULT_DAYS, force=False):
    symbol=str(symbol).upper()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    safe=f"{symbol}_{interval}_{days}d.csv"
    path=CACHE_DIR/safe
    if path.exists() and not force:
        return pd.read_csv(path, parse_dates=["open_time","close_time"])

    end=datetime.now(timezone.utc)
    start=end-timedelta(days=days)
    start_ms=int(start.timestamp()*1000)
    end_ms=int(end.timestamp()*1000)
    rows=[]
    cursor=start_ms

    with httpx.Client(timeout=30) as client:
        while cursor < end_ms:
            r=client.get(f"{BASE}/api/v3/klines", params={
                "symbol":symbol,"interval":interval,"startTime":cursor,
                "endTime":end_ms,"limit":LIMIT
            })
            r.raise_for_status()
            batch=r.json()
            if not batch:
                break
            rows.extend(batch)
            nxt=int(batch[-1][0])+1
            if nxt <= cursor:
                break
            cursor=nxt
            if len(batch) < LIMIT:
                break
            time.sleep(0.05)

    df=_normalize(rows)
    if df.empty:
        raise RuntimeError(f"No Binance {interval} data returned for {symbol}")
    df.to_csv(path,index=False)
    return df


def load_symbols(symbols, interval="4h", days=DEFAULT_DAYS, force=False):
    return {s: fetch_klines(s, interval, days, force) for s in symbols}


if __name__=="__main__":
    symbols=[s.strip().upper() for s in os.getenv("AURELIS_HISTORY_SYMBOLS","BTCUSDT,ETHUSDT").split(",") if s.strip()]
    out={}
    for symbol in symbols:
        df=fetch_klines(symbol)
        out[symbol]={"rows":len(df),"start":str(df.open_time.min()),"end":str(df.open_time.max())}
    print(json.dumps(out,indent=2))
