import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from trade_bot.futures_engine import assess
from trade_bot.signal_engine import build_setup
from trade_bot import journal, paper_trader
from trade_bot.futures_universe import is_valid_binance_usdt_perpetual
from trade_bot.binance_flow import snapshot


class FuturesStrategyTests(unittest.TestCase):
    def _continuation_df(self):
        n=35; closes=[120-i*0.45 for i in range(n-1)]+[104.0]; highs=[c+1 for c in closes]; lows=[c-1 for c in closes]; volumes=[100]*34+[220]; ema20=[130-i*0.5 for i in range(n-1)]+[108]; ema50=[140-i*0.4 for i in range(n-1)]+[112]; ema200=[160-i*0.2 for i in range(n-1)]+[120]; rows=[]
        for i in range(n): rows.append({"close":closes[i],"high":highs[i],"low":lows[i],"volume":volumes[i],"ema20":ema20[i],"ema50":ema50[i],"ema200":ema200[i],"rsi":28,"adx":32,"macd_hist":-1,"atr":4,"volume_ratio":1.0 if i<n-1 else 2.2})
        rows[-1]["low"]=100; rows[-1]["high"]=106; rows[-1]["close"]=101
        return pd.DataFrame(rows)

    def test_continuation_detects_strong_short_even_with_oversold_rsi(self):
        result=assess(self._continuation_df(),"SHORT",{"oi_change_pct":3.0,"taker_ratio":0.80,"liquidation_pressure":True})
        self.assertIn(result.mode,{"BREAKOUT","CONTINUATION"}); self.assertGreaterEqual(result.score,70); self.assertTrue(result.trend_aligned); self.assertTrue(result.momentum_confirmed); self.assertTrue(result.flow_confirmed)

    def test_continuation_bypasses_normal_rsi_and_extension_veto(self):
        signal=build_setup("BRUSDT","crypto",120,85,80,50,-0.8,-0.5,5,"BEARISH",ema20=100,recent_high=105,recent_low=100,rsi=20,strategy_mode="BREAKOUT",continuation_score=85)
        self.assertEqual(signal.direction,"SHORT"); self.assertTrue(signal.runner_enabled); self.assertEqual(signal.entry_status,"READY_CONTINUATION"); self.assertGreaterEqual(signal.risk_reward,1.5)

    def test_normal_oversold_short_is_still_blocked(self):
        signal=build_setup("TESTUSDT","crypto",120,85,80,50,-0.8,-0.5,5,"BEARISH",ema20=100,recent_high=105,recent_low=100,rsi=20)
        self.assertEqual(signal.direction,"WAIT"); self.assertEqual(signal.entry_status,"EXTENDED")

    def test_futures_universe_validation_is_fail_closed(self):
        self.assertTrue(is_valid_binance_usdt_perpetual("BRUSDT",["BRUSDT","BTCUSDT"])); self.assertFalse(is_valid_binance_usdt_perpetual("BRUSDT",["BTCUSDT"]))

    def test_futures_flow_uses_futures_depth(self):
        responses={"/fapi/v1/depth":{"bids":[[100,10]],"asks":[[100,5]]},"/fapi/v1/openInterest":{"openInterest":"100"},"/futures/data/openInterestHist":[{"sumOpenInterest":"100"},{"sumOpenInterest":"104"},{"sumOpenInterest":"104"}],"/fapi/v1/klines":[[0,"100","101","99","100","1",0,0,0,0,0,0],[1,"100","101","95","96","1",0,0,0,0,0,0]],"/fapi/v1/fundingRate":[{"fundingRate":"0.0001"}],"/futures/data/takerlongshortRatio":[{"buySellRatio":"0.80"}],"/fapi/v1/allForceOrders":[]}
        with patch("trade_bot.binance_flow._get",side_effect=lambda path,params=None:responses[path]): result=snapshot("BRUSDT","SHORT")
        self.assertTrue(result["available"]); self.assertLess(result["price_change_pct"],0); self.assertGreater(result["oi_change_pct"],0); self.assertLess(result["taker_ratio"],1)

    def test_runner_keeps_trade_open_after_tp1(self):
        tmp=tempfile.NamedTemporaryFile(suffix=".db",delete=False); tmp.close()
        try:
            journal.DB=tmp.name; paper_trader.DB=tmp.name; journal.init_db(); sid=journal.record_setup(type("S",(),{"symbol":"RUNUSDT","asset_type":"crypto","direction":"SHORT","score":80,"entry_low":99,"entry_high":101,"stop_loss":105,"take_profit_1":95,"take_profit_2":90,"risk_reward":2,"technical_score":80,"whale_score":80,"sentiment_score":50,"market_regime":"BEARISH","strategy_mode":"CONTINUATION","continuation_score":80,"runner_enabled":True,"trailing_atr_multiplier":2.0})())
            paper_trader.open_paper_trade(sid,"RUNUSDT","SHORT",100,105,95,90,runner_enabled=True,trailing_atr_multiplier=2.0)
            self.assertEqual(paper_trader.mark_candle("RUNUSDT",{"time":"2099-01-01T01:00:00+00:00","high":99,"low":94,"close":96,"atr":2}),0)
            with sqlite3.connect(tmp.name) as con: row=con.execute("SELECT status,remaining_pct,tp1_hit_at FROM paper_trades WHERE signal_id=?",(sid,)).fetchone()
            self.assertEqual(row[0],"OPEN"); self.assertAlmostEqual(row[1],70.0); self.assertIsNotNone(row[2])
        finally: os.unlink(tmp.name)


if __name__=="__main__": unittest.main()
