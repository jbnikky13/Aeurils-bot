"""Binance-native futures market-flow intelligence for AURELIS.

Read-only: no order execution. Uses Binance USD-M futures depth, OI, funding,
taker flow and optional liquidation pressure to confirm a 4H setup.
"""
import httpx

FUTURES_BASE = "https://fapi.binance.com"


def _get(path, params=None):
    r = httpx.get(f"{FUTURES_BASE}{path}", params=params or {}, timeout=8)
    r.raise_for_status()
    return r.json()


def _clamp(v, lo=0.0, hi=100.0):
    return max(lo, min(hi, float(v)))


def snapshot(symbol: str, direction: str) -> dict:
    """Return conservative futures-flow evidence; unavailable providers remain neutral."""
    s = symbol.upper()
    result = {
        "available": False, "score": 50.0, "bias": 0.0,
        "oi_change_pct": None, "funding_rate": None,
        "orderbook_imbalance": None, "taker_ratio": None,
        "price_change_pct": None, "liquidation_pressure": False,
        "reasons": []
    }

    try:
        depth = _get("/fapi/v1/depth", {"symbol": s, "limit": 20})
        bids = sum(float(p) * float(q) for p, q in depth.get("bids", []))
        asks = sum(float(p) * float(q) for p, q in depth.get("asks", []))
        total = bids + asks
        result["orderbook_imbalance"] = (bids - asks) / total if total else 0.0
    except Exception as exc:
        result["reasons"].append(f"Futures order book unavailable: {type(exc).__name__}")

    try:
        oi = _get("/fapi/v1/openInterest", {"symbol": s})
        oi_now = float(oi.get("openInterest", 0))
        hist = _get("/futures/data/openInterestHist", {
            "symbol": s, "period": "4h", "limit": 3, "contractType": "PERPETUAL"
        })
        if len(hist) >= 2:
            old = float(hist[-2].get("sumOpenInterest", 0))
            new = float(hist[-1].get("sumOpenInterest", oi_now))
            if old:
                result["oi_change_pct"] = (new - old) / old * 100.0
    except Exception as exc:
        result["reasons"].append(f"Open interest unavailable: {type(exc).__name__}")

    try:
        candles = _get("/fapi/v1/klines", {"symbol": s, "interval": "4h", "limit": 2})
        if len(candles) >= 2:
            old_close = float(candles[-2][4]); new_close = float(candles[-1][4])
            if old_close:
                result["price_change_pct"] = (new_close - old_close) / old_close * 100.0
    except Exception as exc:
        result["reasons"].append(f"4H price/OI relationship unavailable: {type(exc).__name__}")

    try:
        funding = _get("/fapi/v1/fundingRate", {"symbol": s, "limit": 1})
        if funding:
            result["funding_rate"] = float(funding[-1].get("fundingRate", 0))
    except Exception as exc:
        result["reasons"].append(f"Funding unavailable: {type(exc).__name__}")

    try:
        taker = _get("/futures/data/takerlongshortRatio", {"symbol": s, "period": "4h", "limit": 1})
        if taker:
            result["taker_ratio"] = float(taker[-1].get("buySellRatio", 1.0))
    except Exception:
        pass

    try:
        forced = _get("/fapi/v1/allForceOrders", {"symbol": s, "limit": 100})
        recent = forced if isinstance(forced, list) else []
        long_liq = sum(float(x.get("executedQty", 0)) for x in recent if str(x.get("side", "")).upper() == "SELL")
        short_liq = sum(float(x.get("executedQty", 0)) for x in recent if str(x.get("side", "")).upper() == "BUY")
        if direction == "SHORT" and long_liq > short_liq * 1.25 and long_liq > 0:
            result["liquidation_pressure"] = True
        elif direction == "LONG" and short_liq > long_liq * 1.25 and short_liq > 0:
            result["liquidation_pressure"] = True
    except Exception:
        # Liquidation endpoint availability is not a hard dependency.
        pass

    score = 50.0
    bias = 0.0
    imbalance = result["orderbook_imbalance"]
    if imbalance is not None:
        directional = imbalance if direction == "LONG" else -imbalance
        bias += max(-1, min(1, directional * 2.5)) * 0.25
        score += max(-18, min(18, directional * 36))

    oi = result["oi_change_pct"]
    price_change = result["price_change_pct"]
    if oi is not None:
        # Price and OI together distinguish trend participation from liquidation.
        if price_change is not None:
            same_direction = (price_change > 0 and direction == "LONG") or (price_change < 0 and direction == "SHORT")
            opposing_direction = (price_change < 0 and direction == "LONG") or (price_change > 0 and direction == "SHORT")
            if same_direction and oi > 0.5:
                bias += 0.25; score += 14
            elif opposing_direction and oi > 0.5:
                bias -= 0.25; score -= 14
            elif oi < -0.5:
                score += 3 if same_direction else -3
        elif oi > 0.5:
            score += 6
        bias = max(-1, min(1, bias))

    tr = result["taker_ratio"]
    if tr is not None:
        taker_bias = max(-1, min(1, (tr - 1.0) * 2.5))
        directional = taker_bias if direction == "LONG" else -taker_bias
        bias += directional * 0.30
        score += directional * 18

    fr = result["funding_rate"]
    if fr is not None:
        # Extreme funding against the proposed trade is a warning, not a veto.
        if direction == "LONG" and fr > 0.0005: score -= 7
        if direction == "SHORT" and fr < -0.0005: score -= 7

    if result["liquidation_pressure"]:
        score += 8
        bias += 0.10

    result["score"] = round(_clamp(score), 1)
    result["bias"] = round(max(-1.0, min(1.0, bias)), 3)
    result["available"] = any(v is not None for v in (
        result["orderbook_imbalance"], result["oi_change_pct"], result["funding_rate"],
        result["taker_ratio"], result["price_change_pct"]
    ))
    if imbalance is not None: result["reasons"].append(f"Futures depth imbalance: {imbalance:+.1%}")
    if price_change is not None: result["reasons"].append(f"4H futures price change: {price_change:+.2f}%")
    if oi is not None: result["reasons"].append(f"4H OI change: {oi:+.2f}%")
    if fr is not None: result["reasons"].append(f"Funding: {fr:+.5f}")
    if tr is not None: result["reasons"].append(f"Taker buy/sell ratio: {tr:.2f}")
    if result["liquidation_pressure"]: result["reasons"].append("Liquidation pressure confirms the directional move")
    return result
