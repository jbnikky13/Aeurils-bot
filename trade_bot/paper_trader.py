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
    return {'total':total,'open':opened,'closed':closed,'wins':wins,'losses':losses,'pnl_pct':round(float(pnl),4)}
