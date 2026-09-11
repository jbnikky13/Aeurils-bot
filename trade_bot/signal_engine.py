from dataclasses import dataclass
from typing import Literal

Direction = Literal["LONG", "SHORT", "WAIT"]
MAX_HOLD_HOURS = 24.0
MAX_ENTRY_EXTENSION_ATR = 0.85

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
    tp1_eta_hours: float | None = None
    tp2_eta_hours: float | None = None
    horizon_status: str = "UNKNOWN"
    max_hold_hours: float = MAX_HOLD_HOURS
    entry_status: str = "UNKNOWN"
    entry_quality: float | None = None


def combine_scores(technical: float, whale: float, sentiment: float) -> int:
    return max(0, min(100, round(0.55 * technical + 0.30 * whale + 0.15 * sentiment)))


def direction_from_components(technical_bias: float, whale_bias: float) -> Direction:
    bias = 0.65 * technical_bias + 0.35 * whale_bias
    if bias >= 0.20: return "LONG"
    if bias <= -0.20: return "SHORT"
    return "WAIT"


def _eta_hours(distance: float, atr: float, asset_type: str) -> float | None:
    if distance <= 0 or atr <= 0: return None
    return distance / atr if asset_type == "crypto" else (distance / atr) * 24.0


def build_setup(symbol: str, asset_type: str, price: float, technical_score: int, whale_score: int,
                sentiment_score: float, technical_bias: float, whale_bias: float, atr: float,
                market_regime: str = "UNKNOWN", ema20: float | None = None,
                recent_high: float | None = None, recent_low: float | None = None,
                rsi: float | None = None) -> Signal:
    direction = direction_from_components(technical_bias, whale_bias)
    score = combine_scores(technical_score, whale_score, sentiment_score)
    if direction == "WAIT" or score < 60 or atr <= 0:
        return Signal(symbol, asset_type, "WAIT", score, None, None, None, None, None, None,
                      technical_score, whale_score, sentiment_score, ["No sufficiently strong directional setup."],
                      "Wait for confirmation.", market_regime, whale_bias=whale_bias)

    # Do not chase candles that have already moved too far from the trend anchor.
    # The signal becomes WAIT instead of publishing an entry that is likely to be missed.
    entry_anchor = float(ema20) if ema20 is not None else float(price)
    extension_atr = abs(price - entry_anchor) / atr if atr > 0 else 999.0
    entry_quality = max(0.0, 100.0 - (extension_atr / MAX_ENTRY_EXTENSION_ATR) * 100.0)
    if ema20 is not None and extension_atr > MAX_ENTRY_EXTENSION_ATR:
        return Signal(symbol, asset_type, "WAIT", score, None, None, None, None, None, None,
                      technical_score, whale_score, sentiment_score,
                      [f"Entry rejected: price is {extension_atr:.2f} ATR from EMA20; avoid chasing."],
                      "Wait for a pullback/retest toward the entry zone.", market_regime,
                      whale_bias=whale_bias, entry_status="EXTENDED", entry_quality=entry_quality)

    # Entry zone is centered on the current tradable price but narrowed by ATR.
    # This gives the signal a realistic fill zone instead of a stale exact price.
    zone = min(0.003, max(0.001, 0.20 * atr / price))
    entry_low, entry_high = price * (1 - zone), price * (1 + zone)

    if direction == "LONG":
        stop, tp1, tp2 = price - 1.5 * atr, price + 2.0 * atr, price + 3.0 * atr
    else:
        stop, tp1, tp2 = price + 1.5 * atr, price - 2.0 * atr, price - 3.0 * atr

    risk, reward = abs(price - stop), abs(tp2 - price)
    tp1_eta = _eta_hours(abs(tp1 - price), atr, asset_type)
    tp2_eta = _eta_hours(abs(tp2 - price), atr, asset_type)
    horizon_status = "WITHIN_24H" if tp1_eta is not None and tp1_eta <= MAX_HOLD_HOURS else "OVER_24H"

    reasons = [
        f"Technical score: {technical_score}/100",
        f"Whale-flow score: {whale_score}/100",
        f"Sentiment score: {sentiment_score}/100",
        f"Market regime: {market_regime}",
        f"Entry quality: {entry_quality:.0f}/100 ({extension_atr:.2f} ATR from EMA20)" if ema20 is not None else "Entry quality: current-price zone",
        f"Estimated TP1: {tp1_eta:.1f}h" if tp1_eta is not None else "Estimated TP1: unavailable",
        f"Estimated TP2: {tp2_eta:.1f}h" if tp2_eta is not None else "Estimated TP2: unavailable",
        "TP1 horizon: within 24h" if horizon_status == "WITHIN_24H" else "⚠️ TP1 horizon exceeds 24h — extended setup",
    ]
    return Signal(symbol, asset_type, direction, score, entry_low, entry_high, stop, tp1, tp2,
                  reward / risk if risk else None, technical_score, whale_score, sentiment_score,
                  reasons, f"Invalid if price breaks the {direction.lower()} stop-loss level.",
                  market_regime, whale_bias=whale_bias, tp1_eta_hours=tp1_eta, tp2_eta_hours=tp2_eta,
                  horizon_status=horizon_status, entry_status="READY", entry_quality=entry_quality)
