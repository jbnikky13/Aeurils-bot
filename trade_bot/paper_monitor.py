"""Daily mark-to-market service for open AURELIS paper trades."""
import asyncio
import sqlite3
from .journal import DB, init_db
from .paper_trader import mark_price, paper_summary
from .market_data import crypto_klines, stock_daily

def _open_symbols():
    init_db()
    with sqlite3.connect(DB) as con:
        rows=con.execute("SELECT DISTINCT symbol FROM paper_trades WHERE status='OPEN'").fetchall()
    return [r[0] for r in rows]

def _price(symbol):
    try:
        df=crypto_klines(symbol, interval='1h', limit=2)
        return float(df.iloc[-1].close)
    except Exception:
        df=stock_daily(symbol, outputsize='compact')
        return float(df.iloc[-1].close)

async def evaluate_open_trades():
    results=[]
    for symbol in _open_symbols():
        try:
            price=await asyncio.to_thread(_price,symbol)
            closed=mark_price(symbol,price)
            results.append({'symbol':symbol,'price':price,'closed':closed})
        except Exception as exc:
            results.append({'symbol':symbol,'error':f'{type(exc).__name__}: {exc}'})
    return results

async def main():
    results=await evaluate_open_trades()
    print('AURELIS PAPER MONITOR')
    print(results)
    print(paper_summary())

if __name__=='__main__':
    asyncio.run(main())
