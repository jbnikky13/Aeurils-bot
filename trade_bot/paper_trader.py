"""Deterministic paper-trading ledger. Never submits exchange orders."""
import sqlite3
from datetime import datetime, timezone
from .journal import DB, init_db

PAPER_TABLE = "paper_trades"


def _now():
    return datetime.now(timezone.utc).isoformat()


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
        }
        for col, typ in additions.items():
            if col not in cols:
                con.execute(f"ALTER TABLE {PAPER_TABLE} ADD COLUMN {col} {typ}")
        con.commit()


def open_paper_trade(signal_id, symbol, direction, entry, stop_loss=None, tp1=None,
                     tp2=None, final_score=None, market_regime="UNKNOWN",
                     gemini_decision=None, gemini_confidence=None, gemini_available=None):
    init_paper_db()
    with sqlite3.connect(DB) as con:
        cur = con.execute(
            f"""INSERT OR IGNORE INTO {PAPER_TABLE}
            (signal_id,symbol,direction,entry,stop_loss,tp1,tp2,opened_at,final_score,market_regime,gemini_decision,gemini_confidence,gemini_available,last_price,last_checked_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (signal_id, symbol, direction, float(entry), stop_loss, tp1, tp2, _now(), final_score, market_regime,
             gemini_decision, gemini_confidence, gemini_available, float(entry), _now()))
        con.commit()
        return cur.rowcount == 1


def _pnl(direction, entry, exit_price):
    return ((exit_price - entry) / entry * 100 if direction == "LONG"
            else (entry - exit_price) / entry * 100 if direction == "SHORT" else 0.0)


def _touch_outcome(direction, price, stop, tp1, tp2):
    if direction == "LONG":
        if stop is not None and price <= stop: return "LOSS_SL"
        if tp2 is not None and price >= tp2: return "WIN_TP2"
        if tp1 is not None and price >= tp1: return "WIN_TP1"
    elif direction == "SHORT":
        if stop is not None and price >= stop: return "LOSS_SL"
        if tp2 is not None and price <= tp2: return "WIN_TP2"
        if tp1 is not None and price <= tp1: return "WIN_TP1"
    return None


def _favorable(direction, entry, price):
    return max(0.0, _pnl(direction, entry, price))


def _adverse(direction, entry, price):
    return max(0.0, -_pnl(direction, entry, price))


def _sync_setup(signal_id, outcome):
    with sqlite3.connect(DB) as con:
        con.execute("UPDATE setups SET outcome=?, closed_at=? WHERE id=? AND outcome='OPEN'",
                    (outcome, _now(), signal_id))
        con.commit()


def mark_price(symbol, current_price):
    """Evaluate open paper trades, update excursion data, and synchronize closed outcomes."""
    init_paper_db(); closed_ids = []
    price = float(current_price); checked = _now()
    with sqlite3.connect(DB) as con:
        rows = con.execute(
            f"SELECT signal_id,direction,entry,stop_loss,tp1,tp2,max_favorable_pct,max_adverse_pct FROM {PAPER_TABLE} WHERE status='OPEN' AND symbol=?",
            (symbol,)).fetchall()
        for sid, direction, entry, stop, tp1, tp2, old_fav, old_adv in rows:
            fav = max(float(old_fav or 0), _favorable(direction, float(entry), price))
            adv = max(float(old_adv or 0), _adverse(direction, float(entry), price))
            outcome = _touch_outcome(direction, price, stop, tp1, tp2)
            if outcome:
                pnl = _pnl(direction, float(entry), price)
                reason = "TP2" if outcome == "WIN_TP2" else "TP1" if outcome == "WIN_TP1" else "SL"
                con.execute(
                    f"""UPDATE {PAPER_TABLE}
                    SET status='CLOSED',exit_price=?,outcome=?,pnl_pct=?,closed_at=?,exit_reason=?,last_price=?,last_checked_at=?,
                        max_favorable_pct=?,max_adverse_pct=?,
                        tp1_hit_at=CASE WHEN ? IN ('WIN_TP1','WIN_TP2') THEN COALESCE(tp1_hit_at,?) ELSE tp1_hit_at END,
                        tp2_hit_at=CASE WHEN ?='WIN_TP2' THEN COALESCE(tp2_hit_at,?) ELSE tp2_hit_at END,
                        sl_hit_at=CASE WHEN ?='LOSS_SL' THEN COALESCE(sl_hit_at,?) ELSE sl_hit_at END
                    WHERE signal_id=?""",
                    (price, outcome, pnl, checked, reason, price, checked, fav, adv,
                     outcome, checked, outcome, checked, outcome, checked, sid))
                closed_ids.append((sid, outcome))
            else:
                con.execute(
                    f"UPDATE {PAPER_TABLE} SET last_price=?,last_checked_at=?,max_favorable_pct=?,max_adverse_pct=? WHERE signal_id=?",
                    (price, checked, fav, adv, sid))
        con.commit()
    for sid, outcome in closed_ids:
        _sync_setup(sid, outcome)
    return len(closed_ids)


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
    return {'total': total, 'open': opened, 'closed': closed, 'wins': wins, 'losses': losses,
            'tp1': tp1, 'tp2': tp2,
            'win_rate_pct': round(wins / closed * 100, 2) if closed else 0.0,
            'sl_rate_pct': round(losses / closed * 100, 2) if closed else 0.0,
            'pnl_pct': round(float(pnl), 4), 'avg_pnl_pct': round(float(pnl) / closed, 4) if closed else 0.0}
