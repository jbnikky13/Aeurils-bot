import unittest

import numpy as np
import pandas as pd

from trade_bot.pattern_loss_analysis import COST_GRID_R, _stats, analyze_losses


def candles(n=520, seed=17):
    rng = np.random.default_rng(seed)
    returns = rng.normal(0.0002, 0.012, n)
    close = 100 * np.cumprod(1 + returns)
    spread = close * rng.uniform(0.004, 0.02, n)
    volume = rng.uniform(1000, 5000, n)
    return pd.DataFrame({
        "open_time": pd.date_range("2024-01-01", periods=n, freq="4h", tz="UTC"),
        "open": close * (1 + rng.normal(0, 0.002, n)),
        "high": close + spread,
        "low": close - spread,
        "close": close,
        "volume": volume,
        "trades": rng.integers(100, 500, n),
        "taker_buy_base": volume * rng.uniform(0.3, 0.7, n),
        "taker_buy_quote": volume * close,
    })


class PatternLossAnalysisTests(unittest.TestCase):
    def test_cost_sensitivity_is_monotonic(self):
        rows = [{"symbol": "BTCUSDT", "gross_r": 0.5}]
        values = [_stats(rows, cost)["net_avg_r"] for cost in COST_GRID_R]
        self.assertEqual(values, sorted(values, reverse=True))

    def test_report_is_research_only_and_has_filter_comparisons(self):
        report = analyze_losses({"AAAUSDT": candles(), "BBBUSDT": candles(seed=18)})
        self.assertTrue(report["research_only"])
        self.assertFalse(report["signal_engine_modified"])
        self.assertFalse(report["real_money_enabled"])
        self.assertIn("baseline", report["filter_comparisons"])
        self.assertIn("trend_aligned", report["filter_comparisons"])
        self.assertEqual(report["cost_sensitivity_grid_r"], list(COST_GRID_R))
        self.assertEqual(len(report["folds"]), 3)

    def test_invalid_cost_fails_closed(self):
        with self.assertRaises(ValueError):
            analyze_losses({"AAAUSDT": candles()}, selection_cost_r=-0.1)

    def test_bad_symbol_does_not_stop_good_symbol(self):
        report = analyze_losses({
            "BADUSDT": candles().drop(columns=["trades"]),
            "GOODUSDT": candles(seed=19),
        })
        self.assertIn("BADUSDT", report["symbol_errors"])
        self.assertEqual(report["symbols_loaded"], 1)


if __name__ == "__main__":
    unittest.main()
