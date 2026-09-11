"""Monitor open AURELIS paper trades using completed 1h candles."""
import asyncio
import sqlite3
from .journal import DB, init_db
from .paper_trader import mark_candle, expire_old_trades, paper_summary
from .market_data import crypto_klines, stock_daily


def _open_symbols():
    init_db()
    with sqlite3.connect(DB) as con:
        rows = con.execute("SELECT DISTINCT symbol FROM paper_trades WHERE status='OPEN'").fetchall()
    return [r[0] for r in rows]


def _candle(symbol):
    try:
        df = crypto_klines(symbol, interval='1h', limit=3)
        # Use the latest completed candle. The final Binance row can still be forming.
        row = df.iloc[-2] if len(df) >= 2 else df.iloc[-1]
        return {
            'high': float(row.high),
            'low': float(row.low),
            'close': float(row.close),
            'time': datetime_from_ms(int(row.close_time)),
        }
    except Exception:
        # Stocks remain daily for now; the 1h rule applies to Binance crypto.
        df = stock_daily(symbol, outputsize='compact')
        row = df.iloc[-1]
        return {
            'high': float(row.high),
            'low': float(row.low),
            'close': float(row.close),
            'time': str(row.date),
        }


def datetime_from_ms(ms):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


async def evaluate_open_trades():
    results = []
    for symbol in _open_symbols():
        try:
            candle = await asyncio.to_thread(_candle, symbol)
            closed = mark_candle(symbol, candle)
            results.append({'symbol': symbol, 'candle': candle, 'closed': closed})
        except Exception as exc:
            results.append({'symbol': symbol, 'error': f'{type(exc).__name__}: {exc}'})
    expired = expire_old_trades()
    return results, expired


async def main():
    results, expired = await evaluate_open_trades()
    print('AURELIS PAPER MONITOR — 1H RESOLUTION')
    print(results)
    print(f'Expired after 24h: {expired}')
    print(paper_summary())


if __name__ == '__main__':
    asyncio.run(main())
