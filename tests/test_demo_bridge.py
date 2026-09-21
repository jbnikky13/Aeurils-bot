import os
import unittest
from trade_bot.demo_bridge import calculate_quantity


class DemoBridgeTests(unittest.TestCase):
    def test_quantity_respects_risk_and_notional_cap(self):
        q=calculate_quantity(100,95,1000,0.5,20,0.001)
        self.assertGreater(q,0)
        self.assertLessEqual(q*100,200)

    def test_invalid_risk_inputs_fail(self):
        with self.assertRaises(ValueError):
            calculate_quantity(100,100,1000)


if __name__=="__main__":
    unittest.main()
