"""Human-approved calibration recommendations.
This module NEVER changes live strategy settings.
"""
import os, sqlite3, math
from collections import defaultdict
DB=os.getenv("DATABASE_PATH","trade_bot.db")
MIN_SAMPLE=int(os.getenv("CALIBRATION_MIN_SAMPLE","30"))
MIN_GROUP=int(os.getenv("CALIBRATION_MIN_GROUP_SAMPLE","10"))


def _closed():
    con=sqlite3.connect(DB); con.row_factory=sqlite3.Row
    try: rows=con.execute("select * from paper_trades where exit_price is not null").fetchall()
    except sqlite3.Error: rows=[]
    con.close(); return rows

def _summary(rows):
    p=[float(r["pnl_pct"] or 0) for r in rows]
    return {"n":len(p),"win_rate":100*sum(x>0 for x in p)/len(p) if p else 0.0,"expectancy":sum(p)/len(p) if p else 0.0,"pnl":sum(p)}

def recommend():
    rows=_closed()
    if len(rows)<MIN_SAMPLE:
        return {"status":"INSUFFICIENT_DATA","closed":len(rows),"minimum":MIN_SAMPLE,"recommendations":[]}
    regimes=defaultdict(list); scores=defaultdict(list)
    for r in rows:
        regime=r["market_regime"] if "market_regime" in r.keys() and r["market_regime"] else "UNKNOWN"; regimes[regime].append(r)
        if "final_score" in r.keys() and r["final_score"] is not None:
            s=float(r["final_score"]); scores[int(s//10)*10].append(r)
    overall=_summary(rows); rec=[]
    for name,group in regimes.items():
        if len(group)>=MIN_GROUP:
            s=_summary(group)
            if s["expectancy"] < 0 and s["win_rate"] < overall["win_rate"]:
                rec.append({"type":"REVIEW_REGIME","segment":name,"reason":"Negative expectancy and below overall win rate","evidence":s})
            elif s["expectancy"] > overall["expectancy"] and s["win_rate"] > overall["win_rate"]:
                rec.append({"type":"POSITIVE_REGIME","segment":name,"reason":"Outperforms overall baseline; preserve and investigate","evidence":s})
    for bucket,group in sorted(scores.items()):
        if len(group)>=MIN_GROUP:
            s=_summary(group)
            if s["expectancy"] < 0: rec.append({"type":"REVIEW_SCORE_BUCKET","segment":f"{bucket}-{bucket+9}","reason":"Negative expectancy; review threshold evidence","evidence":s})
    return {"status":"REVIEW_READY","closed":len(rows),"overall":overall,"recommendations":rec}

def format_report():
    a=recommend(); lines=["🧠 AURELIS CALIBRATION DECISION ENGINE","",f"Status: {a['status']}",f"Closed paper trades: {a['closed']}"]
    if a["status"]=="INSUFFICIENT_DATA": lines += [f"Need {a['minimum']} closed trades before recommendations are considered.","","🔒 Live strategy unchanged."]; return "\n".join(lines)
    o=a["overall"]; lines += [f"Baseline win rate: {o['win_rate']:.1f}%",f"Baseline expectancy: {o['expectancy']:.2f}%",f"Baseline P&L: {o['pnl']:.2f}%","","Recommendations:"]
    if not a["recommendations"]: lines.append("• No evidence-based calibration recommendation yet.")
    for r in a["recommendations"]: lines.append(f"• {r['type']} — {r['segment']}: {r['reason']} (n={r['evidence']['n']}, win={r['evidence']['win_rate']:.1f}%, exp={r['evidence']['expectancy']:.2f}%)")
    lines += ["","🔒 HUMAN APPROVAL REQUIRED: recommendations do not modify live thresholds or weights."]
    return "\n".join(lines)
if __name__=="__main__": print(format_report())
