"""FV1 overlapping-position portfolio ledger and fail-closed risk telemetry."""
from __future__ import annotations
import sqlite3
from datetime import datetime, timezone
from .journal import DB

RISK_PER_TRADE_PCT=0.25
MAX_OPEN_POSITIONS=3
MAX_AGGREGATE_OPEN_RISK_PCT=1.0
DAILY_LOSS_LIMIT_PCT=1.0
WEEKLY_LOSS_LIMIT_PCT=3.0

def record_snapshot(captured_at=None):
    stamp=captured_at or datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(DB) as con:
        con.row_factory=sqlite3.Row
        con.execute("""CREATE TABLE IF NOT EXISTS fv1_equity_snapshots (
          id INTEGER PRIMARY KEY AUTOINCREMENT,captured_at TEXT NOT NULL UNIQUE,
          equity_index REAL NOT NULL,open_positions INTEGER NOT NULL,
          aggregate_open_risk_pct REAL NOT NULL,realized_r REAL NOT NULL,
          unrealized_r REAL NOT NULL,total_r REAL NOT NULL,daily_return_pct REAL,
          weekly_return_pct REAL,max_drawdown_pct REAL NOT NULL)""")
        con.execute("""CREATE TABLE IF NOT EXISTS fv1_risk_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,event_key TEXT NOT NULL UNIQUE,
          occurred_at TEXT NOT NULL,event_type TEXT NOT NULL,severity TEXT NOT NULL,
          observed_value REAL,limit_value REAL,details TEXT NOT NULL)""")
        rows=con.execute("""SELECT p.signal_id,p.status,p.entry,p.initial_risk,
          p.realized_pnl_pct,p.realized_r,p.unrealized_r
          FROM fv1_cohort c JOIN paper_trades p ON p.signal_id=c.signal_id
          ORDER BY p.opened_at,p.signal_id""").fetchall()
        if not rows: return {"recorded":False,"reason":"no_fv1_trades"}
        realized=unrealized=0.0
        opened=invalid=0
        for r in rows:
            risk=float(r["initial_risk"] or 0); entry=float(r["entry"] or 0)
            if risk<=0 or entry<=0:
                invalid+=1
                continue
            rr=float(r["realized_pnl_pct"] or 0)/100*entry/risk
            if r["status"]=="CLOSED" and r["realized_r"] is not None:
                rr=float(r["realized_r"])
            ur=0.0 if r["status"]=="CLOSED" else float(r["unrealized_r"] or 0)
            realized+=rr; unrealized+=ur
            if r["status"]=="OPEN": opened+=1
        total=realized+unrealized
        equity=100*(1+RISK_PER_TRADE_PCT/100*total)
        peak=float(con.execute("SELECT MAX(equity_index) FROM fv1_equity_snapshots").fetchone()[0] or 100)
        peak=max(peak,equity)
        dd=max(0,(peak-equity)/peak*100)
        day_start=con.execute("""SELECT equity_index FROM fv1_equity_snapshots
          WHERE substr(captured_at,1,10)=substr(?,1,10) ORDER BY captured_at LIMIT 1""",(stamp,)).fetchone()
        dt=datetime.fromisoformat(stamp.replace("Z","+00:00"))
        week=f"{dt.isocalendar().year}-W{dt.isocalendar().week:02d}"
        week_start=None
        for old in con.execute("SELECT captured_at,equity_index FROM fv1_equity_snapshots ORDER BY captured_at"):
            d=datetime.fromisoformat(old["captured_at"].replace("Z","+00:00"))
            if f"{d.isocalendar().year}-W{d.isocalendar().week:02d}"==week:
                week_start=float(old["equity_index"]); break
        daily=((equity/float(day_start[0]))-1)*100 if day_start else 0.0
        weekly=((equity/week_start)-1)*100 if week_start else 0.0
        aggregate=opened*RISK_PER_TRADE_PCT
        con.execute("""INSERT OR IGNORE INTO fv1_equity_snapshots
          (captured_at,equity_index,open_positions,aggregate_open_risk_pct,
           realized_r,unrealized_r,total_r,daily_return_pct,weekly_return_pct,max_drawdown_pct)
          VALUES(?,?,?,?,?,?,?,?,?,?)""",(stamp,equity,opened,aggregate,realized,unrealized,total,daily,weekly,dd))
        checks=[]
        if invalid: checks.append(("INVALID_RISK_RECORD",float(invalid),0.0,"FV1 trade lacks valid entry or initial risk"))
        if opened>MAX_OPEN_POSITIONS: checks.append(("OPEN_POSITION_LIMIT",float(opened),float(MAX_OPEN_POSITIONS),"Open FV1 positions exceed limit"))
        if aggregate>MAX_AGGREGATE_OPEN_RISK_PCT+1e-9: checks.append(("AGGREGATE_OPEN_RISK_LIMIT",aggregate,MAX_AGGREGATE_OPEN_RISK_PCT,"Aggregate FV1 open risk exceeds limit"))
        if daily<=-DAILY_LOSS_LIMIT_PCT: checks.append(("DAILY_LOSS_LIMIT",daily,-DAILY_LOSS_LIMIT_PCT,"Daily FV1 equity loss limit breached"))
        if weekly<=-WEEKLY_LOSS_LIMIT_PCT: checks.append(("WEEKLY_LOSS_LIMIT",weekly,-WEEKLY_LOSS_LIMIT_PCT,"Weekly FV1 equity loss limit breached"))
        for kind,value,limit,detail in checks:
            key=f"{kind}:{stamp[:10]}" if kind=="DAILY_LOSS_LIMIT" else (f"{kind}:{week}" if kind=="WEEKLY_LOSS_LIMIT" else f"{kind}:{stamp}")
            con.execute("""INSERT OR IGNORE INTO fv1_risk_events
              (event_key,occurred_at,event_type,severity,observed_value,limit_value,details)
              VALUES(?,?,?,'CRITICAL',?,?,?)""",(key,stamp,kind,value,limit,detail))
        con.commit()
        return {"recorded":True,"equity_index":equity,"open_positions":opened,
          "aggregate_open_risk_pct":aggregate,"realized_r":realized,
          "unrealized_r":unrealized,"max_drawdown_pct":dd,
          "critical_events":len(checks),"invalid_risk_records":invalid}

def risk_metrics():
    with sqlite3.connect(DB) as con:
        con.row_factory=sqlite3.Row
        has=con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='fv1_equity_snapshots'").fetchone()
        if not has: return {"equity_drawdown_pct":None,"critical_risk_breaches":None,"equity_snapshots":0,"risk_events":[]}
        snaps=con.execute("SELECT * FROM fv1_equity_snapshots ORDER BY captured_at").fetchall()
        events=con.execute("SELECT * FROM fv1_risk_events WHERE severity='CRITICAL'").fetchall()
    if not snaps: return {"equity_drawdown_pct":None,"critical_risk_breaches":None,"equity_snapshots":0,"risk_events":[]}
    return {"equity_drawdown_pct":max(float(x["max_drawdown_pct"]) for x in snaps),
      "critical_risk_breaches":len(events),"equity_snapshots":len(snaps),
      "latest_equity_index":float(snaps[-1]["equity_index"]),
      "latest_open_positions":int(snaps[-1]["open_positions"]),
      "latest_aggregate_open_risk_pct":float(snaps[-1]["aggregate_open_risk_pct"]),
      "risk_events":[dict(x) for x in events]}
