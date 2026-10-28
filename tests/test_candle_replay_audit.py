import unittest

from trade_bot.candle_replay_audit import _hit, metrics, replay_trade


class CandleReplayAuditTests(unittest.TestCase):
    def setUp(self):
        self.base = {
            "opened_at": "2026-10-01T12:02:00+00:00",
            "symbol": "BTCUSDT",
            "direction": "LONG",
            "entry": 100.0,
            "stop_loss": 95.0,
            "tp1": 110.0,
            "tp2": 120.0,
            "score": 70,
            "market_regime": "BULLISH",
        }

    def test_entry_candle_is_excluded(self):
        # Opened at 12:02; the 12:00 candle overlaps entry and must not be used.
        candles = [
            {"time_ms": 1790856000000, "high": 130, "low": 90, "close": 100},
        ]
        result = replay_trade(self.base, candles)
        self.assertEqual(result["status"], "SKIPPED")

    def test_same_candle_stop_and_target_is_conservative_loss(self):
        result = _hit("LONG", {"high": 111, "low": 94}, 95, 110, 120)
        self.assertEqual(result, ("LOSS_AMBIGUOUS_STOP", 95))

    def test_invalid_direction_is_skipped(self):
        row = {**self.base, "direction": "SIDEWAYS"}
        result = replay_trade(row, [])
        self.assertEqual(result["status"], "SKIPPED")
        self.assertEqual(result["reason"], "invalid_direction")

    def test_stop_hit_is_loss(self):
        result = _hit("LONG", {"high": 104, "low": 94}, 95, 110, 120)
        self.assertEqual(result, ("LOSS_SL", 95))

    def test_tp2_has_precedence_over_tp1_when_stop_not_hit(self):
        result = _hit("LONG", {"high": 121, "low": 99}, 95, 110, 120)
        self.assertEqual(result, ("WIN_TP2", 120))

    def test_metrics_report_additive_drawdown_and_net_fees(self):
        rows = [
            {"status": "SCORED", "outcome": "WIN_TP1", "net_pct": 1.8, "opened_at": "2026-01-01"},
            {"status": "SCORED", "outcome": "LOSS_SL", "net_pct": -2.2, "opened_at": "2026-01-02"},
            {"status": "SCORED", "outcome": "WIN_TP2", "net_pct": 1.8, "opened_at": "2026-01-03"},
        ]
        result = metrics(rows)
        self.assertEqual(result["n"], 3)
        self.assertEqual(result["max_additive_drawdown_pct_points"], 2.2)
        self.assertEqual(result["win_rate_pct"], 66.67)

    def test_missing_candle_gap_is_skipped(self):
        start = 1790856300000
        candles = []
        for i in range(288):
            if i in (10, 11):
                continue
            candles.append({"time_ms": start + i * 300000, "high": 104, "low": 99, "close": 102})
        result = replay_trade(self.base, candles)
        self.assertEqual(result["status"], "SKIPPED")
        self.assertEqual(result["reason"], "candle_data_gaps")

    def test_expiry_uses_last_close_and_subtracts_fee_and_slippage(self):
        # Opened at 12:02, first eligible bar begins at 12:05.
        start = 1790856300000
        candles = []
        for i in range(288):
            candles.append({"time_ms": start + i * 300000, "high": 104, "low": 99, "close": 102})
        result = replay_trade(self.base, candles)
        self.assertEqual(result["status"], "SCORED")
        self.assertEqual(result["outcome"], "EXPIRED")
        self.assertAlmostEqual(result["net_pct"], 1.7, places=6)  # 2.0% gross minus 0.30% modeled round-trip costs


if __name__ == "__main__":
    unittest.main()
