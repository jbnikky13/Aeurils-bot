"""Binance-native market-flow intelligence inspired by multi-module agent kits.
Read-only: no order execution. Uses spot depth plus Binance USD-M futures OI,
funding and taker flow to confirm (or reject) a 4H setup.
"""
import httpx

SPOT_BASE = "https://data-api.binance.vision"
FUTURES_BASE = "https://fapi.binance.com"


def _get(base, path, params=None):
    r = httpx.get(f"{base}{path}", params=params or {}, timeout=8)
    r.raise_for_status()
    return r.json()


def _clamp(v, lo=0.0, hi=100.0):
    return max(lo, min(hi, float(v)))


def snapshot(symbol: str, direction: str) -> dict:
    """Return a conservative flow score. Any unavailable component is neutral."""
    s = symbol.upper()
    result = {
        "available": False, "score": 50.0, "bias": 0.0,
        "oi_change_pct": None, "funding_rate": None,
        "orderbook_imbalance": None, "taker_ratio": None,
        "reasons": []
    }
    try:
        depth = _get(SPOT_BASE, "/api/v3/depth", {"symbol": s, "limit": 20})
        bids = sum(float(p) * float(q) for p, q in depth.get("bids", []))
        asks = sum(float(p) * float(q) for p, q in depth.get("asks", []))
        total = bids + asks
        imbalance = (bids - asks) / total if total else 0.0
        result["orderbook_imbalance"] = imbalance
    except Exception as exc:
        result["reasons"].append(f"Order book unavailable: {type(exc).__name__}")

    try:
        oi = _get(FUTURES_BASE, "/fapi/v1/openInterest", {"symbol": s})
        oi_now = float(oi.get("openInterest", 0))
        hist = _get(FUTURES_BASE, "/futures/data/openInterestHist", {
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
        funding = _get(FUTURES_BASE, "/fapi/v1/fundingRate", {"symbol": s, "limit": 1})
        if funding:
            result["funding_rate"] = float(funding[-1].get("fundingRate", 0))
    except Exception as exc:
        result["reasons"].append(f"Funding unavailable: {type(exc).__name__}")

    try:
        taker = _get(FUTURES_BASE, "/futures/data/takerlongshortRatio", {
            "symbol": s, "period": "4h", "limit": 1
        })
        if taker:
            result["taker_ratio"] = float(taker[-1].get("buySellRatio", 1.0))
    except Exception:
        # Endpoint availability varies by Binance market; remain neutral.
        pass

    score = 50.0
    bias = 0.0
    if result["orderbook_imbalance"] is not None:
        x = result["orderbook_imbalance"]
        bias += max(-1, min(1, x * 2.5)) * 0.30
        score += max(-20, min(20, x * 40)) * (1 if direction == "LONG" else -1)
    if result["oi_change_pct"] is not None:
        oi = result["oi_change_pct"]
        # Rising OI confirms the prevailing direction; falling OI weakens it.
        oi_sign = 1 if direction == "LONG" else -1
        bias += max(-1, min(1, oi / 5.0)) * oi_sign * 0.25
        score += max(-15, min(15, oi * 3)) * oi_sign
    if result["taker_ratio"] is not None:
        tr = result["taker_ratio"]
        taker_bias = max(-1, min(1, (tr - 1.0) * 2.5))
        bias += taker_bias * 0.30
        score += taker_bias * 20 if direction == "LONG" else -taker_bias * 20
    if result["funding_rate"] is not None:
        fr = result["funding_rate"]
        # Extreme positive funding is a contrarian warning for longs and vice versa.
        if direction == "LONG":
            score -= min(10, max(0, fr * 10000 - 5))
        elif direction == "SHORT":
            score -= min(10, max(0, -fr * 10000 - 5))

    result["score"] = round(_clamp(score), 1)
    result["bias"] = round(max(-1.0, min(1.0, bias)), 3)
    result["available"] = any(v is not None for v in (
        result["orderbook_imbalance"], result["oi_change_pct"], result["funding_rate"], result["taker_ratio"]
    ))
    if result["orderbook_imbalance"] is not None:
        result["reasons"].append(f"Spot depth imbalance: {result['orderbook_imbalance']:+.1%}")
    if result["oi_change_pct"] is not None:
        result["reasons"].append(f"4H OI change: {result['oi_change_pct']:+.2f}%")
    if result["funding_rate"] is not None:
        result["reasons"].append(f"Funding: {result['funding_rate']:+.5f}")
    if result["taker_ratio"] is not None:
        result["reasons"].append(f"Taker buy/sell ratio: {result['taker_ratio']:.2f}")
    return result
