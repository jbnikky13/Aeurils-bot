import os
from dataclasses import dataclass
from typing import Literal
import httpx

Bias = Literal[-1, 0, 1]

@dataclass
class WhaleSummary:
    score: int
    bias: float
    events: int
    reasons: list[str]

ETHERSCAN = "https://api.etherscan.io/v2/api"

async def fetch_erc20_transfers(address: str, contract: str, chainid: int = 1, limit: int = 100) -> list[dict]:
    key = os.getenv("WHALE_API_KEY")
    if not key:
        raise RuntimeError("WHALE_API_KEY is not configured")
    params = {"chainid": chainid, "module": "account", "action": "tokentx", "contractaddress": contract, "address": address, "page": 1, "offset": limit, "sort": "desc", "apikey": key}
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(ETHERSCAN, params=params)
        r.raise_for_status()
        data = r.json()
    if str(data.get("status")) == "0":
        raise RuntimeError(data.get("message") or "Etherscan returned no transfer data")
    return data.get("result", []) if isinstance(data.get("result"), list) else []


def summarize_labeled_events(events: list[dict], exchange_addresses: set[str], whale_addresses: set[str]) -> WhaleSummary:
    score = 50
    bias = 0.0
    reasons: list[str] = []
    for e in events:
        src, dst = e.get("from", "").lower(), e.get("to", "").lower()
        is_whale_src, is_whale_dst = src in whale_addresses, dst in whale_addresses
        is_exchange_dst, is_exchange_src = dst in exchange_addresses, src in exchange_addresses
        if is_whale_src and is_exchange_dst:
            bias -= 0.25; score -= 8; reasons.append("Whale → exchange flow detected (distribution risk).")
        elif is_exchange_src and is_whale_dst:
            bias += 0.25; score += 8; reasons.append("Exchange → whale flow detected (accumulation signal).")
        elif is_whale_src and is_whale_dst:
            reasons.append("Whale → whale transfer detected; direction is ambiguous.")
    score = max(0, min(100, score))
    return WhaleSummary(score, max(-1.0, min(1.0, bias)), len(events), list(dict.fromkeys(reasons)))
