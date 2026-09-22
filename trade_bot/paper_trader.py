"""Deterministic paper-trading ledger with 1h candle resolution.

Normal setups keep the existing TP1/TP2 close behavior. Continuation/breakout
setups can opt into partial exits plus a trailing runner. This remains paper-only.
"""
import sqlite3
from datetime import datetime, timezone, timedelta
from .journal import DB, init_db

PAPER_TABLE="paper_trades"
RESOLUTION_INTERVAL="1h"
TP1_FRACTION=0.30
TP2_FRACTION=0.30


def _now(): return datetime.now(timezone.utc).isoformat()
def _parse_time(value):
    if not value: return None
    try: return datetime.fromisoformat(str(value).replace("Z","+00:00"))
    except ValueError: return None


def init_paper_db():
    init_db()
    with sqlite3.connect(DB) as con:
        con.execute(f"""CREATE TABLE IF NOT EXISTS {PAPER_TABLE} (
            id INTEGER PRIMARY KEY AUTOINCREMENT, signal_id INTEGER UNIQUE NOT NULL,
            symbol TEXT NOT NULL, direction TEXT NOT NULL, entry REAL NOT NULL,
            stop_loss REAL, tp1 REAL, tp2 REAL, status TEXT NOT NULL DEFAULT 'OPEN',
            exit_price REAL, outcome TEXT, pnl_pct REAL, opened_at TEXT NOT NULL,
            closed_at TEXT, final_score REAL, market_regime TEXT DEFAULT 'UNKNOWN',
            gemini_decision TEXT, gemini_confidence REAL, gemini_available INTEGER)""")
        cols={r[1] for r in con.execute(f"PRAGMA table_info({PAPER_TABLE})")}
        additions={"final_score":"REAL","market_regime":"TEXT DEFAULT 'UNKNOWN'","gemini_decision":"TEXT","gemini_confidence":"REAL","gemini_available":"INTEGER","tp1_hit_at":"TEXT","tp2_hit_at":"TEXT","sl_hit_at":"TEXT","exit_reason":"TEXT","last_price":"REAL","last_checked_at":"TEXT","max_favorable_pct":"REAL DEFAULT 0","max_adverse_pct":"REAL DEFAULT 0","expiry_at":"TEXT","resolution_source":"TEXT","runner_enabled":"INTEGER DEFAULT 0","runner_active":"INTEGER DEFAULT 0","remaining_pct":"REAL DEFAULT 100","realized_pnl_pct":"REAL DEFAULT 0","trailing_stop":"REAL","trailing_atr_multiplier":"REAL DEFAULT 2.0","initial_risk":"REAL","realized_r":"REAL DEFAULT 0","unrealized_r":"REAL DEFAULT 0"}
        for col,typ in additions.items():
            if col not in cols: con.execute(f"ALTER TABLE {PAPER_TABLE} ADD COLUMN {col} {typ}")
        con.commit()


