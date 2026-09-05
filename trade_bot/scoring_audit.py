"""Helpers for explaining and auditing signal scores."""

def audit_payload(signal, regime="UNKNOWN"):
    return {
        "symbol": getattr(signal,"symbol",None), "direction": getattr(signal,"direction",None),
        "technical_score": getattr(signal,"technical_score",None), "whale_score": getattr(signal,"whale_score",None),
        "sentiment_score": getattr(signal,"sentiment_score",None), "final_score": getattr(signal,"score",None),
        "regime": regime, "risk_reward": getattr(signal,"risk_reward",None),
        "gemini_confidence": getattr(signal,"gemini_confidence",None),
        "gemini_decision": getattr(signal,"gemini_decision",None),
    }

def explain(audit):
    parts=[]
    if audit.get("technical_score") is not None: parts.append(f"technical {audit['technical_score']}")
    if audit.get("whale_score") is not None: parts.append(f"whale {audit['whale_score']}")
    if audit.get("sentiment_score") is not None: parts.append(f"sentiment {audit['sentiment_score']}")
    if audit.get("gemini_decision"): parts.append(f"Gemini {audit['gemini_decision']}")
    return " | ".join(parts)
