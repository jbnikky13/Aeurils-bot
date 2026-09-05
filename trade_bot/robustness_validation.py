"""Phase 9: robustness and out-of-sample diagnostics for paper trades.
Simulation/analysis only. Never changes live strategy settings or places orders.
"""
import os, sqlite3, math
from collections import defaultdict
DB=os.getenv("DATABASE_PATH","trade_bot.db")
MIN_SAMPLE=int(os.getenv("ROBUSTNESS_MIN_SAMPLE","40"))
MIN_SPLIT=int(os.getenv("ROBUSTNESS_MIN_SPLIT","10"))

def _rows():
    con=sqlite3.connect(DB); con.row_factory=sqlite3.Row
    try:r=con.execute("select * from paper_trades where exit_price is not null order by rowid").fetchall()
    except sqlite3.Error:r=[]
    con.close();return r

def _stats(rows):
    p=[float(r["pnl_pct"] or 0) for r in rows]; w=[x for x in p if x>0]; l=[x for x in p if x<0]
    return {"n":len(p),"win_rate":100*len(w)/len(p) if p else 0,"pnl":sum(p),"expectancy":sum(p)/len(p) if p else 0,"profit_factor":sum(w)/abs(sum(l)) if l else (math.inf if w else 0)}

def validate():
    rows=_rows()
    if len(rows)<MIN_SAMPLE:return {"status":"INSUFFICIENT_DATA","closed":len(rows),"minimum":MIN_SAMPLE}
    mid=len(rows)//2; train=rows[:mid]; test=rows[mid:]
    regimes=defaultdict(list)
    for r in rows:
        regimes[(r["market_regime"] if "market_regime" in r.keys() and r["market_regime"] else "UNKNOWN")].append(r)
    regime_stats={k:_stats(v) for k,v in regimes.items() if len(v)>=MIN_SPLIT}
    score_buckets=defaultdict(list)
    for r in rows:
        if "final_score" in r.keys() and r["final_score"] is not None:score_buckets[int(float(r["final_score"])//10)*10].append(r)
    score_stats={f"{k}-{k+9}":_stats(v) for k,v in score_buckets.items() if len(v)>=MIN_SPLIT}
    a,b=_stats(train),_stats(test)
    robust=b["expectancy"]>=0 and b["win_rate"]>=50
    return {"status":"ROBUST" if robust else "REVIEW_REQUIRED","closed":len(rows),"in_sample":a,"out_of_sample":b,"regimes":regime_stats,"scores":score_stats,"robust_out_of_sample":robust}

def format_report():
    a=validate(); lines=["🔬 AURELIS ROBUSTNESS VALIDATION","",f"Status: {a['status']}",f"Closed paper trades: {a['closed']}"]
    if a["status"]=="INSUFFICIENT_DATA":return "\n".join(lines+[f"Need {a['minimum']} closed trades.","🔒 Live strategy unchanged."])
    i,o=a["in_sample"],a["out_of_sample"]
    lines += [f"In-sample: n={i['n']} | win={i['win_rate']:.1f}% | expectancy={i['expectancy']:.2f}%",f"Out-of-sample: n={o['n']} | win={o['win_rate']:.1f}% | expectancy={o['expectancy']:.2f}%","","By regime:"]
    for k,v in a["regimes"].items():lines.append(f"• {k}: n={v['n']} | win={v['win_rate']:.1f}% | exp={v['expectancy']:.2f}%")
    lines += ["","By score:"]+[f"• {k}: n={v['n']} | win={v['win_rate']:.1f}% | exp={v['expectancy']:.2f}%" for k,v in sorted(a["scores"].items())]
    lines += ["","🔒 Diagnostic only. No automatic strategy changes."]
    return "\n".join(lines)
if __name__=="__main__":print(format_report())
