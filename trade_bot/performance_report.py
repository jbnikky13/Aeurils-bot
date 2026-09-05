"""Daily performance and scoring-audit report for Telegram."""
from .performance import summary
from .journal import audit_stats

def build_report():
    s=summary(); closed=s["wins"]+s["losses"]
    lines=["📈 AURELIS DAILY PERFORMANCE","",f"Closed signals: {s['total_closed']}",f"Open signals: {s['open']}",f"Wins: {s['wins']}",f"Losses: {s['losses']}",f"Win rate: {s['win_rate']:.1f}%" if closed else "Win rate: N/A (no closed trades)"]
    if s["breakdown"]: lines += ["","Outcome / asset:"]+[f"• {o} / {a}: {n}" for o,a,n in s["breakdown"]]
    audits=audit_stats()
    if audits:
        lines += ["","🔎 SCORING AUDIT"]
        for r in audits[:12]:
            lines.append(f"• {r['market_regime']} / {r['asset_type']} / {r['outcome']}: n={r['count']} | final {r['avg_score']} | tech {r['avg_technical']} | whale {r['avg_whale']} | sentiment {r['avg_sentiment']}")
    lines += ["","⚠️ Historical observations only; not a guarantee of future performance."]
    return "\n".join(lines)
