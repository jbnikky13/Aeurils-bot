"""Binance USD-M Futures Demo/Testnet execution adapter for AURELIS.

SAFETY:
- This adapter is opt-in via EXECUTION_MODE=BINANCE_DEMO.
- It refuses production Binance endpoints.
- It requires BINANCE_DEMO_API_KEY/SECRET.
- It is intentionally separate from the paper trader.
- No live-trading mode is implemented here.
"""
from __future__ import annotations
import hashlib, hmac, os, time
from urllib.parse import urlencode
import httpx

DEMO_BASE = os.getenv("BINANCE_DEMO_BASE_URL", "https://testnet.binancefuture.com").rstrip("/")
API_KEY = os.getenv("BINANCE_DEMO_API_KEY", "")
API_SECRET = os.getenv("BINANCE_DEMO_API_SECRET", "")
RECV_WINDOW = int(os.getenv("BINANCE_DEMO_RECV_WINDOW", "5000"))
MAX_LEVERAGE = int(os.getenv("BINANCE_DEMO_MAX_LEVERAGE", "3"))


class DemoTradingDisabled(RuntimeError):
    pass


class BinanceDemoClient:
    def __init__(self):
        mode=os.getenv("EXECUTION_MODE","PAPER").upper()
        if mode != "BINANCE_DEMO":
            raise DemoTradingDisabled("Set EXECUTION_MODE=BINANCE_DEMO to use Binance demo trading.")
        if "testnet.binancefuture.com" not in DEMO_BASE:
            raise DemoTradingDisabled("Refusing non-testnet Binance endpoint.")
        if not API_KEY or not API_SECRET:
            raise DemoTradingDisabled("BINANCE_DEMO_API_KEY and BINANCE_DEMO_API_SECRET are required.")

    def _signed(self, method, path, params=None):
        params=dict(params or {})
        params["timestamp"]=int(time.time()*1000)
        params["recvWindow"]=RECV_WINDOW
        query=urlencode(params)
        sig=hmac.new(API_SECRET.encode(),query.encode(),hashlib.sha256).hexdigest()
        headers={"X-MBX-APIKEY":API_KEY}
        with httpx.Client(timeout=20) as client:
            r=client.request(method,f"{DEMO_BASE}{path}?{query}&signature={sig}",headers=headers)
            r.raise_for_status()
            return r.json()

    def ping(self):
        with httpx.Client(timeout=10) as client:
            r=client.get(f"{DEMO_BASE}/fapi/v1/ping")
            r.raise_for_status()
            return r.json()

    def account(self):
        return self._signed("GET","/fapi/v2/account")

    def exchange_info(self):
        return self._signed("GET","/fapi/v1/exchangeInfo") if False else self._public("GET","/fapi/v1/exchangeInfo")

    def _public(self, method, path, params=None):
        with httpx.Client(timeout=20) as client:
            r=client.request(method,f"{DEMO_BASE}{path}",params=params or {})
            r.raise_for_status()
            return r.json()

    def position_risk(self, symbol=None):
        return self._signed("GET","/fapi/v2/positionRisk", {"symbol":symbol} if symbol else {})

    def set_leverage(self, symbol, leverage):
        leverage=max(1,min(int(leverage),MAX_LEVERAGE))
        return self._signed("POST","/fapi/v1/leverage",{"symbol":symbol.upper(),"leverage":leverage})

    def market_order(self, symbol, side, quantity, client_order_id):
        if side.upper() not in {"BUY","SELL"}:
            raise ValueError("side must be BUY or SELL")
        return self._signed("POST","/fapi/v1/order",{
            "symbol":symbol.upper(),"side":side.upper(),"type":"MARKET",
            "quantity":quantity,"newClientOrderId":client_order_id,
            "newOrderRespType":"RESULT",
        })

    def stop_market(self, symbol, side, quantity, stop_price, client_order_id):
        return self._signed("POST","/fapi/v1/order",{
            "symbol":symbol.upper(),"side":side.upper(),"type":"STOP_MARKET",
            "stopPrice":stop_price,"quantity":quantity,
            "reduceOnly":"true","workingType":"MARK_PRICE",
            "newClientOrderId":client_order_id,
        })

    def take_profit_market(self, symbol, side, quantity, stop_price, client_order_id):
        return self._signed("POST","/fapi/v1/order",{
            "symbol":symbol.upper(),"side":side.upper(),"type":"TAKE_PROFIT_MARKET",
            "stopPrice":stop_price,"quantity":quantity,
            "reduceOnly":"true","workingType":"MARK_PRICE",
            "newClientOrderId":client_order_id,
        })
