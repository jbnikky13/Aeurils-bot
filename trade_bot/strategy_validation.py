"""Objective validation for the paper-trading strategy.
Never changes live thresholds or places orders.
"""
import os, sqlite3, math
from collections import defaultdict
DB=os.getenv("DATABASE_PATH","trade_bot.db")
MIN_SAMPLE=int(os.getenv("VALIDATION_MIN_SAMPLE","20"))

def validate():
    con=sqlite3.connect(DB); con.row_factory=sqlite3.Row
    tables={r[0] for r in con.execute("select name from sqlite_master where type='table'")}
    if "paper_trades" not in tables:
        con.close(); return {"status":"INSUFFICIENT_DATA","closed":0,"reason":f"Need at least {MIN_SAMPLE} closed paper trades."}
    rows=con.execute("select * from paper_trades where exit_price is not null").fetchall(); con.close()
    if len(rows)<MIN_SAMPLE:
        return {"status":"INSUFFICIENT_DATA","closed":len(rows),"reason":f"Need at least {MIN_SAMPLE} closed paper trades."}
    pnl=[float(r["pnl_pct"] or 0) for r in rows]; wins=[p for p in pnl if p>0]; losses=[p for p in pnl if p<0]
    gross_win=sum(wins); gross_loss=abs(sum(losses)); pf=gross_win/gross_loss if gross_loss else math.inf
    eq=peak=dd=0.0
    for p in pnl:
        eq+=p; peak=max(peak,eq); dd=min(dd,eq-peak)
    groups=defaultdict(list); scores=defaultdict(list)
    for r,p in zip(rows,pnl):
        regime=r["market_regime"] if "market_regime" in r.keys() and r["market_regime"] else "UNKNOWN"; groups[regime].append(p)
        score=r["final_score"] if "final_score" in r.keys() else None
        if score is not None:
            lo=int(float(score)//10*10); scores[f"{lo}-{lo+9}"].append(p)
    def summarize(g):
        return {"trades":len(g),"win_rate":100*sum(p>0 for p in g)/len(g),"pnl_pct":sum(g),"expectancy_pct":sum(g)/len(g)}
    return {"status":"VALIDATED" if len(rows)>=MIN_SAMPLE else "INSUFFICIENT_DATA","closed":len(rows),"wins":len(wins),"losses":len(losses),"win_rate":100*len(wins)/len(rows),"pnl_pct":sum(pnl),"expectancy_pct":sum(pnl)/len(pnl),"profit_factor":pf,"max_drawdown_pct":abs(dd),"by_regime":{k:summarize(v) for k,v in groups.items()},"by_score":{k:summarize(v) for k,v in scores.items()}}

def format_report():
    a=validate(); lines=["🧪 AURELIS STRATEGY VALIDATION","",f"Status: {a['status']}",f"Closed paper trades: {a['closed']}"]
    if a["status"]=="INSUFFICIENT_DATA": lines += [f"⚠️ {a['reason']}","","No strategy changes have been made."]; return "\n".join(lines)
    lines += [f"Win rate: {a['win_rate']:.1f}%",f"Total paper P&L: {a['pnl_pct']:.2f}%",f"Expectancy: {a['expectancy_pct']:.2f}%",f"Profit factor: {a['profit_factor']:.2f}" if math.isfinite(a['profit_factor']) else "Profit factor: ∞",f"Max drawdown: {a['max_drawdown_pct']:.2f}%","","By regime:"]
    for k,v in a["by_regime"].items(): lines.append(f"• {k}: {v['trades']} | {v['win_rate']:.1f}% win | {v['pnl_pct']:.2f}% P&L")
    lines += ["","By score:"]
    for k,v in sorted(a["by_score"].items()): lines.append(f"• {k}: {v['trades']} | {v['win_rate']:.1f}% win | {v['pnl_pct']:.2f}% P&L")
    lines += ["","🔒 Observational only: no automatic strategy/threshold changes."]
    return "\n".join(lines)
if __name__=="__main__": print(format_report())
