import sqlite3
from pathlib import Path

from trade_bot import paper_analytics


def make_db(path):
    with sqlite3.connect(path) as con:
        con.execute("""
            CREATE TABLE paper_trades (
                id INTEGER, signal_id INTEGER, symbol TEXT, direction TEXT,
                entry REAL, stop_loss REAL, tp1 REAL, tp2 REAL, status TEXT,
                exit_price REAL, outcome TEXT, pnl_pct REAL, opened_at TEXT,
                closed_at TEXT, final_score REAL, market_regime TEXT,
                gemini_available INTEGER
            )
        """)
        rows = [
            (1,1,"AAAUSDT","LONG",100,95,110,115,"CLOSED",110,"WIN_TP1",10,"2026-09-01T10:00:00+00:00","2026-09-01T12:00:00+00:00",72,"BULLISH",1),
            (2,2,"BBBUSDT","SHORT",100,105,90,85,"CLOSED",105,"LOSS_SL",-5,"2026-09-01T11:00:00+00:00","2026-09-01T13:00:00+00:00",68,"BEARISH",0),
            (3,3,"CCCUSDT","LONG",100,95,110,115,"OPEN",None,None,None,"2026-09-01T12:00:00+00:00",None,75,"BULLISH",1),
        ]
        con.executemany("INSERT INTO paper_trades VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)


def test_analytics_uses_closed_trades_and_fees(tmp_path):
    db = tmp_path / "paper.db"
    make_db(db)
    old = paper_analytics.DB
    paper_analytics.DB = str(db)
    try:
        a = paper_analytics.analytics()
        assert a["paper_trades"] == 3
        assert a["open"] == 1
        assert a["closed"] == 2
        assert a["wins"] == 1
        assert a["losses"] == 1
        assert a["win_rate_pct"] == 50.0
        assert a["net_pnl_pct"] == 4.6
        assert a["profit_factor"] > 1
        assert a["max_drawdown_pct"] == 5.2
    finally:
        paper_analytics.DB = old
