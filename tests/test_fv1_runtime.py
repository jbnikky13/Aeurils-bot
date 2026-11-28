import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
from types import SimpleNamespace

from trade_bot import fv1_runtime as fv

class FV1RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db=os.path.join(self.tmp.name,"test.db")
        self.patcher=patch.object(fv,"DB",self.db); self.patcher.start()
        with sqlite3.connect(self.db) as con:
            con.execute("""CREATE TABLE paper_trades (
                signal_id INTEGER PRIMARY KEY, symbol TEXT, opened_at TEXT, status TEXT,
                outcome TEXT, pnl_pct REAL, realized_r REAL, closed_at TEXT,
                resolution_source TEXT, initial_risk REAL, entry REAL, direction TEXT,
                exit_price REAL, final_score REAL, realized_pnl_pct REAL DEFAULT 0, unrealized_r REAL DEFAULT 0)""")
    def tearDown(self):
        self.patcher.stop(); self.tmp.cleanup()
    def add_trade(self,sid,symbol,status="OPEN",outcome=None,r=None,closed=None,score=70):
        opened=(datetime.now(timezone.utc)+timedelta(seconds=1)).isoformat()
        with sqlite3.connect(self.db) as con:
            con.execute("""INSERT INTO paper_trades
                (signal_id,symbol,opened_at,status,outcome,realized_r,closed_at,
                 resolution_source,initial_risk,entry,direction,exit_price,final_score)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (sid,symbol,opened,status,outcome,r,closed,"5m_ohlc",1,100,"LONG",101,score))
        return opened
    def test_only_new_paper_signals_enter_fv1(self):
        meta=fv.initialize()
        opened=self.add_trade(1,"BTCUSDT")
        self.assertTrue(fv.register_signal(1))
        self.assertFalse(fv.register_signal(999))
        with sqlite3.connect(self.db) as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM fv1_cohort").fetchone()[0],1)
    def test_cohort_only_token_rank_and_reserve_slots(self):
        fv.initialize()
        for sid in range(1,5):
            self.add_trade(sid,"BTCUSDT","CLOSED","WIN_TP1",1.2,datetime.now(timezone.utc).isoformat())
            fv.register_signal(sid)
        for sid in range(5,8):
            self.add_trade(sid,"ETHUSDT","CLOSED","LOSS_SL",-1,datetime.now(timezone.utc).isoformat())
            fv.register_signal(sid)
        class FakeResponse:
            def __init__(self,payload): self.payload=payload
            def raise_for_status(self): pass
            def json(self): return self.payload
        class FakeClient:
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def get(self,url,params=None):
                if url.endswith("24hr"): return FakeResponse({"quoteVolume":"10000000"})
                if url.endswith("bookTicker"): return FakeResponse({"bidPrice":"100","askPrice":"100.02"})
                now=int(datetime.now(timezone.utc).timestamp()*1000)
                candles=[[0,"100","102","99",str(100+i),"1000",now-1000] for i in range(45)]
                return FakeResponse(candles)
        with patch.object(fv.httpx,"Client",return_value=FakeClient()):
            w=fv.rank_from_paper_trades()
        self.assertEqual(w["selected"][0]["symbol"],"BTCUSDT")
        self.assertEqual(w["source"],"PAPER_LEDGER_HISTORY_PLUS_BINANCE_LIQUIDITY")
    def test_overlapping_equity_and_risk_controls(self):
        fv.initialize()
        now=datetime.now(timezone.utc).isoformat()
        # Three concurrent positions consume 0.75% aggregate risk.
        for sid in (101,102,103):
            self.add_trade(sid,"BTCUSDT")
            fv.register_signal(sid)
        with sqlite3.connect(self.db) as con:
            con.execute("UPDATE paper_trades SET initial_risk=2, realized_pnl_pct=0, unrealized_r=1 WHERE signal_id IN (101,102,103)")
        from trade_bot import fv1_risk_ledger as risk
        first=risk.record_snapshot(now)
        self.assertEqual(first["open_positions"],3)
        self.assertAlmostEqual(first["aggregate_open_risk_pct"],0.75)
        self.assertAlmostEqual(first["unrealized_r"],3.0)
        # A fourth overlapping position breaches both concurrency and risk caps.
        self.add_trade(104,"ETHUSDT")
        fv.register_signal(104)
        with sqlite3.connect(self.db) as con:
            con.execute("UPDATE paper_trades SET initial_risk=2, unrealized_r=1 WHERE signal_id=104")
        second=risk.record_snapshot((datetime.now(timezone.utc)+timedelta(seconds=2)).isoformat())
        self.assertEqual(second["open_positions"],4)
        self.assertAlmostEqual(second["aggregate_open_risk_pct"],1.0)
        metrics=risk.risk_metrics()
        self.assertEqual(metrics["critical_risk_breaches"],1)
        self.assertIsNotNone(metrics["equity_drawdown_pct"])

    def test_risk_ledger_is_persisted_and_fail_closed_without_snapshots(self):
        fv.initialize()
        from trade_bot import fv1_risk_ledger as risk
        self.assertIsNone(risk.risk_metrics()["equity_drawdown_pct"])
        self.assertIsNone(risk.risk_metrics()["critical_risk_breaches"])

    def test_missing_risk_controls_remain_pending(self):
        fv.initialize()
        m=fv.cohort_metrics()
        self.assertEqual(m["gates"]["status"],"PENDING")
        self.assertEqual(m["gates"]["gates"]["critical_risk_breaches"]["status"],"PENDING")

if __name__ == "__main__":
    unittest.main()
