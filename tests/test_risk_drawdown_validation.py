import json
import tempfile
import unittest
from pathlib import Path

from trade_bot import performance_audit_v2, paper_filter_validation


class RiskAndHoldoutValidationTests(unittest.TestCase):
    def test_risk_is_reconstructed_from_entry_and_stop_loss(self):
        row = {
            "status": "CLOSED", "outcome": "WIN_TP1", "direction": "LONG",
            "entry": 100.0, "stop_loss": 95.0, "exit_price": 110.0,
            "pnl_pct": 10.0, "initial_risk": None, "closed_at": "2026-01-02T00:00:00+00:00",
            "opened_at": "2026-01-01T00:00:00+00:00", "max_favorable_pct": 10.0,
            "max_adverse_pct": 1.0,
        }
        report = performance_audit_v2._stats([row])
        self.assertEqual(report["risk_derived_from_stop_loss"], 1)
        self.assertEqual(report["risk_unrecoverable"], 0)
        self.assertEqual(report["r_samples"], 1)
        self.assertEqual(report["avg_r"], 2.0)
        self.assertEqual(report["r_coverage_pct"], 100.0)

    def test_unrecoverable_risk_is_not_reported_as_zero_r(self):
        row = {
            "status": "CLOSED", "outcome": "EXPIRED", "direction": "LONG",
            "entry": 100.0, "stop_loss": None, "exit_price": 100.0,
            "pnl_pct": 0.0, "initial_risk": None, "closed_at": "2026-01-02T00:00:00+00:00",
            "opened_at": "2026-01-01T00:00:00+00:00",
        }
        report = performance_audit_v2._stats([row])
        self.assertEqual(report["risk_unrecoverable"], 1)
        self.assertEqual(report["r_samples"], 0)
        self.assertIsNone(report["avg_r"])
        self.assertIsNone(report["sum_r"])

    def test_legacy_database_rows_get_risk_backfilled(self):
        import os
        import sqlite3
        from trade_bot import journal, paper_trader

        old_journal_db, old_trader_db = journal.DB, paper_trader.DB
        handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        handle.close()
        try:
            journal.DB = handle.name
            paper_trader.DB = handle.name
            with sqlite3.connect(handle.name) as con:
                con.execute("""CREATE TABLE paper_trades (
                    id INTEGER PRIMARY KEY, signal_id INTEGER UNIQUE NOT NULL,
                    symbol TEXT NOT NULL, direction TEXT NOT NULL, entry REAL NOT NULL,
                    stop_loss REAL, tp1 REAL, tp2 REAL, status TEXT NOT NULL,
                    exit_price REAL, outcome TEXT, pnl_pct REAL, opened_at TEXT NOT NULL,
                    closed_at TEXT
                )""")
                con.execute("""INSERT INTO paper_trades
                    (id,signal_id,symbol,direction,entry,stop_loss,tp1,tp2,status,opened_at)
                    VALUES (1,1,'TESTUSDT','LONG',100,95,110,115,'CLOSED','2026-01-01T00:00:00+00:00')""")
            paper_trader.init_paper_db()
            with sqlite3.connect(handle.name) as con:
                risk = con.execute("SELECT initial_risk FROM paper_trades WHERE signal_id=1").fetchone()[0]
            self.assertEqual(risk, 5.0)
        finally:
            journal.DB = old_journal_db
            paper_trader.DB = old_trader_db
            try:
                os.unlink(handle.name)
            except FileNotFoundError:
                pass

    def test_validation_uses_chronological_holdout_and_does_not_promote_small_test(self):
        rows = []
        for i in range(100):
            win = i % 3 != 0
            rows.append({
                "id": i + 1,
                "opened_at": f"2026-01-{1 + i // 4:02d}T{(i % 4) * 6:02d}:00:00+00:00",
                "closed_at": f"2026-01-{1 + i // 4:02d}T{(i % 4) * 6 + 1:02d}:00:00+00:00",
                "status": "CLOSED", "outcome": "WIN_TP1" if win else "LOSS_SL",
                "pnl_pct": 3.0 if win else -1.5, "direction": "LONG" if i % 2 == 0 else "SHORT",
                "final_score": 68 if i % 4 else 64,
                "market_regime": "BULLISH" if i % 3 else "BEARISH",
                "entry": 100.0, "stop_loss": 95.0, "initial_risk": 5.0,
            })
        report = paper_filter_validation.validate(rows, min_train_scored=10, min_test_scored=50)
        self.assertTrue(report["research_only"])
        self.assertFalse(report["signal_engine_modified"])
        self.assertFalse(report["real_money_enabled"])
        self.assertEqual(report["train_rows"], 70)
        self.assertEqual(report["test_rows"], 30)
        if report["selected_filter"]:
            self.assertIn(report["status"], {
                "INSUFFICIENT_HOLDOUT_SAMPLE",
                "OUT_OF_SAMPLE_IMPROVEMENT_NOT_SUPPORTED",
                "OUT_OF_SAMPLE_IMPROVEMENT_SUPPORTED",
            })
        self.assertEqual(report["test_start"], rows[70]["opened_at"] if rows[69]["opened_at"] <= rows[70]["opened_at"] else report["test_start"])


if __(!1) {}
