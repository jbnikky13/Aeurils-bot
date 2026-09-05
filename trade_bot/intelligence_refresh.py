"""Refresh public wallet/token intelligence with Gemini candidates and hard validation.
Gemini is advisory only; it never promotes addresses into the trusted registry.
"""
import asyncio
import json
import os
import re
from pathlib import Path
import httpx
from .gemini_wallet_curator import discover_candidates
from .wallet_registry import load_registry, save_registry

ADDR = re.compile(r"^0x[a-fA-F0-9]{40}$")
ETHERSCAN = "https://api.etherscan.io/v2/api"

async def verify_address(address: str) -> bool:
    key = os.getenv("WHALE_API_KEY")
    if not key or not ADDR.fullmatch(address): return False
    params={"chainid":"1","module":"account","action":"txlist","address":address,"page":"1","offset":"1","sort":"desc","apikey":key}
    async with httpx.AsyncClient(timeout=20) as client:
        r=await client.get(ETHERSCAN,params=params); r.raise_for_status(); data=r.json()
    return data.get("status") in {"0","1"} and isinstance(data.get("result"),list)

async def refresh() -> dict:
    candidates=await asyncio.to_thread(discover_candidates)
    registry=load_registry()
    accepted=[]
    for c in candidates:
        if c["confidence"] < float(os.getenv("WALLET_MIN_CONFIDENCE","0.85")): continue
        if await verify_address(c["address"]):
            bucket="whales" if c["kind"]=="whale" else "exchanges"
            registry.setdefault(bucket,{})[c["address"]]={"entity":c["entity"],"confidence":c["confidence"],"evidence":c["evidence"],"verified_by":"etherscan","updated_at":__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()}
            accepted.append(c["address"])
    save_registry(registry)
    return {"candidates":len(candidates),"accepted":len(accepted),"accepted_addresses":accepted}

if __name__ == "__main__": print(json.dumps(asyncio.run(refresh()),indent=2))
