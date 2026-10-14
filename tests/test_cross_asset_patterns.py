import unittest

import numpy as np
import pandas as pd

from trade_bot.cross_asset_patterns import analyze, pattern_key


def candles(n=260, seed=7):
    rng = np.random.default_rng(seed)
    returns = rng.normal(0.0005, 0.012, n)
    close = 100 * np.cumprod(1 + returns)
    spread = close * rng.uniform(0.004, 0.02, n)
    volume = rng.uniform(1000, 5000, n)
    return pd.DataFrame({
        "open_time": pd.date_range("2025-01-01", periods=n, freq="4h", tz="UTC"),
        "open": close * (1 + rng.normal(0, 0.002, n)),
        "high": close + spread,
        "low": close - spread,
        "close": close,
        "volume": volume,
        "trades": rng.integers(100, 500, n),
        "taker_buy_base": volume * rng.uniform(0.3, 0.7, n),
        "taker_buy_quote": volume * close,
    })


class CrossAssetPatternTests(unittest.TestCase):
    def test_pattern_key_is_scale_independent_and_deterministic(self):
        frame = candles()
        from trade_bot.historical_features import add_features
        features = add_features(frame)
        a = pattern_key(features.iloc[-1])
        b = pattern_key(features.iloc[-1])
        self.assertIsNotNone(a)
        self.assertEqual(a, b)
        self.assertEqual(len(a), 8)

    def test_analyze_is_research_only_and_does_not_require_pattern_hits(self):
        report = analyze({"AAAUSDT": candles(), "BBBUSDT": candles(seed=8)})
        self.assertTrue(report["research_only"])
        self.assertFalse(report["signal_engine_modified"])
        self.assertFalse(report["real_money_enabled"])
        self.assertEqual(report["symbols_loaded"], 2)
        self.assertIn("patterns", report)
        self.assertGreaterEqual(report["forward_horizon_hours"], 1)

    def test_bad_train_fraction_fails_closed(self):
        with self.assertRaises(ValueError):
            analyze({"AAAUSDT": candles()}, train_fraction=0.4)

    def test_missing_required_column_is_reported_per_symbol(self):
        frame = candles().drop(columns=["trades"])
        report = analyze({"BADUSDT": frame})
        self.assertIn("BADUSDT", report["symbol_errors"])
        self.assertEqual(report["symbols_loaded"], 0)



