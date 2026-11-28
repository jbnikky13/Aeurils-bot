import unittest
from trade_bot.forward_validation import fingerprint, cohort_eligible, evaluate_gates, bootstrap_daily_block_ci, load_state, save_state, PROTOCOL
from trade_bot.token_intelligence import analyze_behavior, score_token, select_watchlist, rotation_reasons

class FV1Tests(unittest.TestCase):
    def test_fingerprint_order_independent(self):
        self.assertEqual(fingerprint({"a":"1","b":"2"}), fingerprint({"b":"2","a":"1"}))
    def test_cohort_rejects_old_wrong_hash_and_naive_time(self):
        base={"created_at":"2026-12-01T00:00:00Z","strategy_fingerprint":"x","cohort_id":"FV1","status":"OPEN"}
        self.assertTrue(cohort_eligible(base,"2026-11-30T00:00:00Z","x")[0])
        self.assertEqual(cohort_eligible(base,"2026-12-02T00:00:00Z","x")[1],"pre_freeze_signal")
        self.assertEqual(cohort_eligible(base,"2026-11-30T00:00:00Z","y")[1],"strategy_fingerprint_mismatch")
        bad=dict(base,created_at="2026-12-01T00:00:00")
        self.assertFalse(cohort_eligible(bad,"2026-11-30T00:00:00Z","x")[0])
    def test_missing_gate_data_is_pending(self):
        self.assertEqual(evaluate_gates({"signals":200})["status"],"PENDING")
    def test_gate_pass_requires_all_thresholds(self):
        m={"signals":200,"scored":100,"days":30,"expectancy_pct":.1,"profit_factor":1.25,
           "equity_drawdown_pct":15,"integrity_pct":98,"bootstrap_ci_low_pct":.001,"critical_risk_breaches":0}
        self.assertEqual(evaluate_gates(m)["status"],"PASS")
        m["critical_risk_breaches"]=1
        self.assertEqual(evaluate_gates(m)["status"],"FAIL")
    def test_daily_block_bootstrap(self):
        self.assertIsNone(bootstrap_daily_block_ci([1]))
        self.assertGreater(bootstrap_daily_block_ci([1,2,3,4,5],iterations=100)["lower_95_pct"],0)
    def test_state_roundtrip(self):
        import tempfile, os
        with tempfile.TemporaryDirectory() as d:
            p=os.path.join(d,"state.json"); s=load_state(p); save_state(p,s)
            self.assertEqual(load_state(p)["cohort_id"],"FV1")

class TokenTests(unittest.TestCase):
    def candles(self,n=50):
        return [{"open":100+i,"high":102+i,"low":99+i,"close":101+i,"volume":1000+i} for i in range(n)]
    def test_closed_history_minimum_and_metrics(self):
        self.assertFalse(analyze_behavior(self.candles(10))["eligible"])
        self.assertTrue(analyze_behavior(self.candles())["eligible"])
    def test_liquidity_and_spread_fail_closed(self):
        m=analyze_behavior(self.candles())
        self.assertFalse(score_token(m,1000,.1)["eligible"])
        self.assertFalse(score_token(m,3_000_000,.5)["eligible"])
    def test_rank_and_no_forced_slots(self):
        items=[{"symbol":f"T{i}","score":i,"eligible":True} for i in range(1,14)]
        w=select_watchlist(items)
        self.assertEqual(len(w["selected"]),10); self.assertEqual(len(w["reserves"]),3)
        self.assertEqual(select_watchlist(items[:2])["unfilled_active_slots"],8)
    def test_rotation(self):
        self.assertEqual(rotation_reasons([{"symbol":"A"}],[{"symbol":"B"}])["added"],["B"])

if __name__=="__main__": unittest.main()
