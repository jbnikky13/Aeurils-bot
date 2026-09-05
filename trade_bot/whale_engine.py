from dataclasses import dataclass
from typing import Literal

Flow = Literal["ACCUMULATION", "DISTRIBUTION", "MIXED", "UNKNOWN"]

@dataclass
class WhaleEvent:
    asset: str
    amount_usd: float
    source_type: str
    destination_type: str
    flow: Flow
    confidence: int
    note: str


def classify_flow(source_type: str, destination_type: str) -> Flow:
    source, destination = source_type.lower(), destination_type.lower()
    if "exchange" in destination and "exchange" not in source: return "DISTRIBUTION"
    if "exchange" in source and "exchange" not in destination: return "ACCUMULATION"
    if source == "whale" and destination == "whale": return "MIXED"
    return "UNKNOWN"


def whale_bias(events: list[WhaleEvent]) -> tuple[float, int]:
    if not events: return 0.0, 50
    weighted = total = 0.0
    for event in events:
        weight = max(0.0, event.amount_usd) * (event.confidence / 100)
        sign = 1 if event.flow == "ACCUMULATION" else -1 if event.flow == "DISTRIBUTION" else 0
        weighted += sign * weight
        total += weight
    bias = weighted / total if total else 0.0
    return max(-1.0, min(1.0, bias)), round(50 + 50 * bias)
