"""FV1 runtime integration for the existing SQLite paper-trade ledger.

The cohort is prospective and isolated from legacy paper trades. Research-only;
this module never places or authorizes orders.
"""
from __future__ import annotations
import hashlib, json, math, os, sqlite3
import httpx
from datetime import datetime, timezone
from pathlib import Path
from .journal import DB
from .forward_validation import PROTOCOL, evaluate_gates, bootstrap_daily_block_ci
from .token_intelligence import select_watchlist

RISK_PER_TRADE_PCT = 0.25
BINANCE_DATA_BASE = os.getenv('CRYPTO_API_URL','https://data-api.binance.vision').rstrip('/')
MIN_TOKEN_TRADES = 3
MIN_TOKEN_SCORED = 2

def _utc():
    return datetime.now(timezone.utc).isoformat()

def _connect():
    con=sqlite3.connect(DB); con.row_factory=sqlite3.Row
    con.execute("""CREATE TABLE IF NOT EXISTS fv1_meta (
        id INTEGER PRIMARY KEY CHECK(id=1), frozen_at TEXT NOT NULL,
        strategy_fingerprint TEXT NOT NULL, protocol_json TEXT NOT NULL)""")
    con.execute("""CREATE TABLE IF NOT EXISTS fv1_cohort (
        signal_id INTEGER PRIMARY KEY, symbol TEXT NOT NULL, created_at TEXT NOT NULL,
        strategy_fingerprint TEXT NOT NULL, cohort_id TEXT NOT NULL DEFAULT 'FV1',
        status TEXT NOT NULL DEFAULT 'OPEN', outcome TEXT, pnl_pct REAL, realized_r REAL,
        closed_at TEXT, resolution_source TEXT, integrity_ok INTEGER NOT NULL DEFAULT 1)""")
    con.execute("""CREATE TABLE IF NOT EXISTS fv1_watchlist_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT, generated_at TEXT NOT NULL,
        selection_json TEXT NOT NULL, source TEXT NOT NULL)""")
    con.commit()
    return con

def _fingerprint():
    root=Path(__file__).resolve().parent
    files=("scheduler.py","signal_engine.py","paper_trader.py","confluence_gate.py")
    h=hashlib.sha256()
    for name in files:
        p=root/name
        if not p.exists(): raise RuntimeError("FV1 strategy source missing: "+name)
        h.update(name.encode()); h.update(p.read_bytes())
    return h.hexdigest()

def initialize():
    con=_connect()
    try:
        row=con.execute("SELECT frozen_at,strategy_fingerprint,protocol_json FROM fv1_meta WHERE id=1").fetchone()
        if row is None:
            con.execute("INSERT INTO fv1_meta(id,frozen_at,strategy_fingerprint,protocol_json) VALUES(1,?,?,?)",
                        (_utc(),_fingerprint(),json.dumps(PROTOCOL,sort_keys=True)))
            con.commit()
            row=con.execute("SELECT frozen_at,strategy_fingerprint,protocol_json FROM fv1_meta WHERE id=1").fetchone()
        if json.loads(row["protocol_json"]) != PROTOCOL:
            raise RuntimeError("FV1 protocol mismatch; do not silently reset the cohort")
        return dict(row)
    finally: con.close()

def register_signal(signal_id):
    meta=initialize()
    if _fingerprint() != meta["strategy_fingerprint"]:
        raise RuntimeError("FV1 frozen strategy fingerprint changed; stop cohort intake and restart under a new cohort")
    con=_connect()
    try:
        trade=con.execute("SELECT symbol,opened_at,status FROM paper_trades WHERE signal_id=?",(int(signal_id),)).fetchone()
        if trade is None: return False
        created=trade["opened_at"]
        # Existing ledger records and any signals before the immutable freeze are excluded.
        from .forward_validation import cohort_eligible
        record={"created_at":created,"strategy_fingerprint":meta["strategy_fingerprint"],
                "cohort_id":"FV1","status":trade["status"]}
        eligible,reason=cohort_eligible(record,meta["frozen_at"],meta["strategy_fingerprint"])
        if not eligible: return False
        con.execute("""INSERT OR IGNORE INTO fv1_cohort
            (signal_id,symbol,created_at,strategy_fingerprint,cohort_id,status)
            VALUES(?,?,?,?,'FV1',?)""",(int(signal_id),trade["symbol"],created,
              meta["strategy_fingerprint"],trade["status"]))
        con.commit()
        return True
    finally: con.close()

