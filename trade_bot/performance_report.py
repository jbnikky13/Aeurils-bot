"""Daily performance report for Telegram and scheduled jobs."""
from .performance import summary

def build_report():
    s = summary()
    closed = s["wins"] + s["losses"]
    lines = ["📈 AURELIS DAILY PERFORMANCE", "", f"Closed signals: {s['total_closed']}", f"Open signals: {s['open']}", f"Wins: {s['wins']}", f"Losses: {s['losses']}", f"Win rate: {s['win_rate']:.1f}%" if closed else "Win rate: N/A (no closed trades)"]
    if s["breakdown"]:
        lines += ["", "Outcome / asset:"]
        lines += [f"• {outcome} / {asset}: {count}" for outcome, asset, count in s["breakdown"]]
    lines += ["", "⚠️ Journal statistics are historical observations, not a guarantee of future performance."]
    return "\n".join(lines)
