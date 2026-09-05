"""Promote discovery candidates only after quantitative + AI validation."""
from dataclasses import dataclass
from typing import Optional
import os
from .gem_finder import discover_gems, discover_small_caps
from .live_setup import crypto_setup

@dataclass
class GemCandidate:
    symbol: str
    name: str
    discovery_score: float
    technical_score: Optional[float]
    whale_score: Optional[float]
    final_score: float
    status: str
    reasons: list[str]


def _pair(symbol: str) -> str:
    return symbol.upper() + "USDT" if not symbol.upper().endswith("USDT") else symbol.upper()

async def scan_candidates(limit: int = 10) -> list[GemCandidate]:
    raw = discover_gems(limit) + discover_small_caps(limit)
    seen = set(); candidates = []
    for item in sorted(raw, key=lambda x: x.get("score", 0), reverse=True):
        symbol = item.get("symbol", "").upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        try:
            setup = await crypto_setup(_pair(symbol))
            technical = float(getattr(setup, "score", 0))
            whale = float(getattr(setup, "whale_score", 50))
            final = round(item["score"] * 0.35 + technical * 0.45 + whale * 0.20, 1)
            reasons = [f"discovery={item['score']:.1f}", f"technical={technical:.1f}", f"whale={whale:.1f}"]
            status = "WATCH" if final >= float(os.getenv("GEM_WATCH_SCORE", "65")) else "REJECT"
            candidates.append(GemCandidate(symbol, item.get("name", symbol), item["score"], technical, whale, final, status, reasons))
        except Exception as exc:
            candidates.append(GemCandidate(symbol, item.get("name", symbol), item["score"], None, None, 0.0, "UNVERIFIED", [str(exc)]))
    return sorted(candidates, key=lambda x: x.final_score, reverse=True)
