"""Evidence-based paper-signal calibration metrics. No automatic strategy changes."""
import sqlite3
from collections import defaultdict
from . import journal
from .paper_trader import init_paper_db


def _rows():
    init_paper_db()
    with sqlite3.connect(journal.DB) as con:
        con.row_factory=sqlite3.Row
        return con.execute("SELECT * FROM paper_trades").fetchall()


def _bucket(score):
    try:
        s=float(score)
        return f"{int(s//10)*10}-{int(s//10)*10+9}"
    except (TypeError,ValueError): return "UNKNOWN"


def calibration():
    rows=_rows()
    closed=[r for r in rows if r["exit_price"] is not None and str(r["status"]).upper()=="CLOSED"]
    groups=defaultdict(lambda:[0,0,0.0])
    for r in closed:
        outcome=str(r["outcome"] or "").upper()
        win=outcome in {"WIN_TP1","WIN_TP2","WIN"}
        regime=r["market_regime"] or "UNKNOWN"
        score=r["final_score"]
        for key in [("REGIME",regime),("SCORE",_bucket(score))]:
            g=groups[key]; g[0]+=1; g[1]+=int(win); g[2]+=float(r["pnl_pct"] or 0)

    def out(prefix):
        result=[]
        for (kind,key),v in sorted(groups.items()):
            if kind==prefix: result.append([key,v[0],100*v[1]/v[0] if v[0] else 0,v[2]])
        return result
    return {"closed":len(closed),"by_regime":out("REGIME"),"by_score":out("SCORE")}


def format_report():
    a=calibration()
    lines=["🧪 AURELIS CALIBRATION REPORT","",f"Closed paper trades: {a['closed']}","", "By market regime:"]
    lines += [f"• {k}: {n} trades | {w:.1f}% wins | {p:.2f}% P&L" for k,n,w,p in a["by_regime"]] or ["• No closed observations yet."]
    lines += ["", "By signal score:"]
    lines += [f"• {k}: {n} trades | {w:.1f}% wins | {p:.2f}% P&L" for k,n,w,p in a["by_score"]] or ["• No closed observations yet."]
    lines += ["", "🔒 Calibration is observational only; no thresholds or weights are changed automatically."]
    return "\n".join(lines)


if __name__ == "__main__": print(format_report())
