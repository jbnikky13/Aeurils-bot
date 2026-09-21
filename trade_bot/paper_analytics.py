"""Independent paper-trading analytics for AURELIS.

Calculations use entry/exit prices and recorded pnl_pct, never the legacy
realized_r/unrealized_r fields. Open trades are excluded from closed-trade
performance. Ambiguous OHLC candles are excluded from win/loss rates.
"""
import json
import os
import sqlite3
from collections import defaultdict
from datetime import datetime

DB = os.getenv("DATABASE_PATH", "trade_bot.db")
FEE_BPS_PER_SIDE = float(os.getenv("PAPER_FEE_BPS_PER_SIDE", "10"))
ROUND_TRIP_FEE_PCT = (2 * FEE_BPS_PER_SIDE) / 100.0


def _num(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _dt(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return datetime.min


def _rows():
    if not os.path.exists(DB):
        return []
    with sqlite3.connect(DB) as con:
        con.row_factory = sqlite3.Row
        tables = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        if "paper_trades" not in tables:
            return []
        return con.execute("SELECT * FROM paper_trades").fetchall()


def _net_pnl(row):
    """Return price P&L after one entry and one exit fee."""
    return _num(row["pnl_pct"]) - ROUND_TRIP_FEE_PCT


def _group(rows, key_fn):
    out = defaultdict(lambda: {"trades": 0, "wins": 0, "losses": 0, "pnl": 0.0})
    for r in rows:
        key = key_fn(r)
        out[key]["trades"] += 1
        out[key]["pnl"] += _net_pnl(r)
        if str(r["outcome"] or "").startswith("WIN_"):
            out[key]["wins"] += 1
        elif str(r["outcome"] or "") == "LOSS_SL":
            out[key]["losses"] += 1
    return [
        {
            "key": str(k),
            **v,
            "win_rate_pct": round(v["wins"] / (v["wins"] + v["losses"]) * 100, 2)
            if v["wins"] + v["losses"] else 0.0,
            "pnl": round(v["pnl"], 4),
        }
        for k, v in sorted(out.items(), key=lambda item: item[1]["pnl"], reverse=True)
    ]


def analytics():
    rows = _rows()
    closed = [r for r in rows if str(r["status"]).upper() == "CLOSED" and str(r["outcome"] or "").upper() != "AMBIGUOUS"]
    resolved = [r for r in closed if str(r["outcome"] or "").upper() in {
        "WIN_TP1", "WIN_TP2", "WIN_RUNNER", "LOSS_SL", "EXPIRED"
    }]
    scored = [r for r in closed if str(r["outcome"] or "").upper() in {
        "WIN_TP1", "WIN_TP2", "WIN_RUNNER", "LOSS_SL"
    }]
    wins = [r for r in scored if str(r["outcome"] or "").startswith("WIN_")]
    losses = [r for r in scored if str(r["outcome"] or "") == "LOSS_SL"]
    pnls = [_net_pnl(r) for r in closed]
    win_pnls = [_net_pnl(r) for r in wins]
    loss_pnls = [_net_pnl(r) for r in losses]

    equity = peak = max_dd = 0.0
    for r in sorted(closed, key=lambda x: _dt(x["closed_at"])):
        equity += _net_pnl(r)
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)

    gross_profit = sum(max(0.0, p) for p in pnls)
    gross_loss = abs(sum(min(0.0, p) for p in pnls))
    report = {
        "paper_trades": len(rows),
        "open": sum(str(r["status"]).upper() == "OPEN" for r in rows),
        "closed": len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "expired": sum(str(r["outcome"] or "") == "EXPIRED" for r in closed),
        "ambiguous": sum(str(r["outcome"] or "") == "AMBIGUOUS" for r in rows),
        "win_rate_pct": round(len(wins) / len(scored) * 100, 2) if scored else 0.0,
        "net_pnl_pct": round(sum(pnls), 4),
        "avg_trade_pct": round(sum(pnls) / len(closed), 4) if closed else 0.0,
        "avg_win_pct": round(sum(win_pnls) / len(win_pnls), 4) if win_pnls else 0.0,
        "avg_loss_pct": round(sum(loss_pnls) / len(loss_pnls), 4) if loss_pnls else 0.0,
        "profit_factor": round(gross_profit / gross_loss, 4) if gross_loss else None,
        "expectancy_pct": round(sum(_net_pnl(r) for r in scored) / len(scored), 4) if scored else 0.0,
        "max_drawdown_pct": round(max_dd, 4),
        "fee_assumption_pct": ROUND_TRIP_FEE_PCT,
        "by_direction": _group(closed, lambda r: str(r["direction"] or "UNKNOWN").upper()),
        "by_regime": _group(closed, lambda r: str(r["market_regime"] or "UNKNOWN")),
        "by_score": _group(closed, lambda r: (
            "65-69" if _num(r["final_score"]) < 70 else
            "70-74" if _num(r["final_score"]) < 75 else
            "75+"
        )),
        "by_gemini": _group(closed, lambda r: (
            "AVAILABLE" if _num(r["gemini_available"]) == 1 else "UNAVAILABLE"
        )),
        "by_symbol": _group(closed, lambda r: str(r["symbol"] or "UNKNOWN")),
        "outcomes": dict(sorted(
            ((str(r["outcome"] or "UNKNOWN"), sum(
                1 for x in closed if str(x["outcome"] or "UNKNOWN") == str(r["outcome"] or "UNKNOWN")
            )) for r in closed),
            key=lambda x: x[0]
        )),
    }
    return report


def format_report():
    a = analytics()
    pf = "N/A" if a["profit_factor"] is None else f"{a['profit_factor']:.2f}"
    lines = [
        "📊 AURELIS PAPER PERFORMANCE",
        "",
        f"Paper trades: {a['paper_trades']} | Open: {a['open']} | Closed: {a['closed']}",
        f"Wins: {a['wins']} | Losses: {a['losses']} | Expired: {a['expired']}",
        f"Win rate: {a['win_rate_pct']:.1f}%",
        f"Net P&L after fees: {a['net_pnl_pct']:.2f}%",
        f"Expectancy: {a['expectancy_pct']:.2f}% / scored trade",
        f"Avg win: {a['avg_win_pct']:.2f}% | Avg loss: {a['avg_loss_pct']:.2f}%",
        f"Profit factor: {pf}",
        f"Max drawdown: {a['max_drawdown_pct']:.2f}%",
        f"Fee assumption: {a['fee_assumption_pct']:.2f}% round trip",
        "",
        "By direction:",
    ]
    lines += [f"• {x['key']}: {x['trades']} | {x['win_rate_pct']:.1f}% WR | {x['pnl']:.2f}%"
              for x in a["by_direction"]]
    lines += ["", "By regime:"]
    lines += [f"• {x['key']}: {x['trades']} | {x['win_rate_pct']:.1f}% WR | {x['pnl']:.2f}%"
              for x in a["by_regime"]]
    lines += ["", "By score band:"]
    lines += [f"• {x['key']}: {x['trades']} | {x['win_rate_pct']:.1f}% WR | {x['pnl']:.2f}%"
              for x in a["by_score"]]
    lines += ["", "Gemini availability:"]
    lines += [f"• {x['key']}: {x['trades']} | {x['win_rate_pct']:.1f}% WR | {x['pnl']:.2f}%"
              for x in a["by_gemini"]]
    lines += ["", "🧪 Paper-only analytics; historical simulation does not guarantee future results."]
    return "\n".join(lines)


if __name__ == "__main__":
    print(json.dumps(analytics(), indent=2, sort_keys=True))
    print()
    print(format_report())
