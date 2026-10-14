import unittest

import numpy as np
import pandas as pd

from trade_bot.pattern_walk_forward import _net_r, walk_forward


def candles(n=520, seed=7):
    rng = np.random.default_rng(seed)
    returns = rng.normal(0.0003, 0.012, n)
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


class WalkForwardPatternTests(unittest.TestCase):
    def test_cost_is_deducted_in_r(self):
        self.assertAlmostEqual(_net_r(1.0, 0.08), 0.92)
        self.assertAlmostEqual(_net_r(-1.0, 0.08), -1.08)

    def test_negative_cost_fails_closed(self):
        with self.assertRaises(ValueError):
            walk_forward({"AAAUSDT": candles()}, cost_r=-0.01)

    def test_report_is_research_only_and_has_three_chronological_folds(self):
        report = walk_forward({"AAAUSDT": candles(), "BBBUSDT": candles(seed=8)})
        self.assertTrue(report["research_only"])
        self.assertFalse(report["signal_engine_modified"])
        self.assertFalse(report["real_money_enabled"])
        self.assertEqual(report["symbols_loaded"], 2)
        self.assertEqual(len(report["folds"]), 3)
        self.assertTrue(all(fold["cost_adjusted"] for fold in report["folds"]))
        self.assertIn("avg_r", report["overall_out_of_sample"])

    def test_missing_columns_are_reported_without_crashing_other_symbols(self):
        report = walk_forward({
            "BADUSDT": candles().drop(columns=["trades"]),
            "GOODUSDT": candles(seed=9),
        })
        self.assertIn("BADUSDT", report["symbol_errors"])
        self.assertEqual(report["symbols_loaded"], 1)
