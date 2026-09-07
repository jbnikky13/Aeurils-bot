import os
import tempfile
import unittest

from trade_bot import journal, paper_trader
from trade_bot.calibration import calibration
from trade_bot.gemini_signal import confirm
from trade_bot.confluence_gate import evaluate


class AurelisFixTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        journal.DB = self.tmp.name
        paper_trader.DB = self.tmp.name
        os.environ.pop("GEMINI_API_KEY", None)

    def tearDown(self):
        try:
            os.unlink(self.tmp.name)
        except FileNotFoundError:
            pass

    def test_gemini_missing_key_is_explicit_and_nonfatal(self):
        result = confirm("BTCUSDT", 70, -0.4, 50, 0, 100, 2)
        self.assertFalse(result["available"])
        self.assertEqual(result["decision"], "UNAVAILABLE")
        self.assertIsNone(result["confidence"])

    def test_weighted_gate_allows_a_setup_without_six_confluences(self):
        class Signal:
            direction = "LONG"
            score = 70
            technical_score = 70
            entry_low = 100
            entry_high = 101
            stop_loss = 98
            take_profit_1 = 105
            risk_reward = 2

        gate = evaluate(Signal(), offchain={"volume_liquidity": True})
        self.assertEqual(gate["score"], 65)
        self.assertEqual(gate["tier"], "EARLY_SETUP")
        self.assertFalse(gate["actionable"])

        gate = evaluate(Signal(), offchain={"volume_liquidity": True, "market_regime": True})
        self.assertEqual(gate["score"], 75)
        self.assertEqual(gate["tier"], "A_SETUP")
        self.assertTrue(gate["actionable"])

    def test_weighted_gate_keeps_bad_risk_non_actionable(self):
        class Signal:
            direction = "LONG"
            score = 90
            technical_score = 90
            entry_low = 100
            entry_high = 101
            stop_loss = 99
            take_profit_1 = 101
            risk_reward = 0.5

        gate = evaluate(Signal(), offchain={"volume_liquidity": True, "market_regime": True, "sentiment_narrative": True})
        self.assertFalse(gate["actionable"])
        self.assertEqual(gate["tier"], "EARLY_SETUP")
        self.assertTrue(gate["hard_block"])

    def test_paper_close_syncs_setup_and_calibration(self):
        journal.init_db()

        class Signal:
            symbol = "TESTUSDT"
            asset_type = "crypto"
            direction = "SHORT"
            score = 66
            entry_low = 99
            entry_high = 101
            stop_loss = 105
            take_profit_1 = 95
            take_profit_2 = 90
            risk_reward = 2
            technical_score = 80
            whale_score = 50
            sentiment_score = 50
            market_regime = "BEARISH"
            gemini_confidence = None
            gemini_decision = "UNAVAILABLE"
            gemini_rationale = "Gemini unavailable: HTTP 429"
            whale_bias = 0

        signal_id = journal.record_setup(Signal())
        paper_trader.open_paper_trade(
            signal_id, "TESTUSDT", "SHORT", 100, 105, 95, 90,
            final_score=66, market_regime="BEARISH",
            gemini_decision="UNAVAILABLE", gemini_confidence=None,
            gemini_available=0,
        )

        self.assertEqual(paper_trader.mark_price("TESTUSDT", 94), 1)
        with __import__("sqlite3").connect(self.tmp.name) as con:
            setup = con.execute("SELECT outcome FROM setups WHERE id=?", (signal_id,)).fetchone()
            paper = con.execute("SELECT outcome,final_score,market_regime FROM paper_trades WHERE signal_id=?", (signal_id,)).fetchone()
        self.assertEqual(setup[0], "WIN_TP1")
        self.assertEqual(paper, ("WIN_TP1", 66.0, "BEARISH"))

        report = calibration()
        self.assertEqual(report["closed"], 1)
        self.assertEqual(report["by_score"][0][0], "60-69")


if __name__ == "__main__":
    unittest.main()
