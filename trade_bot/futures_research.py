"""Risk-aware research layer for AURELIS futures backtests.

Consumes the JSON produced by futures_backtest.py and converts raw trade-level
price returns into a conservative equity/risk simulation. This is research only:
no orders are placed and no live credentials are used.

The model explicitly reports gross and cost-adjusted results, long/short splits,
strategy splits, regime-neutral time splits (60/20/20), drawdown, expectancy,
profit factor, consecutive losses, and a BRUSDT-specific case study.
"""
from __future__ import annotations
import argparse, json, math
from collections import defaultdict
from datetime import datetime, timezone


def pct(v):
    return float(v or 0.0)


def max_drawdown(equity):
    peak = equity[0] if equity else 1.0
    worst = 0.0
    for x in equity:
        peak = max(peak, x)
        worst = min(worst, (x / peak - 1.0) * 100.0)
    return worst


def longest_loss_streak(values):
    best = cur = 0
    for v in values:
        if v < 0:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def metrics(trades, starting_equity=100.0, risk_per_trade=0.01,
            taker_fee=0.0005, slippage=0.0005, funding_per_8h=0.0001,
            leverage_cap=3.0):
    """Risk model.

    Each trade risks risk_per_trade of current equity based on its actual stop
    distance, capped at leverage_cap notional. Fee/slippage are charged on an
    estimated round-trip notional. Funding is a conservative placeholder per
    8-hour settlement and is only charged for estimated holding periods.
    Historical funding is intentionally not fabricated.
    """
    equity = float(starting_equity)
    curve = [equity]
    gross = net = fees = funding = 0.0
    wins = losses = 0
    r_values = []
    rows = []

    for t in sorted(trades, key=lambda x: x.get("entry_time", "")):
        entry = pct(t.get("entry")); stop = pct(t.get("stop")); price_pnl = pct(t.get("pnl_pct"))
        if entry <= 0 or stop <= 0:
            continue
        stop_pct = abs(entry - stop) / entry
        if stop_pct <= 0:
            continue
        notional_fraction = min(leverage_cap, risk_per_trade / stop_pct)
        # pnl_pct is the percentage return on 1x notional for the simulated
        # partial TP/runner lifecycle.
        gross_trade = notional_fraction * price_pnl
        entry_dt = t.get("entry_time", "")
        exit_dt = t.get("exit_time", "")
        try:
            hold_hours = max(0.0, (datetime.fromisoformat(exit_dt.replace("Z", "+00:00")) - datetime.fromisoformat(entry_dt.replace("Z", "+00:00"))).total_seconds() / 3600.0)
        except Exception:
            hold_hours = 0.0
        funding_rounds = math.floor(hold_hours / 8.0)
        # Funding is modeled as a neutral conservative cost rather than a
        # fabricated historical rate; direction-specific real funding comes
        # from Binance history in the next data-integrity phase.
        funding_cost = notional_fraction * funding_rounds * funding_per_8h * 100.0
        round_trip_cost = notional_fraction * (2.0 * (taker_fee + slippage)) * 100.0
        net_trade = gross_trade - round_trip_cost - funding_cost
        equity *= (1.0 + net_trade / 100.0)
        curve.append(equity)
        gross += gross_trade
        fees += round_trip_cost
        funding += funding_cost
        net += net_trade
        r = price_pnl / (stop_pct * 100.0)
        r_values.append(r)
        if net_trade > 0: wins += 1
        elif net_trade < 0: losses += 1
        rows.append({"symbol": t.get("symbol"), "direction": t.get("direction"), "mode": t.get("mode"), "outcome": t.get("outcome"), "net_trade_pct": net_trade, "gross_trade_pct": gross_trade, "risk_R": r, "holding_hours": hold_hours})

    profit = sum(x["net_trade_pct"] for x in rows if x["net_trade_pct"] > 0)
    loss = -sum(x["net_trade_pct"] for x in rows if x["net_trade_pct"] < 0)
    return {
        "trades": len(rows), "wins": wins, "losses": losses,
        "win_rate_pct": round(100 * wins / len(rows), 2) if rows else 0.0,
        "ending_equity": round(equity, 4),
        "net_return_pct": round((equity / starting_equity - 1) * 100, 4),
        "gross_trade_contribution_pct": round(gross, 4),
        "fees_pct_equity_basis": round(fees, 4),
        "estimated_funding_cost_pct": round(funding, 4),
        "profit_factor": round(profit / loss, 4) if loss else None,
        "expectancy_pct_per_trade": round(net / len(rows), 5) if rows else 0.0,
        "avg_R": round(sum(r_values) / len(r_values), 4) if r_values else 0.0,
        "max_drawdown_pct": round(max_drawdown(curve), 4),
        "max_consecutive_losses": longest_loss_streak([x["net_trade_pct"] for x in rows]),
        "curve": [round(x, 6) for x in curve],
        "trades_detail": rows,
    }


def split_periods(trades):
    ordered = sorted(trades, key=lambda x: x.get("entry_time", ""))
    n = len(ordered)
    if n < 3:
        return {"development_60": ordered, "validation_20": [], "out_of_sample_20": []}
    a = max(1, int(n * 0.60)); b = max(a + 1, int(n * 0.80))
    return {"development_60": ordered[:a], "validation_20": ordered[a:b], "out_of_sample_20": ordered[b:]}


def grouped(trades, key):
    out = {}
    groups = defaultdict(list)
    for t in trades: groups[t.get(key, "UNKNOWN")].append(t)
    for k, xs in sorted(groups.items()): out[k] = metrics(xs)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("report")
    ap.add_argument("--starting-equity", type=float, default=100.0)
    ap.add_argument("--risk-per-trade", type=float, default=0.01)
    ap.add_argument("--taker-fee", type=float, default=0.0005)
    ap.add_argument("--slippage", type=float, default=0.0005)
    ap.add_argument("--funding-per-8h", type=float, default=0.0001)
    ap.add_argument("--leverage-cap", type=float, default=3.0)
    args = ap.parse_args()
    raw = json.load(open(args.report, encoding="utf-8"))
    trades = [t for t in raw.get("trades_detail", []) if t.get("outcome") not in ("OPEN", "AMBIGUOUS")]

    def calc(xs):
        return metrics(xs, args.starting_equity, args.risk_per_trade, args.taker_fee, args.slippage, args.funding_per_8h, args.leverage_cap)

    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": args.report,
        "source_window": {"start": raw.get("start"), "end": raw.get("end"), "days": raw.get("days")},
        "cost_assumptions": {"taker_fee": args.taker_fee, "slippage": args.slippage, "funding_per_8h_placeholder": args.funding_per_8h, "note": "Funding is deliberately conservative placeholder until historical funding is joined; Binance funding is periodic and direction-dependent."},
        "risk_assumptions": {"starting_equity": args.starting_equity, "risk_per_trade": args.risk_per_trade, "leverage_cap": args.leverage_cap},
        "overall": calc(trades),
        "by_direction": {k: calc([t for t in trades if t.get("direction") == k]) for k in ("LONG", "SHORT")},
        "by_mode": {k: calc([t for t in trades if t.get("mode") == k]) for k in ("BREAKOUT", "CONTINUATION", "NORMAL")},
        "by_symbol": grouped(trades, "symbol"),
        "time_split": {name: calc(xs) for name, xs in split_periods(trades).items()},
        "brusdt_case_study": calc([t for t in trades if t.get("symbol") == "BRUSDT"]),
        "brusdt_trades": [t for t in trades if t.get("symbol") == "BRUSDT"],
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
