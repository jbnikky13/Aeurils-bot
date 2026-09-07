"""Optional Gemini confirmation for already-measured market data.

Gemini is advisory only: it never supplies prices, indicators, wallet data,
or risk levels. API failures are returned as an explicit unavailable state so
callers can preserve deterministic market-data scoring.
"""
import json
import os
import httpx

URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"


def _unavailable(reason: str, status_code: int | None = None) -> dict:
    result = {
        "decision": "UNAVAILABLE",
        "confidence": None,
        "rationale": f"Gemini unavailable: {reason}",
        "invalidation": None,
        "available": False,
    }
    if status_code is not None:
        result["status_code"] = status_code
    return result


def confirm(symbol: str, technical_score: float, technical_bias: str,
            whale_score: float, whale_bias: str, price: float, atr: float) -> dict:
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        return _unavailable("GEMINI_API_KEY is not configured")

    prompt = f"""Analyze this trading setup using ONLY the supplied facts. Do not invent prices or data.
Symbol: {symbol}; price: {price}; technical_score: {technical_score}; technical_bias: {technical_bias}; whale_score: {whale_score}; whale_bias: {whale_bias}; ATR: {atr}.
Return JSON with decision (LONG, SHORT, WAIT), confidence (0-100), rationale, and invalidation. Treat conflicting evidence conservatively."""
    body = {"contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json"}}
    try:
        r = httpx.post(URL, params={"key": key}, json=body, timeout=30)
        r.raise_for_status()
        payload = r.json()
        text = payload["candidates"][0]["content"]["parts"][0]["text"]
        result = json.loads(text)
        if result.get("decision") not in {"LONG", "SHORT", "WAIT"}:
            raise ValueError("Invalid Gemini decision")
        result["confidence"] = max(0, min(100, float(result.get("confidence", 0))))
        result["available"] = True
        return result
    except httpx.HTTPStatusError as exc:
        return _unavailable(f"HTTP {exc.response.status_code}", exc.response.status_code)
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return _unavailable(type(exc).__name__)
