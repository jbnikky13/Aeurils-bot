"""AURELIS Performance Audit v2.

Read-only analytics over the paper-trading ledger. This module does not change
signals, thresholds, position sizing, or execution. It separates strict
5m-boundary results from legacy wall-clock expiries so delayed workflow runs
cannot masquerade as 24h outcomes.
"""
import json, math, os, sqlite3
from collections import defaultdict
from datetime import datetime

DB=os.getenv("DATABASE_PATH","trade_bot.db")
OUT=os.getenv("PERFORMANCE_AUDIT_PATH","data/aurelis_performance_audit_v2.json")
FEE_BPS_PER_SIDE=float(os.getenv("PAPER_FEE_BPS_PER_SIDE","10"))
ROUND_TRIP_FEE_PCT=(2*FEE_BPS_PER_SIDE)/100.0


def _num(v, default=0.0):
    try:return float(v)
    except (TypeError,ValueError):return default


def _dt(v):
    try:return datetime.fromisoformat(str(v).replace("Z","+00:00"))
    except (TypeError,ValueError):return None


def _rows():
    if not os.path.exists(DB): return []
    with sqlite3.connect(DB) as con:
        con.row_factory=sqlite3.Row
        tables={r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "paper_trades" not in tables:return []
        return [dict(r) for r in con.execute("SELECT * FROM paper_trades").fetchall()]


def _outcome(r):return str(r.get("outcome") or "").upper()


def _strict_expiry(r):
    if _outcome(r)!="EXPIRED": return True
    return r.get("resolution_source")=="5m_expiry_boundary"


def _return_pct(r):
    return _num(r.get("pnl_pct"))


def _net_pct(r):
    return _return_pct(r)-ROUND_TRIP_FEE_PCT


def _r(r):
    risk=_num(r.get("initial_risk"))
    if risk<=0:return None
    entry=_num(r.get("entry"))
    exit_price=_num(r.get("exit_price"))
    if str(r.get("direction")).upper()=="SHORT":
        move=entry-exit_price
    else:
        move=exit_price-entry
    return move/risk


def _holding_hours(r):
    a,b=_dt(r.get("opened_at")),_dt(r.get("closed_at"))
    return (b-a).total_seconds()/3600 if a and b else None


def _mfe_r(r):
    risk=_num(r.get("initial_risk"))
    return _num(r.get("max_favorable_pct"))/(risk/_num(r.get("entry"))*100) if risk>0 and _num(r.get("entry")) else None


def _mae_r(r):
    risk=_num(r.get("initial_risk"))
    return _num(r.get("max_adverse_pct"))/(risk/_num(r.get("entry"))*100) if risk>0 and _num(r.get("entry")) else None


def _stats(rows):
    closed=[r for r in rows if str(r.get("status","")).upper()=="CLOSED" and _outcome(r)!="AMBIGUOUS"]
    scored=[r for r in closed if _outcome(r) in {"WIN_TP1","WIN_TP2","WIN_RUNNER","LOSS_SL"}]
    wins=[r for r in scored if _outcome(r).startswith("WIN_")]
    losses=[r for r in scored if _outcome(r)=="LOSS_SL"]
    net=[_net_pct(r) for r in closed]
    gross_profit=sum(max(0,x) for x in net)
    gross_loss=abs(sum(min(0,x) for x in net))
    eq=peak=dd=0.0
    for r in sorted(closed,key=lambda x:_dt(x.get("closed_at")) or datetime.min):
        eq+=_net_pct(r); peak=max(peak,eq); dd=max(dd,peak-eq)
    rs=[x for x in (_r(r) for r in closed) if x is not None]
    holding=[x for x in (_holding_hours(r) for r in closed) if x is not None]
    mfe=[x for x in (_mfe_r(r) for r in closed) if x is not None]
    mae=[x for x in (_mae_r(r) for r in closed) if x is not None]
    return {
        "trades":len(rows),"closed":len(closed),"scored":len(scored),
        "wins":len(wins),"losses":len(losses),
        "expired":sum(_outcome(r)=="EXPIRED" for r in closed),
        "strict_expiry_trades":sum(_outcome(r)=="EXPIRED" and _strict_expiry(r) for r in closed),
        "legacy_expiry_trades":sum(_outcome(r)=="EXPIRED" and not _strict_expiry(r) for r in closed),
        "win_rate_pct":round(len(wins)/len(scored)*100,2) if scored else 0.0,
        "net_pnl_pct":round(sum(net),4),
        "avg_trade_pct":round(sum(net)/len(closed),4) if closed else 0.0,
        "expectancy_pct":round(sum(_net_pct(r) for r in scored)/len(scored),4) if scored else 0.0,
        "avg_win_pct":round(sum(_net_pct(r) for r in wins)/len(wins),4) if wins else 0.0,
        "avg_loss_pct":round(sum(_net_pct(r) for r in losses)/len(losses),4) if losses else 0.0,
        "profit_factor":round(gross_profit/gross_loss,4) if gross_loss else None,
        "max_drawdown_pct":round(dd,4),
        "sum_r":round(sum(rs),4) if rs else 0.0,
        "avg_r":round(sum(rs)/len(rs),4) if rs else 0.0,
        "avg_mfe_r":round(sum(mfe)/len(mfe),4) if mfe else 0.0,
        "avg_mae_r":round(sum(mae)/len(mae),4) if mae else 0.0,
        "avg_holding_hours":round(sum(holding)/len(holding),3) if holding else 0.0,
    }


def _group(rows,key):
    groups=defaultdict(list)
    for r in rows:groups[str(key(r))].append(r)
    return {k:_stats(v) for k,v in sorted(groups.items())}


def _score_band(r):
    s=_num(r.get("final_score"))
    return "80+" if s>=80 else "75-79" if s>=75 else "70-74" if s>=70 else "65-69" if s>=65 else "<65"


def _boundary_quality(r):
    if _outcome(r)!="EXPIRED":return "NOT_EXPIRY"
    return "STRICT_5M_BOUNDARY" if _strict_expiry(r) else "LEGACY_WALL_CLOCK"


def build_report(rows=None):
    rows=_rows() if rows is None else rows
    closed=[r for r in rows if str(r.get("status","")).upper()=="CLOSED" and _outcome(r)!="AMBIGUOUS"]
    strict=[r for r in closed if _strict_expiry(r)]
    report={
        "audit_version":"2.0",
        "paper_only":True,
        "fee_assumption_bps_per_side":FEE_BPS_PER_SIDE,
        "fee_assumption_round_trip_pct":ROUND_TRIP_FEE_PCT,
        "methodology":{
            "execution_resolution":"5m",
            "expiry_policy":"first completed 5m candle at/after expiry_at",
            "legacy_expiry_treatment":"excluded from strict-boundary performance views",
            "r_definition":"price move divided by absolute entry-to-SL risk",
            "pnl_basis":"recorded pnl_pct less one entry and one exit fee",
        },
        "data_quality":{
            "total_rows":len(rows),
            "closed_rows":len(closed),
            "strict_boundary_rows":len(strict),
            "legacy_expiry_rows":sum(_outcome(r)=="EXPIRED" and not _strict_expiry(r) for r in closed),
            "fallback_expiry_rows":sum(r.get("resolution_source")=="wall_clock_fallback" for r in closed),
            "missing_initial_risk":sum(_num(r.get("initial_risk"))<=0 for r in closed),
        },
        "all_closed":_stats(closed),
        "strict_boundary_view":_stats(strict),
        "by_direction":_group(strict,lambda r:r.get("direction","UNKNOWN").upper()),
        "by_regime":_group(strict,lambda r:r.get("market_regime","UNKNOWN")),
        "by_score_band":_group(strict,_score_band),
        "by_symbol":_group(strict,lambda r:r.get("symbol","UNKNOWN")),
        "by_signal_source":_group(strict,lambda r:r.get("signal_source","UNKNOWN")),
        "by_expiry_quality":_group(closed,_boundary_quality),
    }
    return report


def write_report():
    report=build_report()
    os.makedirs(os.path.dirname(OUT) or ".",exist_ok=True)
    tmp=OUT+".tmp"
    with open(tmp,"w",encoding="utf-8") as f:json.dump(report,f,indent=2,ensure_ascii=False)
    os.replace(tmp,OUT)
    return report


if __name__=="__main__":
    report=write_report()
    a=report["strict_boundary_view"]
    print("AURELIS PERFORMANCE AUDIT v2")
    print(json.dumps({
        "strict_boundary_trades":a["trades"],
        "wins":a["wins"],"losses":a["losses"],"expired":a["expired"],
        "win_rate_pct":a["win_rate_pct"],"net_pnl_pct":a["net_pnl_pct"],
        "expectancy_pct":a["expectancy_pct"],"profit_factor":a["profit_factor"],
        "max_drawdown_pct":a["max_drawdown_pct"],"sum_r":a["sum_r"],
        "legacy_expiry_rows":report["data_quality"]["legacy_expiry_rows"],
    },indent=2))
