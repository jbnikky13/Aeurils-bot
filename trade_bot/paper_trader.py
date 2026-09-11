"""Deterministic paper-trading ledger with intrabar-aware resolution."""
import sqlite3
from datetime import datetime, timezone, timedelta
from .journal import DB, init_db

PAPER_TABLE = "paper_trades"


def _now():
    return datetime.now(timezone.utc).isoformat()


def _parse_time(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def init_paper_db():
    init_db()
    with sqlite3.connect(DB) as con:
        con.execute(f"""CREATE TABLE IF NOT EXISTS {PAPER_TABLE} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_id INTEGER UNIQUE NOT NULL,
            symbol TEXT NOT NULL,
            direction TEXT NOT NULL,
            entry REAL NOT NULL,
            stop_loss REAL,
            tp1 REAL,
            tp2 REAL,
            status TEXT NOT NULL DEFAULT 'OPEN',
            exit_price REAL,
            outcome TEXT,
            pnl_pct REAL,
            opened_at TEXT NOT NULL,
            closed_at TEXT,
            final_score REAL,
            market_regime TEXT DEFAULT 'UNKNOWN',
            gemini_decision TEXT,
            gemini_confidence REAL,
            gemini_available INTEGER
        )""")
        cols = {r[1] for r in con.execute(f"PRAGMA table_info({PAPER_TABLE})")}
        additions = {
            "final_score": "REAL", "market_regime": "TEXT DEFAULT 'UNKNOWN'",
            "gemini_decision": "TEXT", "gemini_confidence": "REAL", "gemini_available": "INTEGER",
            "tp1_hit_at": "TEXT", "tp2_hit_at": "TEXT", "sl_hit_at": "TEXT",
            "exit_reason": "TEXT", "last_price": "REAL", "last_checked_at": "TEXT",
            "max_favorable_pct": "REAL DEFAULT 0", "max_adverse_pct": "REAL DEFAULT 0",
            "expiry_at": "TEXT", "resolution_source": "TEXT"
        }
        for col, typ in additions.items():
            if col not in cols:
                con.execute(f"ALTER TABLE {PAPER_TABLE} ADD COLUMN {col} {typ}")
        con.commit()


def open_paper_trade(signal_id, symbol, direction, entry, stop_loss=None, tp1=None,
                     tp2=None, final_score=None, market_regime="UNKNOWN",
                     gemini_decision=None, gemini_confidence=None, gemini_available=None):
    init_paper_db()
    opened = datetime.now(timezone.utc)
    expiry = opened + timedelta(hours=24)
    with sqlite3.connect(DB) as con:
        cur = con.execute(
            f"""INSERT OR IGNORE INTO {PAPER_TABLE}
            (signal_id,symbol,direction,entry,stop_loss,tp1,tp2,opened_at,final_score,market_regime,gemini_decision,gemini_confidence,gemini_available,last_price,last_checked_at,expiry_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (signal_id, symbol, direction, float(entry), stop_loss, tp1, tp2, opened.isoformat(), final_score, market_regime,
             gemini_decision, gemini_confidence, gemini_available, float(entry), opened.isoformat(), expiry.isoformat())
        )
        con.commit()
        return cur.rowcount == 1


def _pnl(direction, entry, exit_price):
    return ((exit_price - entry) / entry * 100 if direction == "LONG"
            else (entry - exit_price) / entry * 100 if direction == "SHORT" else 0.0)


def _favorable(direction, entry, price):
    return max(0.0, _pnl(direction, entry, price))


def _adverse(direction, entry, price):
    return max(0.0, -_pnl(direction, entry, price))


def _sync_setup(signal_id, outcome):
    with sqlite3.connect(DB) as con:
        con.execute("UPDATE setups SET outcome=?, closed_at=? WHERE id=? AND outcome='OPEN'",
                    (outcome, _now(), signal_id))
        con.commit()


def _resolve_candle(direction, high, low, stop, tp1, tp2):
    """Resolve a candle using its actual range.

    If both a target and stop are inside the same 1-minute candle, the stop is
    conservatively treated as first. This avoids look-ahead optimism when the
    exact tick sequence is unavailable.
    """
    if direction == "LONG":
        stop_hit = stop is not None and low <= stop
        tp2_hit = tp2 is not None and high >= tp2
        tp1_hit = tp1 is not None and high >= tp1
    else:
        stop_hit = stop is not None and high >= stop
        tp2_hit = tp2 is not None and low <= tp2
        tp1_hit = tp1 is not None and low <= tp1
    if stop_hit:
        return "LOSS_SL"
    if tp2_hit:
        return "WIN_TP2"
    if tp1_hit:
        return "WIN_TP1"
    return None


def mark_candle(symbol, candle):
    """Resolve all open trades for one completed OHLC candle."""
    init_paper_db()
    high, low, close = float(candle["high"]), float(candle["low"]), float(candle["close"])
    candle_time = candle.get("time") or _now()
    closed_ids = []
    with sqlite3.connect(DB) as con:
        rows = con.execute(
            f"SELECT signal_id,direction,entry,stop_loss,tp1,tp2,max_favorable_pct,max_adverse_pct,opened_at FROM {PAPER_TABLE} WHERE status='OPEN' AND symbol=?",
            (symbol,)
        ).fetchall()
        for sid, direction, entry, stop, tp1, tp2, old_fav, old_adv, opened_at in rows:
            opened_dt = _parse_time(opened_at)
            candle_dt = _parse_time(candle_time)
            if opened_dt and candle_dt and candle_dt < opened_dt:
                continue
            fav_price = high if direction == "LONG" else low
            adv_price = low if direction == "LONG" else high
            fav = max(float(old_fav or 0), _favorable(direction, float(entry), fav_price))
            adv = max(float(old_adv or 0), _adverse(direction, float(entry), adv_price))
            outcome = _resolve_candle(direction, high, low, stop, tp1, tp2)
            if outcome:
                if outcome == "WIN_TP2": exit_price = float(tp2)
                elif outcome == "WIN_TP1": exit_price = float(tp1)
                else: exit_price = float(stop)
                reason = "TP2" if outcome == "WIN_TP2" else "TP1" if outcome == "WIN_TP1" else "SL"
                con.execute(
                    f"""UPDATE {PAPER_TABLE} SET status='CLOSED',exit_price=?,outcome=?,pnl_pct=?,closed_at=?,exit_reason=?,last_price=?,last_checked_at=?,
                        max_favorable_pct=?,max_adverse_pct=?,resolution_source='1m_ohlc',
                        tp1_hit_at=CASE WHEN ? IN ('WIN_TP1','WIN_TP2') THEN COALESCE(tp1_hit_at,?) ELSE tp1_hit_at END,
                        tp2_hit_at=CASE WHEN ?='WIN_TP2' THEN COALESCE(tp2_hit_at,?) ELSE tp2_hit_at END,
                        sl_hit_at=CASE WHEN ?='LOSS_SL' THEN COALESCE(sl_hit_at,?) ELSE sl_hit_at END
                    WHERE signal_id=?""",
                    (exit_price, outcome, _pnl(direction, float(entry), exit_price), candle_time, reason,
                     close, candle_time, fav, adv, outcome, candle_time, outcome, candle_time, outcome, candle_time, sid)
                )
                closed_ids.append((sid, outcome))
            else:
                con.execute(
                    f"UPDATE {PAPER_TABLE} SET last_price=?,last_checked_at=?,max_favorable_pct=?,max_adverse_pct=?,resolution_source='1m_ohlc' WHERE signal_id=?",
                    (close, candle_time, fav, adv, sid)
                )
        con.commit()
    for sid, outcome in closed_ids:
        _sync_setup(sid, outcome)
    return len(closed_ids)


def expire_old_trades(now=None):
    """Close unresolved trades at the latest observed price after 24 hours."""
    init_paper_db(); now = now or datetime.now(timezone.utc)
    expired = 0
    with sqlite3.connect(DB) as con:
        rows = con.execute(f"SELECT signal_id,last_price,opened_at FROM {PAPER_TABLE} WHERE status='OPEN'").fetchall()
        for sid, last_price, opened_at in rows:
            opened = _parse_time(opened_at)
            if opened and now >= opened + timedelta(hours=24):
                price = float(last_price)
                row = con.execute(f"SELECT direction,entry FROM {PAPER_TABLE} WHERE signal_id=?", (sid,)).fetchone()
                if not row: continue
                pnl = _pnl(row[0], float(row[1]), price)
                con.execute(f"UPDATE {PAPER_TABLE} SET status='CLOSED',exit_price=?,outcome='EXPIRED',pnl_pct=?,closed_at=?,exit_reason='EXPIRED',resolution_source='24h_timeout' WHERE signal_id=?",
                             (price, pnl, now.isoformat(), sid))
                expired += 1
        con.commit()
    if expired:
        with sqlite3.connect(DB) as con:
            rows = con.execute(f"SELECT signal_id FROM {PAPER_TABLE} WHERE outcome='EXPIRED' AND closed_at=?", (now.isoformat(),)).fetchall()
        for (sid,) in rows: _sync_setup(sid, "EXPIRED")
    return expired


def mark_price(symbol, current_price):
    """Compatibility path for callers that only have a spot price."""
    return mark_candle(symbol, {"high": current_price, "low": current_price, "close": current_price, "time": _now()})


def close_paper_trade(signal_id, outcome, exit_price):
    if outcome not in {"WIN_TP1", "WIN_TP2", "LOSS_SL", "CANCELLED", "EXPIRED"}:
        raise ValueError("Invalid paper-trade outcome")
    init_paper_db()
    with sqlite3.connect(DB) as con:
        row = con.execute(f"SELECT direction,entry FROM {PAPER_TABLE} WHERE signal_id=? AND status='OPEN'", (signal_id,)).fetchone()
        if not row: return False
        pnl = _pnl(row[0], float(row[1]), float(exit_price))
        now = _now()
        con.execute(f"UPDATE {PAPER_TABLE} SET status='CLOSED',exit_price=?,outcome=?,pnl_pct=?,closed_at=?,exit_reason=? WHERE signal_id=?",
                     (exit_price, outcome, pnl, now, outcome.replace('WIN_', ''), signal_id))
        con.commit()
    _sync_setup(signal_id, outcome)
    return True


def paper_summary():
    init_paper_db()
    with sqlite3.connect(DB) as con:
        total = con.execute(f"SELECT COUNT(*) FROM {PAPER_TABLE}").fetchone()[0]
        opened = con.execute(f"SELECT COUNT(*) FROM {PAPER_TABLE} WHERE status='OPEN'").fetchone()[0]
        closed = con.execute(f"SELECT COUNT(*) FROM {PAPER_TABLE} WHERE status='CLOSED'").fetchone()[0]
        pnl = con.execute(f"SELECT COALESCE(SUM(pnl_pct),0) FROM {PAPER_TABLE} WHERE status='CLOSED'").fetchone()[0]
        wins = con.execute(f"SELECT COUNT(*) FROM {PAPER_TABLE} WHERE outcome IN ('WIN_TP1','WIN_TP2')").fetchone()[0]
        losses = con.execute(f"SELECT COUNT(*) FROM {PAPER_TABLE} WHERE outcome='LOSS_SL'").fetchone()[0]
        tp1 = con.execute(f"SELECT COUNT(*) FROM {PAPER_TABLE} WHERE outcome='WIN_TP1'").fetchone()[0]
        tp2 = con.execute(f"SELECT COUNT(*) FROM {PAPER_TABLE} WHERE outcome='WIN_TP2'").fetchone()[0]
        expired = con.execute(f"SELECT COUNT(*) FROM {PAPER_TABLE} WHERE outcome='EXPIRED'").fetchone()[0]
    return {'total': total, 'open': opened, 'closed': closed, 'wins': wins, 'losses': losses,
            'tp1': tp1, 'tp2': tp2, 'expired': expired,
            'win_rate_pct': round(wins / closed * 100, 2) if closed else 0.0,
            'sl_rate_pct': round(losses / closed * 100, 2) if closed else 0.0,
            'pnl_pct': round(float(pnl), 4), 'avg_pnl_pct': round(float(pnl) / closed, 4) if closed else 0.0}
