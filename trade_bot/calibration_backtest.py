"""Controlled calibration comparison: candidate recommendations are compared with baseline.
This module is simulation-only and never modifies live strategy settings.
"""
import os, sqlite3
from collections import defaultdict
DB=os.getenv("DATABASE_PATH","trade_bot.db")
MIN_SAMPLE=int(os.getenv("BACKTEST_MIN_SAMPLE","30"))

def _rows():
    con=sqlite3.connect(DB); con.row_factory=sqlite3.Row
    try: rows=con.execute("select * from paper_trades where exit_price is not null").fetchall()
    except sqlite3.Error: rows=[]
    con.close(); return rows

def _stats(rows):
    p=[float(r["pnl_pct"] or 0) for r in rows]
    return {"n":len(p),"win_rate":100*sum(x>0 for x in p)/len(p) if p else 0,"expectancy":sum(p)/len(p) if p else 0,"pnl":sum(p)}

def compare():
    rows=_rows()
    if len(rows)<MIN_SAMPLE: return {"status":"INSUFFICIENT_DATA","closed":len(rows),"minimum":MIN_SAMPLE}
    baseline=_stats(rows)
    # Conservative candidate simulation: recommendations are expressed as review filters,
    # not new live weights. Only trades belonging to positively supported segments are retained.
    regimes=defaultdict(list); scores=defaultdict(list)
    for r in rows:
        regime=r["market_regime"] if "market_regime" in r.keys() and r["market_regime"] else "UNKNOWN"; regimes[regime].append(r)
        if "final_score" in r.keys() and r["final_score"] is not None: scores[int(float(r["final_score"])//10)*10].append(r)
    supported={k for k,v in regimes.items() if len(v)>=10 and _stats(v)["expectancy"]>baseline["expectancy"] and _stats(v)["win_rate"]>baseline["win_rate"]}
    candidate=[r for r in rows if (r["market_regime"] or "UNKNOWN") in supported]
    cand=_stats(candidate)
    return {"status":"REVIEW_READY","closed":len(rows),"baseline":baseline,"candidate":cand,"supported_regimes":sorted(supported),"candidate_improves_expectancy":cand["expectancy"]>baseline["expectancy"],"candidate_trade_count":len(candidate)}

def format_report():
    a=compare(); lines=["🧪 AURELIS CONTROLLED CALIBRATION BACKTEST","",f"Status: {a['status']}",f"Closed paper trades: {a['closed']}"]
    if a["status"]=="INSUFFICIENT_DATA": lines += [f"Need {a['minimum']} closed trades before comparison.","🔒 Live strategy unchanged."]; return "\n".join(lines)
    b,c=a["baseline"],a["candidate"]
    lines += [f"Baseline: {b['n']} trades | {b['win_rate']:.1f}% win | {b['expectancy']:.2f}% expectancy | {b['pnl']:.2f}% P&L",f"Candidate filter: {c['n']} trades | {c['win_rate']:.1f}% win | {c['expectancy']:.2f}% expectancy | {c['pnl']:.2f}% P&L",f"Supported regimes: {', '.join(a['supported_regimes']) if a['supported_regimes'] else 'None'}",f"Expectancy improvement: {'YES' if a['candidate_improves_expectancy'] else 'NO'}","","🔒 Simulation only. Human approval is required before any calibration is applied."]
    return "\n".join(lines)
if __name__=="__main__": print(format_report())
