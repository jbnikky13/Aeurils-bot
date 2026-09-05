"""Performance analytics for completed Aeurils signals."""
import sqlite3
from .journal import DB, init_db

def summary():
    init_db()
    with sqlite3.connect(DB) as con:
        rows = con.execute("SELECT outcome, asset_type, COUNT(*) FROM setups WHERE outcome != 'OPEN' GROUP BY outcome, asset_type").fetchall()
        total = con.execute("SELECT COUNT(*) FROM setups WHERE outcome != 'OPEN'").fetchone()[0]
        wins = con.execute("SELECT COUNT(*) FROM setups WHERE outcome IN ('WIN_TP1','WIN_TP2')").fetchone()[0]
        losses = con.execute("SELECT COUNT(*) FROM setups WHERE outcome='LOSS_SL'").fetchone()[0]
        open_count = con.execute("SELECT COUNT(*) FROM setups WHERE outcome='OPEN'").fetchone()[0]
    closed = wins + losses
    return {"total_closed": total, "wins": wins, "losses": losses, "open": open_count, "win_rate": (wins / closed * 100) if closed else 0.0, "breakdown": rows}

def format_summary():
    s = summary()
    lines = ["📈 AURELIS PERFORMANCE", "", f"Closed: {s['total_closed']}", f"Wins: {s['wins']}", f"Losses: {s['losses']}", f"Open: {s['open']}", f"Win rate: {s['win_rate']:.1f}%"]
    if s["breakdown"]:
        lines += ["", "By outcome / asset:"] + [f"• {o} / {a}: {n}" for o, a, n in s["breakdown"]]
    lines += ["", "Performance is based only on recorded journal outcomes; it is not a guarantee of future results."]
    return "\n".join(lines)
