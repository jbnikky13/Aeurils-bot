import os
import sqlite3
from datetime import datetime, timezone

DB=os.getenv("DATABASE_PATH","trade_bot.db")

def init_db():
    with sqlite3.connect(DB) as con:
        con.execute("""CREATE TABLE IF NOT EXISTS setups (id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, symbol TEXT NOT NULL, asset_type TEXT NOT NULL, direction TEXT NOT NULL, score INTEGER NOT NULL, entry_low REAL, entry_high REAL, stop_loss REAL, tp1 REAL, tp2 REAL, risk_reward REAL, technical_score INTEGER, whale_score INTEGER, sentiment_score INTEGER, outcome TEXT DEFAULT 'OPEN', closed_at TEXT)""")
        cols={r[1] for r in con.execute("PRAGMA table_info(setups)")}
        additions={"closed_at":"TEXT","market_regime":"TEXT DEFAULT 'UNKNOWN'","gemini_confidence":"REAL","gemini_decision":"TEXT","gemini_rationale":"TEXT","whale_bias":"REAL"}
        for col,typ in additions.items():
            if col not in cols: con.execute(f"ALTER TABLE setups ADD COLUMN {col} {typ}")

def record_setup(s):
    init_db()
    with sqlite3.connect(DB) as con:
        cur=con.execute("INSERT INTO setups(created_at,symbol,asset_type,direction,score,entry_low,entry_high,stop_loss,tp1,tp2,risk_reward,technical_score,whale_score,sentiment_score,market_regime,gemini_confidence,gemini_decision,gemini_rationale,whale_bias) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(datetime.now(timezone.utc).isoformat(),s.symbol,s.asset_type,s.direction,s.score,s.entry_low,s.entry_high,s.stop_loss,s.take_profit_1,s.take_profit_2,s.risk_reward,s.technical_score,s.whale_score,s.sentiment_score,getattr(s,"market_regime","UNKNOWN"),getattr(s,"gemini_confidence",None),getattr(s,"gemini_decision",None),getattr(s,"gemini_rationale",None),getattr(s,"whale_bias",None)))
        return cur.lastrowid

def performance():
    init_db()
    with sqlite3.connect(DB) as con:
        rows=con.execute("SELECT outcome,COUNT(*) FROM setups GROUP BY outcome").fetchall(); total=sum(n for _,n in rows); wins=sum(n for k,n in rows if k.startswith("WIN_")); result=dict(rows); result["WIN_RATE"]=round(100*wins/total,2) if total else 0.0; return result

def audit_stats():
    init_db()
    with sqlite3.connect(DB) as con:
        con.row_factory=sqlite3.Row
        rows=con.execute("SELECT market_regime,asset_type,outcome,COUNT(*) AS count,ROUND(AVG(score),1) AS avg_score,ROUND(AVG(technical_score),1) AS avg_technical,ROUND(AVG(whale_score),1) AS avg_whale,ROUND(AVG(sentiment_score),1) AS avg_sentiment FROM setups GROUP BY market_regime,asset_type,outcome ORDER BY market_regime,asset_type,outcome").fetchall()
    return [dict(r) for r in rows]
