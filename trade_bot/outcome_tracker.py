import sqlite3
from datetime import datetime, timezone
from .journal import DB, init_db


def open_setups():
    init_db()
    with sqlite3.connect(DB) as con:
        return con.execute("SELECT id,symbol,asset_type,direction,entry_low,entry_high,stop_loss,tp1,tp2 FROM setups WHERE outcome='OPEN'").fetchall()


def update_outcomes(price_lookup):
    rows = open_setups()
    updated = []
    with sqlite3.connect(DB) as con:
        for row in rows:
            sid, symbol, asset_type, direction, low, high, stop, tp1, tp2 = row
            try: price = float(price_lookup(symbol, asset_type))
            except Exception: continue
            outcome = None
            if direction == 'LONG':
                if stop is not None and price <= stop: outcome = 'LOSS'
                elif tp2 is not None and price >= tp2: outcome = 'WIN_TP2'
                elif tp1 is not None and price >= tp1: outcome = 'WIN_TP1'
            elif direction == 'SHORT':
                if stop is not None and price >= stop: outcome = 'LOSS'
                elif tp2 is not None and price <= tp2: outcome = 'WIN_TP2'
                elif tp1 is not None and price <= tp1: outcome = 'WIN_TP1'
            if outcome:
                con.execute("UPDATE setups SET outcome=? WHERE id=?", (outcome, sid))
                updated.append((sid, symbol, outcome))
    return updated
