"""Paper-trading performance analytics. Purely observational."""
import os, sqlite3
from collections import defaultdict
DB=os.getenv("DATABASE_PATH","trade_bot.db")

def analytics():
    con=sqlite3.connect(DB); con.row_factory=sqlite3.Row
    tables={r[0] for r in con.execute("select name from sqlite_master where type='table'")}
    if "paper_trades" not in tables:
        con.close(); return {"trades":0,"closed":0,"wins":0,"losses":0,"win_rate":0.0,"pnl_pct":0.0,"expectancy_pct":0.0,"max_drawdown_pct":0.0,"by_regime":[]}
    rows=con.execute("select * from paper_trades").fetchall(); con.close()
    closed=[r for r in rows if str(r["status"]).upper() in {"CLOSED","TP1","TP2","SL"} or r["exit_price"] is not None]
    wins=[r for r in closed if str(r["outcome"] or "").upper() in {"WIN","TP1","TP2","WIN_TP1","WIN_TP2"}]
    losses=[r for r in closed if str(r["outcome"] or "").upper() in {"LOSS","SL","STOP_LOSS"}]
    pnls=[float(r["pnl_pct"] or 0) for r in closed]
    equity=peak=dd=0.0
    for p in pnls:
        equity+=p; peak=max(peak,equity); dd=min(dd,equity-peak)
    groups=defaultdict(lambda:[0,0.0])
    for r in closed:
        key=r["market_regime"] if "market_regime" in r.keys() and r["market_regime"] else "UNKNOWN"
        groups[key][0]+=1; groups[key][1]+=float(r["pnl_pct"] or 0)
    return {"trades":len(rows),"closed":len(closed),"wins":len(wins),"losses":len(losses),"win_rate":100*len(wins)/len(closed) if closed else 0.0,"pnl_pct":sum(pnls),"expectancy_pct":sum(pnls)/len(closed) if closed else 0.0,"max_drawdown_pct":abs(dd),"by_regime":[[k,v[0],v[1]] for k,v in sorted(groups.items())]}

def format_report():
    a=analytics()
    lines=["📊 AURELIS PAPER PERFORMANCE","",f"Paper trades: {a['trades']}",f"Closed: {a['closed']}",f"Wins: {a['wins']} | Losses: {a['losses']}",f"Win rate: {a['win_rate']:.1f}%",f"Total paper P&L: {a['pnl_pct']:.2f}%",f"Expectancy: {a['expectancy_pct']:.2f}% per closed trade",f"Max drawdown: {a['max_drawdown_pct']:.2f}%"]
    if a["by_regime"]: lines += ["","By market regime:"]+[f"• {r}: {n} trades | {p:.2f}% P&L" for r,n,p in a["by_regime"]]
    lines += ["","🧪 Paper results are simulations and are not evidence of guaranteed future returns."]
    return "\n".join(lines)
if __name__ == "__main__": print(format_report())
