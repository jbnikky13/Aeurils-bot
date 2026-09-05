"""Gemini confirmation for already-measured market data.
Gemini does not supply prices, indicators, wallet addresses, or risk levels."""
import json
import os
import httpx

URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"


def confirm(symbol: str, technical_score: float, technical_bias: str, whale_score: float, whale_bias: str, price: float, atr: float) -> dict:
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY is not configured")
    prompt = f"""Analyze this trading setup using ONLY the supplied facts. Do not invent prices or data.
Symbol: {symbol}; price: {price}; technical_score: {technical_score}; technical_bias: {technical_bias}; whale_score: {whale_score}; whale_bias: {whale_bias}; ATR: {atr}.
Return JSON with decision (LONG, SHORT, WAIT), confidence (0-100), rationale, and invalidation. Treat conflicting evidence conservatively."""
    body={"contents":[{"parts":[{"text":prompt}]}],"generationConfig":{"responseMimeType":"application/json"}}
    r=httpx.post(URL,params={"key":key},json=body,timeout=30); r.raise_for_status()
    text=r.json()["candidates"][0]["content"]["parts"][0]["text"]
    result=json.loads(text)
    if result.get("decision") not in {"LONG","SHORT","WAIT"}: raise ValueError("Invalid Gemini decision")
    result["confidence"]=max(0,min(100,float(result.get("confidence",0))))
    return result