def sync_outcomes():
    initialize()
    con=_connect()
    try:
        con.execute("""UPDATE fv1_cohort SET
            status=p.status, outcome=p.outcome, pnl_pct=p.pnl_pct,
            realized_r=CASE WHEN (p.realized_r IS NULL OR p.realized_r=0) AND p.initial_risk>0 AND p.exit_price IS NOT NULL THEN CASE WHEN p.direction='LONG' THEN (p.exit_price-p.entry)/p.initial_risk WHEN p.direction='SHORT' THEN (p.entry-p.exit_price)/p.initial_risk ELSE NULL END ELSE p.realized_r END, closed_at=p.closed_at,
            resolution_source=p.resolution_source
            FROM paper_trades p
            WHERE fv1_cohort.signal_id=p.signal_id""")
        con.commit()
    finally: con.close()

def cohort_metrics():
    sync_outcomes()
    con=_connect()
    try:
        meta=con.execute("SELECT * FROM fv1_meta WHERE id=1").fetchone()
        rows=con.execute("""SELECT c.*,p.initial_risk,p.entry,p.direction,p.exit_price
            FROM fv1_cohort c LEFT JOIN paper_trades p ON p.signal_id=c.signal_id
            ORDER BY COALESCE(c.closed_at,c.created_at),c.signal_id""").fetchall()
    finally: con.close()
    signals=len(rows)
    scored=[r for r in rows if r["status"]=="CLOSED" and r["outcome"] in
            ("WIN_TP1","WIN_TP2","WIN_RUNNER","LOSS_SL")]
    wins=sum(1 for r in scored if str(r["outcome"]).startswith("WIN"))
    losses=len(scored)-wins
    # Realized R is the normalized outcome; missing/zero risk is an integrity defect.
    rs=[float(r["realized_r"]) for r in scored if r["realized_r"] is not None]
    integrity=sum(1 for r in rows if r["integrity_ok"]==1 and r["strategy_fingerprint"]==meta["strategy_fingerprint"] and r["initial_risk"] is not None and float(r["initial_risk"] or 0)>0)/signals*100 if signals else 0.0
    daily={}
    for r in scored:
        if r["realized_r"] is None or not r["closed_at"]: continue
        day=str(r["closed_at"])[:10]
        daily[day]=daily.get(day,0.0)+float(r["realized_r"])*RISK_PER_TRADE_PCT
    equity=100.0; peak=100.0; max_dd=0.0
    for r in scored:
        if r["realized_r"] is None: continue
        equity *= (1.0 + RISK_PER_TRADE_PCT/100.0*float(r["realized_r"]))
        peak=max(peak,equity)
        max_dd=max(max_dd,(peak-equity)/peak*100 if peak else 0.0)
    gross_win=sum(x for x in rs if x>0); gross_loss=abs(sum(x for x in rs if x<0))
    expectancy=(sum(rs)/len(rs)) if rs else None
    pf=(gross_win/gross_loss) if gross_loss>0 else (float("inf") if gross_win>0 else None)
    days=0
    if meta:
        try:
            frozen=datetime.fromisoformat(meta["frozen_at"].replace("Z","+00:00"))
            days=max(0,(datetime.now(timezone.utc)-frozen).days)
        except Exception:
            days=0
    ci=bootstrap_daily_block_ci([daily[k] for k in sorted(daily)]) if len(daily)>=2 else None
    metrics={"signals":signals,"scored":len(scored),"days":days,
        "expectancy_pct":expectancy*RISK_PER_TRADE_PCT if expectancy is not None else None,
        "profit_factor":pf,"equity_drawdown_pct":None,"equity_drawdown_proxy_pct":max_dd if scored else None,
        "integrity_pct":integrity if signals else None,
        "bootstrap_ci_low_pct":ci["lower_95_pct"] if ci else None,
        "critical_risk_breaches":None,
        "wins":wins,"losses":losses,"expiries":sum(1 for r in rows if r["outcome"] in ("EXPIRED","EXPIRY")),
        "win_rate_pct":wins/len(scored)*100 if scored else None,
        "equity_index":equity,"max_drawdown_pct":max_dd,"bootstrap_ci":ci,
        "frozen_at":meta["frozen_at"] if meta else None,
        "strategy_fingerprint":meta["strategy_fingerprint"] if meta else None,
        "drawdown_method":"proxy: compounded fixed 0.25% risk per realized R; actual overlapping portfolio equity path is not yet instrumented"}
    metrics["gates"]=evaluate_gates(metrics)
    return metrics

