"""Signal lifecycle and duplicate protection for Aeurils."""
import hashlib
import sqlite3
from datetime import datetime, timezone
from .journal import DB, init_db


def _key(s):
    raw = "|".join(str(getattr(s, k, "")) for k in ("symbol","asset_type","direction","entry_low","entry_high","stop_loss","take_profit_1","take_profit_2"))
    return hashlib.sha256(raw.encode()).hexdigest()


def init_lifecycle_db():
    init_db()
    with sqlite3.connect(DB) as con:
        cols = {r[1] for r in con.execute("PRAGMA table_info(setups)")}
        if "signal_key" not in cols: con.execute("ALTER TABLE setups ADD COLUMN signal_key TEXT")
        if "updated_at" not in cols: con.execute("ALTER TABLE setups ADD COLUMN updated_at TEXT")
        con.execute("CREATE INDEX IF NOT EXISTS idx_setups_signal_key ON setups(signal_key)")


def is_duplicate(s, lookback_hours=24):
    init_lifecycle_db()
    key = _key(s)
    with sqlite3.connect(DB) as con:
        row = con.execute("SELECT id FROM setups WHERE signal_key=? AND created_at >= datetime('now', ?)", (key, f"-{int(lookback_hours)} hours")).fetchone()
    return row[0] if row else None


def record_open(s):
    init_lifecycle_db()
    duplicate = is_duplicate(s)
    if duplicate: return duplicate, False
    from .journal import record_setup
    signal_id = record_setup(s)
    with sqlite3.connect(DB) as con:
        con.execute("UPDATE setups SET signal_key=?, updated_at=? WHERE id=?", (_key(s), datetime.now(timezone.utc).isoformat(), signal_id))
    return signal_id, True


def close_signal(signal_id, outcome):
    if outcome not in {"WIN_TP1", "WIN_TP2", "LOSS_SL", "CANCELLED", "EXPIRED"}:
        raise ValueError("Invalid lifecycle outcome")
    init_lifecycle_db()
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(DB) as con:
        cur = con.execute("UPDATE setups SET outcome=?, closed_at=?, updated_at=? WHERE id=? AND outcome='OPEN'", (outcome, now, now, signal_id))
        return cur.rowcount == 1


def open_signals():
    init_lifecycle_db()
    with sqlite3.connect(DB) as con:
        con.row_factory = sqlite3.Row
        return [dict(r) for r in con.execute("SELECT * FROM setups WHERE outcome='OPEN' ORDER BY created_at DESC").fetchall()]
