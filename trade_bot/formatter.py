from .signal_engine import Signal


def money(value: float | None) -> str:
    return "—" if value is None else f"${value:,.4f}" if value < 10 else f"${value:,.2f}"


def format_signal(s: Signal) -> str:
    emoji = "🟢" if s.direction == "LONG" else "🔴" if s.direction == "SHORT" else "⚪"
    lines = [f"{emoji} {s.symbol} — {s.direction}", f"Signal strength: {s.score}/100"]
    if s.direction != "WAIT":
        lines += [f"Entry: {money(s.entry_low)} – {money(s.entry_high)}", f"Stop loss: {money(s.stop_loss)}", f"TP1: {money(s.take_profit_1)}", f"TP2: {money(s.take_profit_2)}", f"Risk/Reward: 1:{s.risk_reward:.2f}" if s.risk_reward else "Risk/Reward: —"]
    lines += [f"📈 Technical: {s.technical_score}/100", f"🐋 Whale flow: {s.whale_score}/100", f"📰 Sentiment: {s.sentiment_score}/100", "Why: " + "; ".join(s.reasons), f"⚠️ {s.invalidation}"]
    return "\n".join(lines)