def rank_from_paper_trades():
    """Rank Binance assets represented in the persisted paper ledger.

    This research watchlist may use legacy paper-trade history for immediate
    coverage. It is explicitly separate from the prospective FV1 validation
    cohort and never feeds a trade filter or authorizes an order.
    """
    con=_connect()
    try:
        rows=con.execute("""SELECT p.symbol,COUNT(*) n,
            SUM(CASE WHEN p.status='CLOSED' AND p.outcome IN
            ('WIN_TP1','WIN_TP2','WIN_RUNNER','LOSS_SL') THEN 1 ELSE 0 END) scored,
            SUM(CASE WHEN p.outcome IN ('WIN_TP1','WIN_TP2','WIN_RUNNER') THEN 1 ELSE 0 END) wins,
            AVG(CASE WHEN p.realized_r IS NOT NULL AND p.realized_r!=0 THEN p.realized_r
                WHEN p.initial_risk>0 AND p.exit_price IS NOT NULL AND p.direction='LONG'
                    THEN (p.exit_price-p.entry)/p.initial_risk
                WHEN p.initial_risk>0 AND p.exit_price IS NOT NULL AND p.direction='SHORT'
                    THEN (p.entry-p.exit_price)/p.initial_risk END) avg_r,
            AVG(p.final_score) avg_score, MAX(p.opened_at) latest
            FROM paper_trades p WHERE p.symbol LIKE '%USDT'
            GROUP BY p.symbol""").fetchall()
    finally: con.close()
    candidates=[]
    for r in rows:
        if r["n"]<MIN_TOKEN_TRADES or r["scored"]<MIN_TOKEN_SCORED: continue
        win=float(r["wins"] or 0)/float(r["scored"])
        avg_r=float(r["avg_r"] or 0)
        score=100*(.50*min(1,float(r["scored"])/20)+.30*max(0,min(1,(avg_r+1)/2))+.20*max(0,min(1,float(r["avg_score"] or 0)/100)))
        candidates.append({"eligible":True,"symbol":r["symbol"],"trades":r["n"],"scored":r["scored"],
            "win_rate_pct":round(win*100,2),"avg_r":round(avg_r,3),
            "avg_engine_score":round(float(r["avg_score"] or 0),1),
            "score":round(score,2),"source":"PAPER_LEDGER_HISTORY"})
    # Current Binance spot liquidity/spread and closed 4h candles qualify the
    # candidate pool; historical ledger data never enters the FV1 gate metrics.
    market=[]
    with httpx.Client(timeout=12) as client:
        for item in candidates:
            try:
                q=client.get(BINANCE_DATA_BASE+"/api/v3/ticker/24hr",params={"symbol":item["symbol"]})
                b=client.get(BINANCE_DATA_BASE+"/api/v3/ticker/bookTicker",params={"symbol":item["symbol"]})
                q.raise_for_status(); b.raise_for_status()
                quote_volume=float(q.json().get("quoteVolume",0))
                bid=float(b.json().get("bidPrice",0)); ask=float(b.json().get("askPrice",0))
                spread=(ask-bid)/((ask+bid)/2)*100 if bid>0 and ask>=bid else 999
                if quote_volume < 2_000_000 or spread > .35: continue
                item["quote_volume_24h_usd"]=round(quote_volume,2)
                item["spread_pct"]=round(spread,4)
                item["score"]=round(min(100,item["score"]+min(5,math.log10(max(1,quote_volume/2_000_000))*2)),2)
                k=client.get(BINANCE_DATA_BASE+"/api/v3/klines",params={"symbol":item["symbol"],"interval":"4h","limit":45})
                k.raise_for_status()
                now_ms=int(datetime.now(timezone.utc).timestamp()*1000)
                closed=[row for row in k.json() if int(row[6])<now_ms]
                closes=[float(row[4]) for row in closed[-42:] if float(row[4])>0]
                if len(closes)<30: continue
                returns=[closes[i]/closes[i-1]-1 for i in range(1,len(closes))]
                item["trend_7d_pct"]=round((closes[-1]/closes[0]-1)*100,2)
                item["realized_vol_24h_pct"]=round(math.sqrt(sum(x*x for x in returns)/len(returns))*math.sqrt(6)*100,3)
                item["market_data_source"]="BINANCE_SPOT_24H_BOOK_TICKER_CLOSED_4H_CANDLES"
                market.append(item)
            except Exception:
                continue
    selection=select_watchlist(market,active_count=10,reserve_count=5)
    selection["source"]="PAPER_LEDGER_HISTORY_PLUS_BINANCE_LIQUIDITY"
    return selection

