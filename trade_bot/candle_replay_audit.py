"""Conservative 5-minute Binance candle replay for recorded AURELIS paper setups.

This is a research audit, not a live signal engine or a full historical signal
re-generation. It replays recorded entries/stops/targets against later candles,
starts at the first candle after entry time, charges configurable round-trip fees,
and treats same-candle stop/target collisions as stop losses.
"""
from __future__ import annotations

import json
import os
import time
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Callable, Iterable, Mapping

import httpx

BASE_URL = os.getenv("CRYPTO_API_URL", "https://data-api.binance.vision").rstrip("/")
LEDGER_PATH = Path(os.getenv("AURELIS_LEDGER_PATH", "data/aurelis_paper_ledger.json"))
FEE_BPS_PER_SIDE = float(os.getenv("PAPER_FEE_BPS_PER_SIDE", "10"))
SLIPPAGE_BPS_PER_SIDE = float(os.getenv("PAPER_SLIPPAGE_BPS_PER_SIDE", "5"))
ROUND_TRIP_COST_PCT = 2 * (FEE_BPS_PER_SIDE + SLIPPAGE_BPS_PER_SIDE) / 100.0
BAR_MS = 5 * 60 * 1000
HORIZON_HOURS = 24
SCORED = {"WIN_TP1", "WIN_TP2", "LOSS_SL", "LOSS_AMBIGUOUS_STOP", "EXPIRED"}
CANDIDATE_NAME = "score_ge_68_not_bearish"


def _dt(value):
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return result if result.tzinfo else result.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _num(value):
    try:
        value = float(value)
        return value if value == value and abs(value) != float("inf") else None
    except (TypeError, ValueError):
        return None


def load_ledger(path=LEDGER_PATH):
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    def rows(section):
        block = data.get(section, {})
        values = block.get("rows", [])
        if values and isinstance(values[0], list):
            return [dict(zip(block.get("columns", []), row)) for row in values]
        return [dict(row) for row in values]
    setups = {str(row.get("id")): row for row in rows("setups")}
    trades = rows("paper_trades")
    joined = []
    for trade in trades:
        setup = setups.get(str(trade.get("signal_id")), {})
        joined.append({**setup, **trade, "score": setup.get("score", trade.get("final_score")),
                       "market_regime": setup.get("market_regime", trade.get("market_regime"))})
    return joined


def fetch_window(symbol: str, day_start_ms: int, client: httpx.Client):
    """Fetch two UTC days, enough for a trade opened on the first day + 24h."""
    response = client.get(f"{BASE_URL}/api/v3/klines", params={
        "symbol": symbol, "interval": "5m", "startTime": day_start_ms,
        "endTime": day_start_ms + 2 * 24 * 60 * 60 * 1000 - 1, "limit": 600,
    })
    response.raise_for_status()
    candles = []
    for row in response.json():
        try:
            candles.append({
                "time_ms": int(row[0]), "open": float(row[1]), "high": float(row[2]),
                "low": float(row[3]), "close": float(row[4]),
            })
        except (TypeError, ValueError, IndexError):
            continue
    return candles


def _hit(direction, candle, stop, tp1, tp2):
    if direction == "LONG":
        stop_hit = stop is not None and candle["low"] <= stop
        tp1_hit = tp1 is not None and candle["high"] >= tp1
        tp2_hit = tp2 is not None and candle["high"] >= tp2
    elif direction == "SHORT":
        stop_hit = stop is not None and candle["high"] >= stop
        tp1_hit = tp1 is not None and candle["low"] <= tp1
        tp2_hit = tp2 is not None and candle["low"] <= tp2
    else:
        return None
    if stop_hit and (tp1_hit or tp2_hit):
        return ("LOSS_AMBIGUOUS_STOP", stop)
    if stop_hit:
        return ("LOSS_SL", stop)
    # If both targets are touched in one candle, intrabar order is unknown.
    # Credit only TP1 rather than assuming the farther target was reached first.
    if tp1_hit and tp2_hit:
        return ("WIN_TP1", tp1)
    if tp2_hit:
        return ("WIN_TP2", tp2)
    if tp1_hit:
        return ("WIN_TP1", tp1)
    return None


