import unittest

from trade_bot.binance_demo import BinanceDemoClient, DemoTradingDisabled
from trade_bot.execution_config import assert_demo_only


class BinanceDemoSafetyTests(unittest.TestCase):
    def test_paper_is_safe_default(self):
        old = __import__("os").environ.pop("EXECUTION_MODE", None)
        try:
            assert_demo_only()
            with self.assertRaises(DemoTradingDisabled):
                BinanceDemoClient()
        finally:
            if old is not None:
                __import__("os").environ["EXECUTION_MODE"] = old

    def test_live_mode_is_rejected(self):
        import os
        old = os.environ.get("EXECUTION_MODE")
        os.environ["EXECUTION_MODE"] = "LIVE"
        try:
            with self.assertRaises(RuntimeError):
                assert_demo_only()
        finally:
            if old is None:
                os.environ.pop("EXECUTION_MODE", None)
            else:
                os.environ["EXECUTION_MODE"] = old

    def test_demo_requires_demo_credentials(self):
        import os
        old_mode=os.environ.get("EXECUTION_MODE")
        old_key=os.environ.pop("BINANCE_DEMO_API_KEY", None)
        old_secret=os.environ.pop("BINANCE_DEMO_API_SECRET", None)
        os.environ["EXECUTION_MODE"]="BINANCE_DEMO"
        try:
            with self.assertRaises(DemoTradingDisabled):
                BinanceDemoClient()
        finally:
            if old_mode is None:
                os.environ.pop("EXECUTION_MODE", None)
            else:
                os.environ["EXECUTION_MODE"]=old_mode
            if old_key is not None:
                os.environ["BINANCE_DEMO_API_KEY"]=old_key
            if old_secret is not None:
                os.environ["BINANCE_DEMO_API_SECRET"]=old_secret


if __name__ == "__main__":
    unittest.main()
