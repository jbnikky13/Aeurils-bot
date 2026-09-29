import unittest
from trade_bot.performance_audit_v2 import build_report, _duration_class

class PerformanceAuditV2Tests(unittest.TestCase):
    def row(self,**kw):
        base={"status":"CLOSED","outcome":"WIN_TP1","pnl_pct":2.0,"entry":100.0,
              "exit_price":102.0,"direction":"LONG","initial_risk":2.0,
              "opened_at":"2026-09-01T00:00:00+00:00",
              "closed_at":"2026-09-01T05:00:00+00:00",
              "max_favorable_pct":3.0,"max_adverse_pct":1.0,
              "resolution_source":"5m_ohlc","final_score":75,
              "market_regime":"BULLISH","symbol":"BTCUSDT",
              "signal_source":"PRIMARY"}
        base.update(kw); return base

    def test_legacy_expiry_is_not_in_strict_view(self):
        rows=[self.row(),self.row(outcome="EXPIRED",pnl_pct=5.0,
            resolution_source="24h_timeout")]
        r=build_report(rows)
        self.assertEqual(r["all_closed"]["trades"],2)
        self.assertEqual(r["strict_boundary_view"]["trades"],1)
        self.assertEqual(r["data_quality"]["legacy_expiry_rows"],1)

    def test_strict_expiry_is_included(self):
        rows=[self.row(outcome="EXPIRED",pnl_pct=-1.0,
            resolution_source="5m_expiry_boundary")]
        r=build_report(rows)
        self.assertEqual(r["strict_boundary_view"]["expired"],1)
        self.assertEqual(r["strict_boundary_view"]["legacy_expiry_trades"],0)

    def test_duration_classification(self):
        self.assertEqual(_duration_class(self.row()), "INTRADAY_RESOLVED")
        self.assertEqual(_duration_class(self.row(
            outcome="EXPIRED",pnl_pct=3.0,
            closed_at="2026-09-03T00:00:00+00:00",
            resolution_source="24h_timeout")), "EXTENDED_SETUP")
        self.assertEqual(_duration_class(self.row(
            outcome="WIN_TP1",pnl_pct=4.0,
            closed_at="2026-09-03T00:00:00+00:00")), "LONG_DURATION_WINNER")

    def test_r_and_fee_math(self):
        r=build_report([self.row()])
        s=r["strict_boundary_view"]
        self.assertAlmostEqual(s["sum_r"],1.0)
        self.assertAlmostEqual(s["net_pnl_pct"],1.8)

if __name__=="__main__":
    unittest.main()
