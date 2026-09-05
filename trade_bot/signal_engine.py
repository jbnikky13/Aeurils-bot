from dataclasses import dataclass
from typing import Literal

Direction = Literal["LONG", "SHORT", "WAIT"]

@dataclass
class Signal:
    symbol: str
    asset_type: str
    direction: Direction
    score: int
    entry_low: float | None
    entry_high: float | None
    stop_loss: float | None
    take_profit_1: float | None
    take_profit_2: float | None
    risk_reward: float | None
    technical_score: int
    whale_score: int
    sentiment_score: int
    reasons: list[str]
    invalidation: str
    market_regime: str = "UNKNOWN"
    gemini_confidence: float | None = None
    gemini_decision: str | None = None
    gemini_rationale: str | None = None
    whale_bias: float | None = None


def combine_scores(technical: float, whale: float, sentiment: float) -> int:
    return max(0, min(100, round(0.55 * technical + 0.30 * whale + 0.15 * sentiment)))

def direction_from_components(technical_bias: float, whale_bias: float) -> Direction:
    bias = 0.65 * technical_bias + 0.35 * whale_bias
    if bias >= 0.20: return "LONG"
    if bias <= -0.20: return "SHORT"
    return "WAIT"

def build_setup(symbol: str, asset_type: str, price: float, technical_score: int, whale_score: int, sentiment_score: int, technical_bias: float, whale_bias: float, atr: float, market_regime: str = "UNKNOWN") -> Signal:
    direction = direction_from_components(technical_bias, whale_bias)
    score = combine_scores(technical_score, whale_score, sentiment_score)
    if direction == "WAIT" or score < 70:
        return Signal(symbol, asset_type, "WAIT", score, None, None, None, None, None, None, technical_score, whale_score, sentiment_score, ["No sufficiently strong multi-factor setup."], "Wait for confirmation.", market_regime, whale_bias=whale_bias)
    entry_low, entry_high = price * 0.997, price * 1.003
    if direction == "LONG": stop, tp1, tp2 = price - 1.5 * atr, price + 2.0 * atr, price + 3.0 * atr
    else: stop, tp1, tp2 = price + 1.5 * atr, price - 2.0 * atr, price - 3.0 * atr
    risk, reward = abs(price - stop), abs(tp2 - price)
    return Signal(symbol, asset_type, direction, score, entry_low, entry_high, stop, tp1, tp2, reward / risk if risk else None, technical_score, whale_score, sentiment_score, [f"Technical score: {technical_score}/100", f"Whale-flow score: {whale_score}/100", f"Sentiment score: {sentiment_score}/100", f"Market regime: {market_regime}"], f"Invalid if price breaks the {direction.lower()} stop-loss level.", market_regime, whale_bias=whale_bias)
