import os
import httpx
import pandas as pd

CRYPTO_API_URL = os.getenv("CRYPTO_API_URL", "https://data-api.binance.vision").rstrip("/")


def crypto_klines(symbol: str, interval: str = "1h", limit: int = 240, start_time: int | None = None, end_time: int | None = None) -> pd.DataFrame:
    """Fetch Binance candles. Supports intraday replay with start/end timestamps."""
    params = {"symbol": symbol.upper(), "interval": interval, "limit": min(int(limit), 1000)}
    if start_time is not None: params["startTime"] = int(start_time)
    if end_time is not None: params["endTime"] = int(end_time)
    r = httpx.get(f"{CRYPTO_API_URL}/api/v3/klines", params=params, timeout=15)
    r.raise_for_status()
    rows = r.json()
    if not rows:
        raise ValueError(f"No crypto candles returned for {symbol}")
    cols = ["open_time", "open", "high", "low", "close", "volume", "close_time", "quote_volume", "trades", "taker_base", "taker_quote", "ignore"]
    df = pd.DataFrame(rows, columns=cols)
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def stock_daily(symbol: str, outputsize: str = "compact") -> pd.DataFrame:
    key = os.getenv("STOCK_API_KEY")
    if not key:
        raise RuntimeError("STOCK_API_KEY is not configured")
    r = httpx.get("https://www.alphavantage.co/query", params={"function": "TIME_SERIES_DAILY", "symbol": symbol.upper(), "outputsize": outputsize, "apikey": key}, timeout=20)
    r.raise_for_status()
    data = r.json()
    series = data.get("Time Series (Daily)")
    if not series:
        raise ValueError(data.get("Note") or data.get("Information") or data.get("Error Message") or f"No stock data for {symbol}")
    df = pd.DataFrame.from_dict(series, orient="index")
    df.index = pd.to_datetime(df.index)
    df = df.rename(columns={"1. open": "open", "2. high": "high", "3. low": "low", "4. close": "close", "5. volume": "volume"}).sort_index().reset_index(names="date")
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df
