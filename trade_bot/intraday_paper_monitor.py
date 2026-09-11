"""Intraday paper-trade monitor using Binance 1-minute OHLC replay."""
import asyncio
import sqlite3
from datetime import datetime, timezone
from .journal import DB, init_db
from .paper_trader import mark_candle, expire_old_trades, paper_summary
from .market_data import crypto_klines


def _open_symbols():
    init_db()
    with sqlite3.connect(DB) as con:
        return [r[0] for r in con.execute("SELECT DISTINCT symbol FROM paper_trades WHERE status='OPEN'").fetchall()]


def _start_ms(symbol):
    with sqlite3.connect(DB) as con:
        rows=con.execute("SELECT opened_at,last_checked_at FROM paper_trades WHERE status='OPEN' AND symbol=?",(symbol,)).fetchall()
    values=[]
    for opened,last in rows:
        value=last or opened
        if not value: continue
        try: values.append(int(datetime.fromisoformat(value.replace('Z','+00:00')).timestamp()*1000))
        except ValueError: pass
    return min(values) if values else None


def _candles(symbol):
    start=_start_ms(symbol)
    if start is None: return []
    now=int(datetime.now(timezone.utc).timestamp()*1000)
    df=crypto_klines(symbol,interval='1m',limit=1000,start_time=start,end_time=now)
    return [{'time':datetime.fromtimestamp(int(r.open_time)/1000,tz=timezone.utc).isoformat(),
             'high':float(r.high),'low':float(r.low),'close':float(r.close)} for r in df.itertuples()]

async def evaluate():
    results=[]
    for symbol in _open_symbols():
        try:
            candles=await asyncio.to_thread(_candles,symbol)
            closed=0
            for candle in candles:
                closed += mark_candle(symbol,candle)
            expired=expire_old_trades()
            results.append({'symbol':symbol,'candles_checked':len(candles),'closed':closed,'expired':expired})
        except Exception as exc:
            results.append({'symbol':symbol,'error':f'{type(exc).__name__}: {exc}'})
    return results

async def main():
    print('AURELIS INTRADAY PAPER MONITOR')
    print(await evaluate())
    print(paper_summary())

if __name__=='__main__': asyncio.run(main())
