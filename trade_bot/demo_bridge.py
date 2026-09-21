"""Bridge approved AURELIS signals into Binance Futures Demo.

This module is deliberately conservative:
- only BINANCE_DEMO execution is allowed;
- PAPER remains the default;
- every entry receives reduce-only SL and TP orders;
- quantity is derived from risk budget and capped;
- client order IDs make reconciliation possible;
- no live endpoint or live mode is supported.
"""
from __future__ import annotations
import math, os, time
from .binance_demo import BinanceDemoClient
from .execution_config import assert_demo_only


def _round_step(value, step):
    if step <= 0:
        return value
    return math.floor(value / step) * step


def calculate_quantity(entry, stop, equity, risk_pct=0.5, max_notional_pct=20.0, step_size=0.001):
    entry=float(entry); stop=float(stop); equity=float(equity)
    risk=abs(entry-stop)
    if entry <= 0 or risk <= 0 or equity <= 0:
        raise ValueError("Invalid entry, stop, or equity.")
    risk_cash=equity*float(risk_pct)/100
    qty=risk_cash/risk
    max_qty=(equity*float(max_notional_pct)/100)/entry
    return max(0.0,_round_step(min(qty,max_qty),float(step_size)))


def execute_signal(signal, equity):
    cfg=assert_demo_only()
    if cfg["mode"] != "BINANCE_DEMO":
        raise RuntimeError("Demo bridge requires EXECUTION_MODE=BINANCE_DEMO.")

    symbol=str(signal["symbol"]).upper()
    direction=str(signal["direction"]).upper()
    entry=float(signal["entry"])
    stop=float(signal["stop_loss"])
    tp1=float(signal["tp1"])
    step=float(signal.get("step_size",0.001))
    qty=calculate_quantity(entry,stop,equity,cfg["max_risk_per_trade_pct"],20.0,step)
    if qty <= 0:
        raise ValueError("Calculated demo quantity is zero.")

    client=BinanceDemoClient()
    client.set_leverage(symbol,min(int(signal.get("leverage",1)),cfg["max_leverage"]))
    side="BUY" if direction=="LONG" else "SELL"
    close_side="SELL" if side=="BUY" else "BUY"
    cid=f"AUR-{int(time.time())}-{symbol[:5]}"
    entry_order=client.market_order(symbol,side,qty,cid)
    stop_order=client.stop_market(symbol,close_side,qty,stop,cid+"-SL")
    tp_order=client.take_profit_market(symbol,close_side,qty,tp1,cid+"-TP1")
    return {
        "mode":"BINANCE_DEMO","symbol":symbol,"direction":direction,"quantity":qty,
        "entry_order":entry_order,"stop_order":stop_order,"tp1_order":tp_order,
        "risk_pct":cfg["max_risk_per_trade_pct"],"max_leverage":cfg["max_leverage"],
    }
