"""Multi-timeframe paper-trade monitor.

5m candles are the primary execution-resolution feed. They cover the full
24-hour holding window within Binance's 1000-candle API limit and are aligned
with the GitHub Actions monitor cadence. 1h candles are also replayed for
higher-timeframe confirmation/diagnostics. The ledger remains paper-only.
"""
import asyncio
import sqlite3
from datetime import datetime, timezone, timedelta
from .journal import DB, init_db
from .paper_trader import mark_candle, expire_old_trades, paper_summary
from .market_data import crypto_klines


PRIMARY_INTERVAL="5m"
HTF_INTERVAL="1h"
ATR_PERIOD=14
# 5m is the execution clock; 1h is confirmation/diagnostics. This keeps the
# monitor materially more precise than 1m without treating noisy 1m spikes as fills.


def _open_symbols():
    init_db()
    with sqlite3.connect(DB) as con:
        return [r[0] for r in con.execute(
            "SELECT DISTINCT symbol FROM paper_trades WHERE status='OPEN'"
        ).fetchall()]


def _start_ms(symbol):
    with sqlite3.connect(DB) as con:
        rows=con.execute(
            "SELECT opened_at,last_checked_at FROM paper_trades "
            "WHERE status='OPEN' AND symbol=?",
            (symbol,),
        ).fetchall()

    values=[]
    for opened,last in rows:
        value=last or opened
        if not value:
            continue
        try:
            values.append(int(datetime.fromisoformat(
                value.replace("Z","+00:00")
            ).timestamp()*1000))
        except ValueError:
            continue

    if not values:
        return None

    # Re-fetch one primary candle before the last checkpoint so a workflow
    # starting close to a candle boundary cannot permanently skip a candle.
    return max(0,min(values)-5*60*1000)


def _atr(values, period=ATR_PERIOD):
    if len(values)<period+1:
        return [0.0]*len(values)

    out=[0.0]*len(values)
    trs=[]
    prev_close=None
    for i,row in enumerate(values):
        high=float(row["high"]); low=float(row["low"]); close=float(row["close"])
        tr=max(
            high-low,
            abs(high-prev_close) if prev_close is not None else high-low,
            abs(low-prev_close) if prev_close is not None else high-low,
        )
        trs.append(tr)
        prev_close=close
        if len(trs)>=period:
            out[i]=sum(trs[-period:])/period
    return out


def _candles(symbol, interval=PRIMARY_INTERVAL):
    start=_start_ms(symbol)
    if start is None:
        return []

    now=int(datetime.now(timezone.utc).timestamp()*1000)
    df=crypto_klines(
        symbol,
        interval=interval,
        limit=1000,
        start_time=start,
        end_time=now,
    )

    raw=[{
        "time":datetime.fromtimestamp(
            int(r.open_time)/1000,tz=timezone.utc
        ).isoformat(),
        "high":float(r.high),
        "low":float(r.low),
        "close":float(r.close),
    } for r in df.itertuples()]

    atrs=_atr(raw)
    for row,atr in zip(raw,atrs):
        row["atr"]=atr
    return raw


def _higher_timeframe_snapshot(symbol):
    """Return the latest completed 1h candle for diagnostics.

    This does not independently close trades; 5m is the deterministic
    execution resolution. It gives the monitor a higher-timeframe heartbeat
    without double-counting the same trade event.
    """
    start=int(datetime.now(timezone.utc).timestamp()*1000)-3*60*60*1000
    df=crypto_klines(
        symbol,
        interval=HTF_INTERVAL,
        limit=6,
        start_time=start,
        end_time=int(datetime.now(timezone.utc).timestamp()*1000),
    )
    if len(df)==0:
        return None
    r=df.iloc[-2] if len(df)>1 else df.iloc[-1]
    return {
        "time":datetime.fromtimestamp(int(r.open_time)/1000,tz=timezone.utc).isoformat(),
        "high":float(r.high),
        "low":float(r.low),
        "close":float(r.close),
    }


async def _evaluate_symbol(symbol):
    primary=await asyncio.to_thread(_candles,symbol,PRIMARY_INTERVAL)
    closed=0
    for candle in primary:
        closed += mark_candle(symbol,candle)

    htf=None
    try:
        htf=await asyncio.to_thread(_higher_timeframe_snapshot,symbol)
    except Exception:
        htf=None

    return {
        "symbol":symbol,
        "primary_interval":PRIMARY_INTERVAL,
        "candles_checked":len(primary),
        "closed":closed,
        "higher_timeframe":htf,
    }


async def evaluate():
    results=[]
    for symbol in _open_symbols():
        try:
            results.append(await _evaluate_symbol(symbol))
        except Exception as exc:
            results.append({
                "symbol":symbol,
                "error":f"{type(exc).__name__}: {exc}",
            })

    expired=expire_old_trades()
    return results,expired


async def main():
    print("AURELIS MULTI-TIMEFRAME PAPER MONITOR")
    results,expired=await evaluate()
    print({
        "primary_interval":PRIMARY_INTERVAL,
        "higher_timeframe":HTF_INTERVAL,
        "results":results,
        "expired":expired,
    })
    print(paper_summary())


if __name__=="__main__":
    asyncio.run(main())
