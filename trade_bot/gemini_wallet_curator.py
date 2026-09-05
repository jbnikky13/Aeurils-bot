"""Gemini-assisted wallet candidate curator.

Gemini never writes wallets directly to the trusted registry. Candidates must
be validated and explicitly promoted by the verification layer.
"""
import json
import os
import re
import httpx

ADDRESS_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"


def discover_candidates(chain: str = "ethereum") -> list[dict]:
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY is not configured")
    prompt = (
        "Return JSON only with key candidates, an array of candidate public wallet entities "
        f"for {chain}. Each item must contain address, entity, kind (whale|exchange), "
        "confidence (0-1), and evidence. Never invent an address. Only include addresses "
        "you can identify with high confidence from your learned/public knowledge."
    )
    body = {"contents":[{"parts":[{"text":prompt}]}], "generationConfig":{"responseMimeType":"application/json"}}
    r = httpx.post(GEMINI_URL, params={"key": key}, json=body, timeout=30)
    r.raise_for_status()
    text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
    payload = json.loads(text)
    out = []
    for item in payload.get("candidates", []):
        address = str(item.get("address", "")).strip()
        confidence = float(item.get("confidence", 0))
        if ADDRESS_RE.fullmatch(address) and 0 <= confidence <= 1:
            kind = item.get("kind")
            if kind in {"whale", "exchange"}:
                out.append({"address":address.lower(), "entity":item.get("entity","unknown"), "kind":kind, "confidence":confidence, "evidence":item.get("evidence","")})
    return out
