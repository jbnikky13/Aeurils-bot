"""Gemini-assisted wallet candidate curator.
Gemini is advisory only; candidates must be independently verified.
"""
import json, os, re, httpx
ADDRESS_RE=re.compile(r"^0x[a-fA-F0-9]{40}$")
GEMINI_URL="https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"

def discover_candidates(chain="ethereum"):
    key=os.getenv("GEMINI_API_KEY")
    if not key: raise RuntimeError("GEMINI_API_KEY is not configured")
    prompt=(f"Return JSON only. Identify publicly documented {chain} wallet addresses that are likely "
            "major exchange wallets or well-known high-balance/whale wallets. Never guess or invent addresses. "
            "Each item must contain address, entity, kind (whale|exchange), confidence (0-1), and evidence.")
    schema={"type":"object","properties":{"candidates":{"type":"array","items":{"type":"object","properties":{
        "address":{"type":"string"},"entity":{"type":"string"},"kind":{"type":"string","enum":["whale","exchange"]},
        "confidence":{"type":"number","minimum":0,"maximum":1},"evidence":{"type":"string"}},"required":["address","entity","kind","confidence","evidence"]}}},"required":["candidates"]}
    body={"contents":[{"parts":[{"text":prompt}]}],"generationConfig":{"responseMimeType":"application/json","responseSchema":schema}}
    r=httpx.post(GEMINI_URL,headers={"x-goog-api-key":key},json=body,timeout=30); r.raise_for_status()
    payload=json.loads(r.json()["candidates"][0]["content"]["parts"][0]["text"])
    return [x for x in payload.get("candidates",[]) if ADDRESS_RE.fullmatch(str(x.get("address",""))) and x.get("kind") in {"whale","exchange"}]