def replay_trade(row: Mapping, candles: Iterable[Mapping]):
    opened = _dt(row.get("opened_at") or row.get("created_at"))
    entry = _num(row.get("entry"))
    stop = _num(row.get("stop_loss"))
    tp1 = _num(row.get("tp1"))
    tp2 = _num(row.get("tp2"))
    direction = str(row.get("direction") or "").upper()
    if not opened or not entry or not stop or not tp1:
        return {"status": "SKIPPED", "reason": "missing_entry_time_or_risk_or_target"}
    if direction not in {"LONG", "SHORT"}:
        return {"status": "SKIPPED", "reason": "invalid_direction"}
    if (direction == "LONG" and not (stop < entry < tp1)) or (direction == "SHORT" and not (tp1 < entry < stop)):
        return {"status": "SKIPPED", "reason": "inconsistent_entry_stop_target"}
    opened_ms = int(opened.timestamp() * 1000)
    start_ms = (opened_ms // BAR_MS + 1) * BAR_MS  # never use the entry candle
    end_ms = opened_ms + HORIZON_HOURS * 60 * 60 * 1000
    eligible = sorted((c for c in candles if start_ms <= int(c["time_ms"]) < end_ms),
                      key=lambda c: int(c["time_ms"]))
    expected_bars = max(1, (end_ms - start_ms + BAR_MS - 1) // BAR_MS)
    minimum_bars = int(expected_bars * 0.95 + 0.999999)
    gaps = [int(eligible[i]["time_ms"]) - int(eligible[i - 1]["time_ms"])
            for i in range(1, len(eligible))]
    coverage_ok = bool(eligible) and len(eligible) >= minimum_bars
    if coverage_ok:
        coverage_ok = int(eligible[-1]["time_ms"]) + BAR_MS >= end_ms
    if not coverage_ok:
        return {"status": "SKIPPED", "reason": "insufficient_candle_coverage"}
    if any(gap > 2 * BAR_MS for gap in gaps):
        return {"status": "SKIPPED", "reason": "candle_data_gaps"}
    for candle in eligible:
        hit = _hit(direction, candle, stop, tp1, tp2)
        if hit:
            outcome, exit_price = hit
            break
    else:
        outcome, exit_price = "EXPIRED", eligible[-1]["close"]
    gross_pct = ((exit_price - entry) / entry * 100 if direction == "LONG"
                 else (entry - exit_price) / entry * 100)
    return {
        "status": "SCORED", "outcome": outcome, "exit_price": exit_price,
        "gross_pct": gross_pct, "net_pct": gross_pct - ROUND_TRIP_COST_PCT,
        "opened_at": opened.isoformat(), "symbol": row.get("symbol"),
        "score": _num(row.get("score")), "market_regime": str(row.get("market_regime") or "UNKNOWN").upper(),
    }


def metrics(rows):
    scored = [r for r in rows if r.get("status") == "SCORED" and r.get("outcome") in SCORED]
    if not scored:
        return {"n": 0, "win_rate_pct": None, "expectancy_net_pct": None,
                "profit_factor": None, "max_additive_drawdown_pct_points": None}
    returns = [float(r["net_pct"]) for r in sorted(scored, key=lambda r: r["opened_at"])]
    wins = sum(r["outcome"].startswith("WIN_") for r in scored)
    positive = sum(v for v in returns if v > 0)
    negative = -sum(v for v in returns if v < 0)
    equity = peak = max_dd = 0.0
    for value in returns:
        equity += value
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return {"n": len(scored), "win_rate_pct": round(100 * wins / len(scored), 2),
            "expectancy_net_pct": round(sum(returns) / len(returns), 4),
            "profit_factor": round(positive / negative, 4) if negative else None,
            "max_additive_drawdown_pct_points": round(max_dd, 4)}


def evaluate(rows, replayed):
    """Select among fixed filters on the first 70%; evaluate once on final 30%."""
    by_id = {str(row.get("signal_id") or row.get("id")): row for row in replayed}
    aligned = []
    for row in rows:
        key = str(row.get("signal_id") or row.get("id"))
        result = by_id.get(key)
        if result and result.get("status") == "SCORED":
            aligned.append({**row, **result})
    aligned.sort(key=lambda r: str(r.get("opened_at") or ""))
    split = max(1, int(len(aligned) * 0.7))
    train, holdout = aligned[:split], aligned[split:]
    def candidate(r):
        score = _num(r.get("score"))
        return score is not None and score >= 68 and r.get("market_regime") != "BEARISH"
    train_base, train_cand = metrics(train), metrics([r for r in train if candidate(r)])
    hold_base, hold_cand = metrics(holdout), metrics([r for r in holdout if candidate(r)])
    enough = train_cand["n"] >= 30 and hold_cand["n"] >= 30
    passed = bool(enough and train_cand["expectancy_net_pct"] > train_base["expectancy_net_pct"]
                  and train_cand["win_rate_pct"] >= train_base["win_rate_pct"]
                  and train_cand["max_additive_drawdown_pct_points"] <= train_base["max_additive_drawdown_pct_points"]
                  and hold_cand["expectancy_net_pct"] > hold_base["expectancy_net_pct"]
                  and hold_cand["win_rate_pct"] >= hold_base["win_rate_pct"]
                  and hold_cand["max_additive_drawdown_pct_points"] < hold_base["max_additive_drawdown_pct_points"])
    return {"replayed_scored": len(aligned), "training_count": len(train), "holdout_count": len(holdout),
            "candidate": CANDIDATE_NAME, "training_baseline": train_base, "training_candidate": train_cand,
            "holdout_baseline": hold_base, "holdout_candidate": hold_cand,
            "status": "RESEARCH_PASS" if passed else ("INSUFFICIENT_SAMPLE" if not enough else "NOT_SUPPORTED"),
            "live_settings_changed": False, "real_money_enabled": False,
            "drawdown_note": "Additive trade-return percentage points, not account-equity drawdown."}


def run(path=LEDGER_PATH, client=None):
    rows = load_ledger(path)
    if client is None:
        client = httpx.Client(timeout=20)
        own_client = True
    else:
        own_client = False
    cache = {}
    results = []
    try:
        for index, row in enumerate(rows, 1):
            opened = _dt(row.get("opened_at") or row.get("created_at"))
            if not opened or str(row.get("status", "CLOSED")).upper() != "CLOSED":
                continue
            symbol = str(row.get("symbol") or "").upper()
            if not symbol:
                results.append({"status": "SKIPPED", "reason": "missing_symbol"})
                continue
            opened_ms = int(opened.timestamp() * 1000)
            day_start_ms = (opened_ms // (24 * 60 * 60 * 1000)) * 24 * 60 * 60 * 1000
            key = (symbol, day_start_ms)
            try:
                if key not in cache:
                    cache[key] = fetch_window(symbol, day_start_ms, client)
                    time.sleep(0.04)
                result = replay_trade(row, cache[key])
                result["signal_id"] = row.get("signal_id") or row.get("id")
                results.append(result)
            except (httpx.HTTPError, ValueError, RuntimeError) as exc:
                results.append({"status": "SKIPPED", "reason": f"market_data_unavailable:{type(exc).__name__}",
                                "signal_id": row.get("signal_id") or row.get("id"), "symbol": symbol})
            if index % 50 == 0:
                print(f"Progress: processed {index}/{len(rows)} ledger rows; cached windows={len(cache)}")
    finally:
        if own_client:
            client.close()
    scored = [r for r in results if r.get("status") == "SCORED"]
    skipped = [r for r in results if r.get("status") != "SCORED"]
    report = evaluate(rows, results)
    report.update({"total_closed_rows_considered": len(results), "scored": len(scored), "skipped": len(skipped),
                   "skip_reasons": dict((reason, sum(r.get("reason") == reason for r in skipped))
                                        for reason in sorted({r.get("reason", "unknown") for r in skipped})),
                   "all_trade_metrics": metrics(scored), "fee_bps_per_side": FEE_BPS_PER_SIDE,
                   "horizon_hours": HORIZON_HOURS})
    output = Path(os.getenv("AURELIS_CANDLE_REPLAY_OUT", "data/candle_replay_report.json"))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    run()
