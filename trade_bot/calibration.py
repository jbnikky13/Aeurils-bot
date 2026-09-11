"""Evidence-based paper-signal calibration metrics. No automatic strategy changes."""
import sqlite3
from collections import defaultdict
from . import journal
from .paper_trader import init_paper_db


def _rows():
    init_paper_db()
    with sqlite3.connect(journal.DB) as con:
        con.row_factory = sqlite3.Row
        return con.execute("SELECT * FROM paper_trades").fetchall()


def _bucket(score):
    try:
        s=float(score); lo=int(s//10)*10
        return f"{lo}-{lo+9}"
    except (TypeError,ValueError): return "UNKNOWN"


def _group(rows, key_fn):
    groups=defaultdict(lambda:[0,0,0.0])
    for r in rows:
        key=key_fn(r)
        win=str(r["outcome"] or "").upper() in {"WIN_TP1","WIN_TP2","WIN"}
        g=groups[key]; g[0]+=1; g[1]+=int(win); g[2]+=float(r["pnl_pct"] or 0)
    return [[k,v[0],100*v[1]/v[0] if v[0] else 0,v[2]] for k,v in sorted(groups.items())]


def calibration():
    rows=_rows()
    closed=[r for r in rows if r["exit_price"] is not None and str(r["status"]).upper()=="CLOSED"]
    wins=sum(str(r["outcome"] or "").upper() in {"WIN_TP1","WIN_TP2","WIN"} for r in closed)
    tp1=sum(str(r["outcome"] or "").upper()=="WIN_TP1" for r in closed)
    tp2=sum(str(r["outcome"] or "").upper()=="WIN_TP2" for r in closed)
    sl=sum(str(r["outcome"] or "").upper()=="LOSS_SL" for r in closed)
    expired=sum(str(r["outcome"] or "").upper()=="EXPIRED" for r in closed)
    pnl=sum(float(r["pnl_pct"] or 0) for r in closed)
    return {"closed":len(closed),"wins":wins,"tp1":tp1,"tp2":tp2,"sl":sl,"expired":expired,
            "win_rate_pct":100*wins/len(closed) if closed else 0.0,
            "tp1_rate_pct":100*tp1/len(closed) if closed else 0.0,
            "tp2_rate_pct":100*tp2/len(closed) if closed else 0.0,
            "sl_rate_pct":100*sl/len(closed) if closed else 0.0,
            "expiry_rate_pct":100*expired/len(closed) if closed else 0.0,
            "pnl_pct":pnl,"avg_pnl_pct":pnl/len(closed) if closed else 0.0,
            "by_regime":_group(closed,lambda r:r["market_regime"] or "UNKNOWN"),
            "by_score":_group(closed,lambda r:_bucket(r["final_score"]))}


def format_report():
    a=calibration(); n=a['closed']
    lines=["🧪 AURELIS CALIBRATION REPORT","",f"Closed paper trades: {n}"]
    if n:
        lines += [f"Win rate: {a['win_rate_pct']:.1f}%",f"TP1 exits: {a['tp1_rate_pct']:.1f}%",f"TP2 exits: {a['tp2_rate_pct']:.1f}%",f"SL exits: {a['sl_rate_pct']:.1f}%",f"24h expiries: {a['expiry_rate_pct']:.1f}%",f"Total paper P&L: {a['pnl_pct']:.2f}%",f"Average trade: {a['avg_pnl_pct']:.2f}%"]
    lines += ["","By market regime:"]
    lines += [f"• {k}: {n} trades | {w:.1f}% wins | {p:.2f}% P&L" for k,n,w,p in a["by_regime"]] or ["• No closed observations yet."]
    lines += ["","By signal score:"]
    lines += [f"• {k}: {n} trades | {w:.1f}% wins | {p:.2f}% P&L" for k,n,w,p in a["by_score"]] or ["• No closed observations yet."]
    lines += ["","📌 Calibration status: OBSERVATIONAL","🔒 No thresholds, weights, or execution settings are changed automatically."]
    return "\n".join(lines)

if __name__ == "__main__": print(format_report())
