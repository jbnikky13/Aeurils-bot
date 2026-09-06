"""Deterministic paper-trading ledger. Never submits exchange orders."""
import sqlite3
from datetime import datetime, timezone
from .journal import DB, init_db
PAPER_TABLE="paper_trades"

def init_paper_db():
    init_db()
    with sqlite3.connect(DB) as con:
        con.execute(f"CREATE TABLE IF NOT EXISTS {PAPER_TABLE} (id INTEGER PRIMARY KEY AUTOINCREMENT, signal_id INTEGER UNIQUE NOT NULL, symbol TEXT NOT NULL, direction TEXT NOT NULL, entry REAL NOT NULL, stop_loss REAL, tp1 REAL, tp2 REAL, status TEXT NOT NULL DEFAULT 'OPEN', exit_price REAL, outcome TEXT, pnl_pct REAL, opened_at TEXT NOT NULL, closed_at TEXT)")
        con.commit()

def open_paper_trade(signal_id,symbol,direction,entry,stop_loss=None,tp1=None,tp2=None):
    init_paper_db()
    with sqlite3.connect(DB) as con:
        cur=con.execute(f"INSERT OR IGNORE INTO {PAPER_TABLE} (signal_id,symbol,direction,entry,stop_loss,tp1,tp2,opened_at) VALUES (?,?,?,?,?,?,?,?)",(signal_id,symbol,direction,float(entry),stop_loss,tp1,tp2,datetime.now(timezone.utc).isoformat()))
        con.commit(); return cur.rowcount==1

def _pnl(direction,entry,exit_price):
    return (exit_price-entry)/entry*100 if direction=="LONG" else (entry-exit_price)/entry*100 if direction=="SHORT" else 0.0

def _touch_outcome(direction,price,stop,tp1,tp2):
    if direction=="LONG":
        if stop is not None and price<=stop:return 'LOSS_SL'
        if tp2 is not None and price>=tp2:return 'WIN_TP2'
        if tp1 is not None and price>=tp1:return 'WIN_TP1'
    elif direction=="SHORT":
        if stop is not None and price>=stop:return 'LOSS_SL'
        if tp2 is not None and price<=tp2:return 'WIN_TP2'
        if tp1 is not None and price<=tp1:return 'WIN_TP1'
    return None

def mark_price(symbol,current_price):
    """Evaluate all open trades for a symbol against stop/target levels."""
    init_paper_db(); closed=0
    with sqlite3.connect(DB) as con:
        rows=con.execute(f"SELECT signal_id,direction,entry,stop_loss,tp1,tp2 FROM {PAPER_TABLE} WHERE status='OPEN' AND symbol=?",(symbol,)).fetchall()
        for sid,direction,entry,stop,tp1,tp2 in rows:
            outcome=_touch_outcome(direction,float(current_price),stop,tp1,tp2)
            if outcome:
                pnl=_pnl(direction,float(entry),float(current_price))
                con.execute(f"UPDATE {PAPER_TABLE} SET status='CLOSED',exit_price=?,outcome=?,pnl_pct=?,closed_at=? WHERE signal_id=?",(float(current_price),outcome,pnl,datetime.now(timezone.utc).isoformat(),sid)); closed+=1
        con.commit()
    return closed

def close_paper_trade(signal_id,outcome,exit_price):
    init_paper_db()
    with sqlite3.connect(DB) as con:
        row=con.execute(f"SELECT direction,entry FROM {PAPER_TABLE} WHERE signal_id=? AND status='OPEN'",(signal_id,)).fetchone()
        if not row:return False
        pnl=_pnl(row[0],float(row[1]),float(exit_price))
        con.execute(f"UPDATE {PAPER_TABLE} SET status='CLOSED',exit_price=?,outcome=?,pnl_pct=?,closed_at=? WHERE signal_id=?",(exit_price,outcome,pnl,datetime.now(timezone.utc).isoformat(),signal_id)); con.commit(); return True

def paper_summary():
    init_paper_db()
    with sqlite3.connect(DB) as con:
        total=con.execute(f"SELECT COUNT(*) FROM {PAPER_TABLE}").fetchone()[0]; opened=con.execute(f"SELECT COUNT(*) FROM {PAPER_TABLE} WHERE status='OPEN'").fetchone()[0]; closed=con.execute(f"SELECT COUNT(*) FROM {PAPER_TABLE} WHERE status='CLOSED'").fetchone()[0]; pnl=con.execute(f"SELECT COALESCE(SUM(pnl_pct),0) FROM {PAPER_TABLE} WHERE status='CLOSED'").fetchone()[0]; wins=con.execute(f"SELECT COUNT(*) FROM {PAPER_TABLE} WHERE outcome IN ('WIN_TP1','WIN_TP2')").fetchone()[0]; losses=con.execute(f"SELECT COUNT(*) FROM {PAPER_TABLE} WHERE outcome='LOSS_SL'").fetchone()[0]
    win_rate=(wins/closed*100) if closed else 0.0
    avg_pnl=(float(pnl)/closed) if closed else 0.0
    return {'total':total,'open':opened,'closed':closed,'wins':wins,'losses':losses,'win_rate_pct':round(win_rate,2),'pnl_pct':round(float(pnl),4),'avg_pnl_pct':round(avg_pnl,4)}
