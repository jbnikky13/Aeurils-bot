"""Weighted AURELIS signal scoring.

The old gate required six confirmations simultaneously, which could discard
useful developing setups. This module keeps critical risk/data checks hard,
while using a 100-point weighted score for the remaining evidence.

Tiers:
  80-100 A+ TRADE
  70-79  A TRADE
  60-69  EARLY SETUP / WATCH
  <60    REJECTED

This module only classifies paper/signal candidates. It never executes orders.
"""
import os

MIN_CONFLUENCES = int(os.getenv("MIN_CONFLUENCES", "6"))  # legacy compatibility
TRADE_THRESHOLD = int(os.getenv("AURELIS_TRADE_THRESHOLD", "70"))
EARLY_THRESHOLD = int(os.getenv("AURELIS_EARLY_THRESHOLD", "60"))
MIN_RR = float(os.getenv("AURELIS_MIN_RR", "1.5"))

OFFCHAIN_KEYS = (
    "trend_structure", "direction", "entry_range", "risk_reward",
    "volume_liquidity", "market_regime", "sentiment_narrative", "news_context",
)
ONCHAIN_KEYS = (
    "onchain_dex_activity", "buy_sell_pressure", "liquidity_depth",
    "whale_activity", "exchange_flows", "smart_money", "holder_concentration",
)

# Exactly 100 points. A provider confirmation adds points without being mandatory.
WEIGHTS = {
    "trend_structure": 20,
    "direction": 15,
    "entry_range": 10,
    "risk_reward": 10,
    "volume_liquidity": 10,
    "market_regime": 10,
    "momentum": 10,
    "sentiment_narrative": 5,
    "news_context": 5,
    "onchain_confirmation": 5,
}


def _truthy(value):
    return value is True or (isinstance(value, (int, float)) and value > 0)


def evaluate(signal, onchain=None, offchain=None):
    """Return score, tier, diagnostics and backward-compatible confluence data."""
    onchain = onchain or {}
    offchain = offchain or {}

    direction = getattr(signal, "direction", "WAIT")
    entry_ok = getattr(signal, "entry_low", None) is not None and getattr(signal, "entry_high", None) is not None
    sl_ok = getattr(signal, "stop_loss", None) is not None
    tp_ok = getattr(signal, "take_profit_1", None) is not None
    rr = float(getattr(signal, "risk_reward", 0) or 0)

    checks = [
        ("trend_structure", float(getattr(signal, "score", 0) or 0) >= 60, "Trend / market structure"),
        ("direction", direction != "WAIT", "Directional setup"),
        ("entry_range", entry_ok, "Defined entry range"),
        ("risk_reward", sl_ok and tp_ok and rr >= MIN_RR, f"Risk/reward >= {MIN_RR:g}"),
        ("volume_liquidity", _truthy(offchain.get("volume_liquidity")), "Volume / liquidity"),
        ("market_regime", _truthy(offchain.get("market_regime")), "Market regime"),
        ("momentum", float(getattr(signal, "technical_score", 0) or 0) >= 60, "Technical momentum"),
        ("sentiment_narrative", _truthy(offchain.get("sentiment_narrative")), "Sentiment / narrative"),
        ("news_context", _truthy(offchain.get("news_context")), "News context"),
    ]

    # Any positive on-chain evidence contributes one bounded 5-point bucket.
    onchain_passed = [k for k in ONCHAIN_KEYS if _truthy(onchain.get(k))]
    checks.append(("onchain_confirmation", bool(onchain_passed), "On-chain confirmation"))

    points = {key: WEIGHTS[key] for key, ok, _ in checks if ok}
    score = min(100, int(round(sum(points.values()))))
    passed = [x for x in checks if x[1]]
    unknown = [
        k.replace("_", " ").title()
        for k in set(OFFCHAIN_KEYS + ONCHAIN_KEYS)
        if k not in {x[0] for x in checks}
    ]

    # Critical risk/data failures always block a trade tier.
    hard_block = direction == "WAIT" or not entry_ok or not sl_ok or not tp_ok or rr < MIN_RR
    if hard_block:
        tier = "REJECTED" if direction == "WAIT" else "EARLY_SETUP"
    elif score >= 80:
        tier = "A_PLUS"
    elif score >= TRADE_THRESHOLD:
        tier = "A_SETUP"
    elif score >= EARLY_THRESHOLD:
        tier = "EARLY_SETUP"
    else:
        tier = "REJECTED"

    actionable = tier in ("A_PLUS", "A_SETUP") and not hard_block
    return {
        "passed": len(passed),
        "minimum": MIN_CONFLUENCES,
        "score": score,
        "tier": tier,
        "actionable": actionable,
        "confluences": [x[2] for x in passed],
        "checks": checks,
        "failed": [x[2] for x in checks if not x[1]],
        "unknown": unknown,
        "points": points,
        "onchain_evidence": onchain_passed,
        "trade_threshold": TRADE_THRESHOLD,
        "early_threshold": EARLY_THRESHOLD,
        "hard_block": hard_block,
    }