def open_paper_trade(signal_id,symbol,direction,entry,stop_loss=None,tp1=None,tp2=None,final_score=None,market_regime="UNKNOWN",gemini_decision=None,gemini_confidence=None,gemini_available=None,runner_enabled=False,trailing_atr_multiplier=2.0,signal_source="PRIMARY",confluence_score=None,confluence_tier=None):
    init_paper_db(); opened=datetime.now(timezone.utc); expiry=opened+timedelta(hours=24); risk=abs(float(entry)-float(stop_loss)) if stop_loss is not None else None
    with sqlite3.connect(DB) as con:
        cur=con.execute(f"""INSERT OR IGNORE INTO {PAPER_TABLE}
            (signal_id,symbol,direction,entry,stop_loss,tp1,tp2,opened_at,final_score,market_regime,gemini_decision,gemini_confidence,gemini_available,last_price,last_checked_at,expiry_at,runner_enabled,remaining_pct,trailing_atr_multiplier,initial_risk,signal_source,confluence_score,confluence_tier)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(signal_id,symbol,direction,float(entry),stop_loss,tp1,tp2,opened.isoformat(),final_score,market_regime,gemini_decision,gemini_confidence,gemini_available,float(entry),opened.isoformat(),expiry.isoformat(),1 if runner_enabled else 0,100.0,float(trailing_atr_multiplier or 2.0),risk,signal_source,confluence_score,confluence_tier))
        con.commit(); return cur.rowcount==1


def _pnl(direction,entry,exit_price):
    return ((exit_price-entry)/entry*100 if direction=="LONG" else (entry-exit_price)/entry*100 if direction=="SHORT" else 0.0)

def _r_value(direction,entry,exit_price,initial_risk,fraction=1.0):
    """Risk multiple based on absolute price risk, never percent/risk mixing."""
    if entry is None or exit_price is None:
        return 0.0
    risk = float(initial_risk)
    if risk <= 0:
        return 0.0
    move = (float(exit_price)-float(entry)) if direction=="LONG" else (float(entry)-float(exit_price)) if direction=="SHORT" else 0.0
    return (move / risk) * float(fraction)

def _unrealized_r(direction,entry,current_price,initial_risk,fraction=1.0):
    if not initial_risk or float(initial_risk) <= 0:
        return 0.0
    move = (float(current_price)-float(entry)) if direction=="LONG" else (float(entry)-float(current_price)) if direction=="SHORT" else 0.0
    return (move / float(initial_risk)) * float(fraction)
def _favorable(direction,entry,price): return max(0.0,_pnl(direction,entry,price))
def _adverse(direction,entry,price): return max(0.0,-_pnl(direction,entry,price))
def _sync_setup(signal_id,outcome):
    with sqlite3.connect(DB) as con: con.execute("UPDATE setups SET outcome=?, closed_at=? WHERE id=? AND outcome='OPEN'",(outcome,_now(),signal_id)); con.commit()


def _resolve_candle(direction,high,low,stop,tp1,tp2):
    if direction=="LONG": stop_hit=stop is not None and low<=stop; tp2_hit=tp2 is not None and high>=tp2; tp1_hit=tp1 is not None and high>=tp1
    else: stop_hit=stop is not None and high>=stop; tp2_hit=tp2 is not None and low<=tp2; tp1_hit=tp1 is not None and low<=tp1
    if stop_hit and (tp1_hit or tp2_hit): return "AMBIGUOUS"
    if stop_hit: return "LOSS_SL"
    if tp2_hit: return "WIN_TP2"
    if tp1_hit: return "WIN_TP1"
    return None


def mark_candle(symbol,candle):
    """Resolve an open trade from a completed 1h candle; runners stay open after TP1/TP2."""
    init_paper_db(); high,low,close=map(float,(candle["high"],candle["low"],candle["close"])); candle_time=candle.get("time") or _now(); atr=float(candle.get("atr") or 0); closed_ids=[]
    with sqlite3.connect(DB) as con:
        rows=con.execute(f"SELECT signal_id,direction,entry,stop_loss,tp1,tp2,max_favorable_pct,max_adverse_pct,opened_at,runner_enabled,runner_active,remaining_pct,realized_pnl_pct,trailing_stop,trailing_atr_multiplier,initial_risk,tp1_hit_at,tp2_hit_at FROM {PAPER_TABLE} WHERE status='OPEN' AND symbol=?",(symbol,)).fetchall()
        for sid,direction,entry,stop,tp1,tp2,old_fav,old_adv,opened_at,runner_enabled,runner_active,remaining_pct,realized,trail,mult,risk,tp1_hit_at,tp2_hit_at in rows:
            opened_dt=_parse_time(opened_at); candle_dt=_parse_time(candle_time)
            if opened_dt and candle_dt and candle_dt<opened_dt: continue
            fav=max(float(old_fav or 0),_favorable(direction,float(entry),high if direction=="LONG" else low)); adv=max(float(old_adv or 0),_adverse(direction,float(entry),low if direction=="LONG" else high))

            if runner_active and atr>0:
                proposed=close-float(mult or 2.0)*atr if direction=="LONG" else close+float(mult or 2.0)*atr
                trail=proposed if trail is None else (max(float(trail),proposed) if direction=="LONG" else min(float(trail),proposed))
                trail_hit=(low<=trail) if direction=="LONG" else (high>=trail)
                if trail_hit:
                    exit_price=float(trail); total_pnl=float(realized or 0)+float(remaining_pct or 0)/100*_pnl(direction,float(entry),exit_price); rr=(float(realized or 0)/100 + float(remaining_pct or 0)/100*_r_value(direction,float(entry),exit_price,float(risk),1.0)) if risk else 0
                    con.execute(f"UPDATE {PAPER_TABLE} SET status='CLOSED',exit_price=?,outcome='WIN_RUNNER',pnl_pct=?,closed_at=?,exit_reason='RUNNER_TRAIL',last_price=?,last_checked_at=?,max_favorable_pct=?,max_adverse_pct=?,trailing_stop=?,realized_pnl_pct=?,realized_r=?,unrealized_r=0,resolution_source='1h_runner' WHERE signal_id=?",(exit_price,total_pnl,candle_time,close,candle_time,fav,adv,trail,total_pnl,rr,sid)); closed_ids.append((sid,"WIN_RUNNER")); continue
                con.execute(f"UPDATE {PAPER_TABLE} SET last_price=?,last_checked_at=?,max_favorable_pct=?,max_adverse_pct=?,trailing_stop=?,unrealized_r=? WHERE signal_id=?",(close,candle_time,fav,adv,trail,_unrealized_r(direction,float(entry),close,float(risk),float(remaining_pct or 0)/100) if risk else 0,sid)); continue

            if runner_enabled:
                stop_hit=(direction=="LONG" and stop is not None and low<=stop) or (direction=="SHORT" and stop is not None and high>=stop)
                tp1_hit=(direction=="LONG" and tp1 is not None and high>=tp1) or (direction=="SHORT" and tp1 is not None and low<=tp1)
                tp2_hit=(direction=="LONG" and tp2 is not None and high>=tp2) or (direction=="SHORT" and tp2 is not None and low<=tp2)
                if stop_hit and (tp1_hit or tp2_hit):
                    con.execute(f"UPDATE {PAPER_TABLE} SET last_price=?,last_checked_at=?,max_favorable_pct=?,max_adverse_pct=?,resolution_source='1h_ohlc_ambiguous' WHERE signal_id=?",(close,candle_time,fav,adv,sid)); continue
                if stop_hit:
                    con.execute(f"UPDATE {PAPER_TABLE} SET status='CLOSED',exit_price=?,outcome='LOSS_SL',pnl_pct=?,closed_at=?,exit_reason='SL',sl_hit_at=?,last_price=?,last_checked_at=?,max_favorable_pct=?,max_adverse_pct=?,resolution_source='1h_ohlc' WHERE signal_id=?",(stop,_pnl(direction,float(entry),float(stop)),candle_time,candle_time,close,candle_time,fav,adv,sid)); closed_ids.append((sid,"LOSS_SL")); continue
                touched=False
                if not tp1_hit_at and tp1_hit:
                    realized_new=float(realized or 0)+TP1_FRACTION*_pnl(direction,float(entry),float(tp1)); remaining_new=float(remaining_pct or 100)-TP1_FRACTION*100
                    con.execute(f"UPDATE {PAPER_TABLE} SET tp1_hit_at=?,remaining_pct=?,realized_pnl_pct=?,trailing_stop=?,last_price=?,last_checked_at=?,max_favorable_pct=?,max_adverse_pct=?,resolution_source='1h_runner' WHERE signal_id=?",(candle_time,remaining_new,realized_new,float(entry),close,candle_time,fav,adv,sid)); tp1_hit_at=candle_time; remaining_pct=remaining_new; realized=realized_new; trail=float(entry); touched=True
                if not tp2_hit_at and tp2_hit:
                    realized_new=float(realized or 0)+TP2_FRACTION*_pnl(direction,float(entry),float(tp2)); remaining_new=max(0,float(remaining_pct or 100)-TP2_FRACTION*100); trail_new=(close-float(mult or 2.0)*atr) if direction=="LONG" and atr>0 else ((close+float(mult or 2.0)*atr) if direction=="SHORT" and atr>0 else float(entry))
                    con.execute(f"UPDATE {PAPER_TABLE} SET tp2_hit_at=?,runner_active=1,remaining_pct=?,realized_pnl_pct=?,trailing_stop=?,last_price=?,last_checked_at=?,max_favorable_pct=?,max_adverse_pct=?,resolution_source='1h_runner' WHERE signal_id=?",(candle_time,remaining_new,realized_new,trail_new,close,candle_time,fav,adv,sid)); touched=True
                if touched:
                    con.execute(f"UPDATE {PAPER_TABLE} SET last_price=?,last_checked_at=?,max_favorable_pct=?,max_adverse_pct=?,unrealized_r=? WHERE signal_id=?",(close,candle_time,fav,adv,(_pnl(direction,float(entry),close)*float(remaining_pct or 0)/100/float(risk)) if risk else 0,sid)); continue

            outcome=_resolve_candle(direction,high,low,stop,tp1,tp2)
            if outcome in {"WIN_TP1","WIN_TP2","LOSS_SL"}:
                exit_price=float(tp2 if outcome=="WIN_TP2" else tp1 if outcome=="WIN_TP1" else stop); reason="TP2" if outcome=="WIN_TP2" else "TP1" if outcome=="WIN_TP1" else "SL"
                con.execute(f"""UPDATE {PAPER_TABLE} SET status='CLOSED',exit_price=?,outcome=?,pnl_pct=?,closed_at=?,exit_reason=?,last_price=?,last_checked_at=?,max_favorable_pct=?,max_adverse_pct=?,resolution_source='1h_ohlc',tp1_hit_at=CASE WHEN ? IN ('WIN_TP1','WIN_TP2') THEN COALESCE(tp1_hit_at,?) ELSE tp1_hit_at END,tp2_hit_at=CASE WHEN ?='WIN_TP2' THEN COALESCE(tp2_hit_at,?) ELSE tp2_hit_at END,sl_hit_at=CASE WHEN ?='LOSS_SL' THEN COALESCE(sl_hit_at,?) ELSE sl_hit_at END WHERE signal_id=?""",(exit_price,outcome,_pnl(direction,float(entry),exit_price),candle_time,reason,close,candle_time,fav,adv,outcome,candle_time,outcome,candle_time,outcome,candle_time,sid)); closed_ids.append((sid,outcome))
            elif outcome=="AMBIGUOUS": con.execute(f"UPDATE {PAPER_TABLE} SET last_price=?,last_checked_at=?,max_favorable_pct=?,max_adverse_pct=?,resolution_source='1h_ohlc_ambiguous' WHERE signal_id=?",(close,candle_time,fav,adv,sid))
            else: con.execute(f"UPDATE {PAPER_TABLE} SET last_price=?,last_checked_at=?,max_favorable_pct=?,max_adverse_pct=?,unrealized_r=? WHERE signal_id=?",(close,candle_time,fav,adv,_unrealized_r(direction,float(entry),close,float(risk)) if risk else 0,sid))
        con.commit()
    for sid,outcome in closed_ids: _sync_setup(sid,outcome)
    return len(closed_ids)


def expire_old_trades(now=None):
    init_paper_db(); now=now or datetime.now(timezone.utc); expired=0
    with sqlite3.connect(DB) as con:
        rows=con.execute(f"SELECT signal_id,last_price,opened_at,direction,entry,remaining_pct,realized_pnl_pct FROM {PAPER_TABLE} WHERE status='OPEN'").fetchall()
        for sid,last_price,opened_at,direction,entry,remaining,realized in rows:
            opened=_parse_time(opened_at)
            if opened and now>=opened+timedelta(hours=24):
                price=float(last_price); pnl=float(realized or 0)+float(remaining or 100)/100*_pnl(direction,float(entry),price)
                con.execute(f"UPDATE {PAPER_TABLE} SET status='CLOSED',exit_price=?,outcome='EXPIRED',pnl_pct=?,closed_at=?,exit_reason='EXPIRED',resolution_source='24h_timeout',realized_pnl_pct=?,unrealized_r=0 WHERE signal_id=?",(price,pnl,now.isoformat(),pnl,sid)); expired+=1
        con.commit()
    return expired


def mark_price(symbol,current_price): return mark_candle(symbol,{"high":current_price,"low":current_price,"close":current_price,"time":_now()})

def close_paper_trade(signal_id,outcome,exit_price):
    if outcome not in {"WIN_TP1","WIN_TP2","WIN_RUNNER","LOSS_SL","CANCELLED","EXPIRED","AMBIGUOUS"}: raise ValueError("Invalid paper-trade outcome")
    init_paper_db()
    with sqlite3.connect(DB) as con:
        row=con.execute(f"SELECT direction,entry,remaining_pct,realized_pnl_pct FROM {PAPER_TABLE} WHERE signal_id=? AND status='OPEN'",(signal_id,)).fetchone()
        if not row:return False
        direction,entry,remaining,realized=row; pnl=float(realized or 0)+float(remaining or 100)/100*_pnl(direction,float(entry),float(exit_price)); now=_now(); con.execute(f"UPDATE {PAPER_TABLE} SET status='CLOSED',exit_price=?,outcome=?,pnl_pct=?,closed_at=?,exit_reason=?,realized_pnl_pct=?,unrealized_r=0 WHERE signal_id=?",(exit_price,outcome,pnl,now,outcome.replace('WIN_',''),pnl,signal_id)); con.commit()
    _sync_setup(signal_id,outcome); return True


def paper_summary():
    init_paper_db()
    with sqlite3.connect(DB) as con:
        total=con.execute(f"SELECT COUNT(*) FROM {PAPER_TABLE}").fetchone()[0]; opened=con.execute(f"SELECT COUNT(*) FROM {PAPER_TABLE} WHERE status='OPEN'").fetchone()[0]; closed=con.execute(f"SELECT COUNT(*) FROM {PAPER_TABLE} WHERE status='CLOSED'").fetchone()[0]; pnl=con.execute(f"SELECT COALESCE(SUM(pnl_pct),0) FROM {PAPER_TABLE} WHERE status='CLOSED' AND outcome!='AMBIGUOUS'").fetchone()[0]; wins=con.execute(f"SELECT COUNT(*) FROM {PAPER_TABLE} WHERE outcome IN ('WIN_TP1','WIN_TP2','WIN_RUNNER')").fetchone()[0]; losses=con.execute(f"SELECT COUNT(*) FROM {PAPER_TABLE} WHERE outcome='LOSS_SL'").fetchone()[0]; tp1=con.execute(f"SELECT COUNT(*) FROM {PAPER_TABLE} WHERE outcome='WIN_TP1'").fetchone()[0]; tp2=con.execute(f"SELECT COUNT(*) FROM {PAPER_TABLE} WHERE outcome='WIN_TP2'").fetchone()[0]; runners=con.execute(f"SELECT COUNT(*) FROM {PAPER_TABLE} WHERE outcome='WIN_RUNNER'").fetchone()[0]; expired=con.execute(f"SELECT COUNT(*) FROM {PAPER_TABLE} WHERE outcome='EXPIRED'").fetchone()[0]; ambiguous=con.execute(f"SELECT COUNT(*) FROM {PAPER_TABLE} WHERE outcome='AMBIGUOUS'").fetchone()[0]
    resolved=wins+losses
    return {'total':total,'open':opened,'closed':closed,'wins':wins,'losses':losses,'tp1':tp1,'tp2':tp2,'runners':runners,'expired':expired,'ambiguous':ambiguous,'win_rate_pct':round(wins/resolved*100,2) if resolved else 0.0,'sl_rate_pct':round(losses/resolved*100,2) if resolved else 0.0,'pnl_pct':round(float(pnl),4),'avg_pnl_pct':round(float(pnl)/resolved,4) if resolved else 0.0}
