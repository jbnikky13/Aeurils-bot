import unittest

import numpy as np
import pandas as pd

from trade_bot.execution_robustness import (
    DEFAULT_COST_SCENARIOS,
    _cost_r,
    _outcome_and_bars,
    analyze_execution_robustness,
)


def candles(n=600, seed=31):
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


class ExecutionRobustnessTests(unittest.TestCase):
    def test_cost_increases_with_holding_duration_and_stress_assumptions(self):
        base = DEFAULT_COST_SCENARIOS["base"]
        short = _cost_r(100, 2, 1, base)
        long = _cost_r(100, 2, 6, base)
        stress = _cost_r(100, 2, 6, DEFAULT_COST_SCENARIOS["stress"])
        self.assertGreater(long, short)
        self.assertGreater(stress, long)

    def test_cost_rejects_invalid_inputs(self):
        with self.assertRaises(ValueError):
            _cost_r(100, 2, 0, DEFAULT_COST_SCENARIOS["base"])
        with self.assertRaises(ValueError):
            _cost_r(100, 2, 2, {"fee_bps_per_side": -1, "slippage_bps_per_side": 1,
                                  "funding_bps_per_8h": 1})

    def test_outcome_reports_bars_held(self):
        frame = pd.DataFrame({
            "close": [100.0] * 8, "atr14": [1.0] * 8,
            "low": [99.0] * 8, "high": [101.0] * 8,
        })
        # With a 1.5 ATR stop and 2 ATR target neither is hit, so the time exit is horizon bars.
        self.assertEqual(_outcome_and_bars(frame, 1, "LONG", 3), (0.0, 3))

    def test_report_is_research_only_and_keeps_live_engine_unchanged(self):
        report = analyze_execution_robustness(
            {"AAAUSDT": candles(), "BBBUSDT": candles(seed=32)},
            bootstrap_iterations=100,
        )
        self.assertTrue(report["research_only"])
        self.assertFalse(report["signal_engine_modified"])
        self.assertFalse(report["real_money_enabled"])
        self.assertIn("low", report["cost_scenarios"])
        self.assertIn("base", report["cost_scenarios"])
        self.assertIn("stress", report["cost_scenarios"])
        self.assertIn("base_cost_bootstrap_ci", report)
        self.assertIn("holdout_pass", report)

    def test_invalid_holdout_fails_closed(self):
        with self.assertRaises(ValueError):
            analyze_execution_robustness({"AAAUSDT": candles()}, holdout_start_fraction=0.5)


if __name__ == "__main__":
    unittest.main()
