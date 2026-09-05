import os
import sqlite3
from datetime import datetime, timezone

DB = os.getenv("DATABASE_PATH", "trade_bot.db")


def init_db():
    with sqlite3.connect(DB) as con:
        con.execute("""CREATE TABLE IF NOT EXISTS setups (id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, symbol TEXT NOT NULL, asset_type TEXT NOT NULL, direction TEXT NOT NULL, score INTEGER NOT NULL, entry_low REAL, entry_high REAL, stop_loss REAL, tp1 REAL, tp2 REAL, risk_reward REAL, technical_score INTEGER, whale_score INTEGER, sentiment_score INTEGER, outcome TEXT DEFAULT 'OPEN', closed_at TEXT)""")
        cols = {r[1] for r in con.execute("PRAGMA table_info(setups)")}
        if 'closed_at' not in cols: con.execute("ALTER TABLE setups ADD COLUMN closed_at TEXT")


def record_setup(s):
    init_db()
    with sqlite3.connect(DB) as con:
        cur = con.execute("INSERT INTO setups(created_at,symbol,asset_type,direction,score,entry_low,entry_high,stop_loss,tp1,tp2,risk_reward,technical_score,whale_score,sentiment_score) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (datetime.now(timezone.utc).isoformat(), s.symbol, s.asset_type, s.direction, s.score, s.entry_low, s.entry_high, s.stop_loss, s.take_profit_1, s.take_profit_2, s.risk_reward, s.technical_score, s.whale_score, s.sentiment_score))
        return cur.lastrowid


def performance():
    init_db()
    with sqlite3.connect(DB) as con:
        rows = con.execute("SELECT outcome, COUNT(*) FROM setups GROUP BY outcome").fetchall()
        total = sum(n for _, n in rows); wins = sum(n for k, n in rows if k.startswith('WIN_'))
        result = dict(rows); result['WIN_RATE'] = round(100 * wins / total, 2) if total else 0.0
        return result