def save_watchlist(selection):
    con=_connect()
    try:
        previous=con.execute("SELECT generated_at,selection_json FROM fv1_watchlist_history ORDER BY id DESC LIMIT 1").fetchone()
        current_symbols=[x["symbol"] for x in selection.get("selected",[])]
        previous_symbols=[]
        if previous:
            try: previous_symbols=[x["symbol"] for x in json.loads(previous["selection_json"]).get("selected",[])]
            except Exception: previous_symbols=[]
        added=sorted(set(current_symbols)-set(previous_symbols))
        removed=sorted(set(previous_symbols)-set(current_symbols))
        selection["rotation"]={"added":added,"removed":removed,"reason":"WEEKLY_RANK_REFRESH" if added or removed else "NO_CHANGE"}
        due=not previous or bool(added or removed)
        if previous and not due:
            try:
                last=datetime.fromisoformat(previous["generated_at"].replace("Z","+00:00"))
                due=(datetime.now(timezone.utc)-last).days>=7
            except Exception: due=True
        if due:
            con.execute("INSERT INTO fv1_watchlist_history(generated_at,selection_json,source) VALUES(?,?,?)",
                (selection["generated_at"],json.dumps(selection,sort_keys=True),selection.get("source","GENERATED_PAPER_TRADES")))
            con.commit()
    finally: con.close()

def build_fv1_report():
    m=cohort_metrics()
    lines=["🧪 AURELIS FV1 — PROSPECTIVE PAPER VALIDATION",
        f"Status: {m['gates']['status']} · Paper only",
        f"Eligible signals: {m['signals']}/200 · Scored TP/SL: {m['scored']}/100 · Days: {m['days']}/30",
        f"Expectancy: {m['expectancy_pct'] if m['expectancy_pct'] is not None else 'PENDING'}% · PF: {m['profit_factor'] if m['profit_factor'] is not None else 'PENDING'}",
        f"Equity DD proxy: {m['equity_drawdown_proxy_pct']:.2f}% · verified gate PENDING" if m['equity_drawdown_proxy_pct'] is not None else "Equity DD: PENDING (account-level exposure not yet instrumented)",
        f"Integrity: {m['integrity_pct']:.2f}%" if m['integrity_pct'] is not None else "Integrity: PENDING",
        f"Bootstrap lower 95% CI: {m['bootstrap_ci_low_pct'] if m['bootstrap_ci_low_pct'] is not None else 'PENDING'}",
        f"Risk breaches: {m['critical_risk_breaches']}","",
        "GATES: "+", ".join(f"{k}={v['status']}" for k,v in m["gates"]["gates"].items()),
        "Note: equity index assumes fixed 0.25% risk per realized R; overlapping exposure is not netted. No live trading."]
    return "\n".join(lines)

def build_token_report():
    w=rank_from_paper_trades()
    lines=["🔎 AURELIS TOKEN INTELLIGENCE",
        "Ranking source: stored AURELIS paper-trade history + Binance liquidity, spread and closed 4h candles",
        "","","TOP 10"]
    for i,x in enumerate(w["selected"],1):
        lines.append(f"{i}. {x['symbol']} — {x['score']:.1f}/100 | {x['scored']} scored | WR {x['win_rate_pct']:.1f}% | avg {x['avg_r']:+.2f}R | 7d {x.get('trend_7d_pct',0):+.1f}%")
    lines += ["","RESERVES"]
    lines += [f"• {x['symbol']} — {x['score']:.1f}" for x in w["reserves"]] or ["• None qualified"]
    if w["unfilled_active_slots"]: lines.append(f"⚠️ Only {len(w['selected'])} assets meet minimum evidence; {w['unfilled_active_slots']} slots intentionally unfilled.")
    save_watchlist(w)
    return "\n".join(lines)

def build_preview():
    return build_fv1_report()+"\n\n"+build_token_report()
