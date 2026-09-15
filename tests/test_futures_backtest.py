import unittest
import pandas as pd
from trade_bot.futures_backtest import continuation, Trade, simulate

class FuturesBacktestTests(unittest.TestCase):
    def test_short_continuation_score(self):
        prior=pd.DataFrame({"high":[110]*20,"low":[100]*20})
        row=pd.Series({"close":99,"ema20":101,"ema50":103,"ema200":105,"rsi":30,"adx":30,"macd_hist":-1,"atr":2,"volume_ratio":2.0})
        mode,score,trend=continuation(row,prior,"SHORT",3.0,0.80)
        self.assertIn(mode,{"BREAKOUT","CONTINUATION"})
        self.assertGreaterEqual(score,70)
        self.assertTrue(trend)

    def test_runner_can_capture_move_after_tp2(self):
        entry=pd.Timestamp("2026-01-01T01:00:00Z")
        t=Trade("TESTUSDT","SHORT","CONTINUATION",90,str(entry),100,105,98,96)
        closes=[97,95,92,90,88,92]
        rows=[]
        for i,close in enumerate(closes):
            ts=entry+pd.Timedelta(hours=i+1)
            high=close+1; low=close-1
            rows.append({"time":ts,"open":close+1,"high":high,"low":low,"close":close,"atr":1})
        result=simulate(t,pd.DataFrame(rows))
        self.assertEqual(result.outcome,"WIN_RUNNER")
        self.assertGreater(result.pnl_pct,0)

if __name__=="__main__": unittest.main()
