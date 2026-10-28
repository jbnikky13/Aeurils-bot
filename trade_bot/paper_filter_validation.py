"""Chronological holdout validation for stricter paper-trade filters.

The latest chronological block is reserved for evaluation. Candidate selection
uses training data only. This research report never changes live signal settings.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterable, Mapping

FEE_BPS_PER_SIDE = float(os.getenv("PAPER_FEE_BPS_PER_SIDE", "10"))
ROUND_TRIP_FEE_PCT = 2 * FEE_BPS_PER_SIDE / 100.0
SCORED_OUTCOMES = {"WIN_TP1", "WIN_TP2", "WIN_RUNNER", "LOSS_SL"}


def load_ledger(path: str | Path = "data/aurelis_paper_ledger.json") -> list[dict]:
    """Load paper-trade rows from the repository's exported ledger."""
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    trades = payload.get("paper_trades", {})
    rows = trades.get("rows", [])
    if rows and isinstance(rows[0], list):
        columns = trades.get("columns", [])
        return [dict(zip(columns, row)) for row in rows]
    return [dict(row) for row in rows]


def _number(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _closed(rows: Iterable[Mapping]) -> list[dict]:
    return [
        dict(row) for row in rows
        if str(row.get("status", "")).upper() == "CLOSED"
        and str(row.get("outcome", "")).upper() != "AMBIGUOUS"
    ]


def _net_pct(row: Mapping) -> float:
    return _number(row.get("pnl_pct")) - ROUND_TRIP_FEE_PCT


def metrics(rows: Iterable[Mapping]) -> dict:
    """Summarize a filtered set; drawdown is explicitly in trade-return points."""
    selected = [dict(row) for row in rows]
    closed = _closed(selected)
    scored = [row for row in closed if str(row.get("outcome", "")).upper() in SCORED_OUTCOMES]
    wins = [row for row in scored if str(row.get("outcome", "")).upper().startswith("WIN_")]
    net_scored = [_net_pct(row) for row in scored]
    equity = peak = drawdown = 0.0
    for row in sorted(closed, key=lambda item: str(item.get("closed_at") or "")):
        equity += _net_pct(row)
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)

    missing_risk = [row for row in closed if _number(row.get("initial_risk")) <= 0]
    recoverable = [
        row for row in missing_risk
        if _number(row.get("entry")) > 0
        and _number(row.get("stop_loss")) > 0
        and abs(_number(row.get("entry")) - _number(row.get("stop_loss"))) > 0
    ]
    return {
        "rows": len(selected),
        "closed": len(closed),
        "scored": len(scored),
        "wins": len(wins),
        "losses": sum(str(row.get("outcome", "")).upper() == "LOSS_SL" for row in scored),
        "win_rate_pct": round(100 * len(wins) / len(scored), 2) if scored else None,
        "expectancy_net_pct": round(sum(net_scored) / len(net_scored), 4) if net_scored else None,
        "total_net_pct_including_expiries": round(sum(_net_pct(row) for row in closed), 4),
        "max_drawdown_pct_points": round(drawdown, 4),
        "drawdown_basis": "additive cumulative per-trade net return percentage points, not account-equity drawdown",
        "stored_missing_risk": len(missing_risk),
        "risk_recoverable_from_entry_stop": len(recoverable),
        "risk_unrecoverable": len(missing_risk) - len(recoverable),
    }


def _candidate_filters():
    return [
        ("score_ge_65", lambda row: row.get("final_score") is not None and _number(row.get("final_score")) >= 65),
        ("score_ge_70", lambda row: row.get("final_score") is not None and _number(row.get("final_score")) >= 70),
        ("long_only", lambda row: str(row.get("direction", "")).upper() == "LONG"),
        ("bullish_only", lambda row: str(row.get("market_regime", "")).upper() == "BULLISH"),
        ("high_volatility_only", lambda row: str(row.get("market_regime", "")).upper() == "HIGH_VOLATILITY"),
        ("long_and_score_ge_65", lambda row: str(row.get("direction", "")).upper() == "LONG" and row.get("final_score") is not None and _number(row.get("final_score")) >= 65),
        ("score_ge_68_not_bearish", lambda row: row.get("final_score") is not None and _number(row.get("final_score")) >= 68 and str(row.get("market_regime", "")).upper() != "BEARISH"),
        ("bullish_or_high_volatility", lambda row: str(row.get("market_regime", "")).upper() in {"BULLISH", "HIGH_VOLATILITY"}),
    ]


def validate(
    rows: Iterable[Mapping],
    train_fraction: float = 0.70,
    min_train_scored: int = 30,
    min_test_scored: int = 30,
) -> dict:
    """Select one candidate using training only, then evaluate once on the holdout."""
    if not 0.5 <= train_fraction < 0.9:
        raise ValueError("train_fraction must be in [0.5, 0.9)")
    if min_train_scored < 1 or min_test_scored < 1:
        raise ValueError("minimum sample sizes must be positive")

    ordered = sorted((dict(row) for row in rows), key=lambda row: str(row.get("opened_at") or ""))
    if len(ordered) < 2:
        return {
            "status": "INSUFFICIENT_DATA",
            "research_only": True,
            "signal_engine_modified": False,
            "real_money_enabled": False,
            "rows": len(ordered),
        }

    split = max(1, min(len(ordered) - 1, int(len(ordered) * train_fraction)))
    train, test = ordered[:split], ordered[split:]
    baseline_train = metrics(train)
    baseline_test = metrics(test)
    train_candidates = []
    holdout_candidates = []
    for name, predicate in _candidate_filters():
        train_filtered = [row for row in train if predicate(row)]
        test_filtered = [row for row in test if predicate(row)]
        train_stats = metrics(train_filtered)
        test_stats = metrics(test_filtered)
        train_ok = (
            train_stats["scored"] >= min_train_scored
            and baseline_train["expectancy_net_pct"] is not None
            and train_stats["expectancy_net_pct"] is not None
            and train_stats["expectancy_net_pct"] > baseline_train["expectancy_net_pct"]
            and train_stats["win_rate_pct"] is not None
            and baseline_train["win_rate_pct"] is not None
            and train_stats["win_rate_pct"] > baseline_train["win_rate_pct"]
            and train_stats["max_drawdown_pct_points"] <= baseline_train["max_drawdown_pct_points"]
        )
        train_candidates.append({
            "filter": name,
            "train": train_stats,
            "eligible_on_training_only": train_ok,
        })
        holdout_candidates.append({
            "filter": name,
            "test": test_stats,
        })

    eligible = [item for item in train_candidates if item["eligible_on_training_only"]]
    selected = max(
        eligible,
        key=lambda item: (
            item["train"]["expectancy_net_pct"],
            item["train"]["win_rate_pct"],
            -item["train"]["max_drawdown_pct_points"],
        ),
    ) if eligible else None

    if selected is None:
        selected_test = None
        decision = "NO_FILTER_QUALIFIED_ON_TRAINING"
    else:
        chosen_name = selected["filter"]
        chosen_predicate = dict(_candidate_filters())[chosen_name]
        selected_test = metrics([row for row in test if chosen_predicate(row)])
        if selected_test["scored"] < min_test_scored:
            decision = "INSUFFICIENT_HOLDOUT_SAMPLE"
        elif (
            selected_test["expectancy_net_pct"] is not None
            and baseline_test["expectancy_net_pct"] is not None
            and selected_test["expectancy_net_pct"] > baseline_test["expectancy_net_pct"]
            and selected_test["win_rate_pct"] is not None
            and baseline_test["win_rate_pct"] is not None
            and selected_test["win_rate_pct"] >= baseline_test["win_rate_pct"]
            and selected_test["max_drawdown_pct_points"] < baseline_test["max_drawdown_pct_points"]
        ):
            decision = "OUT_OF_SAMPLE_IMPROVEMENT_SUPPORTED"
        else:
            decision = "OUT_OF_SAMPLE_IMPROVEMENT_NOT_SUPPORTED"

    return {
        "status": decision,
        "research_only": True,
        "signal_engine_modified": False,
        "real_money_enabled": False,
        "method": "chronological 70/30 holdout; filters selected using training metrics only",
        "fee_assumption_round_trip_pct": ROUND_TRIP_FEE_PCT,
        "minimum_training_scored_trades": min_train_scored,
        "minimum_holdout_scored_trades": min_test_scored,
        "total_rows": len(ordered),
        "train_rows": len(train),
        "test_rows": len(test),
        "train_end": train[-1].get("opened_at"),
        "test_start": test[0].get("opened_at"),
        "baseline_train": baseline_train,
        "baseline_test": baseline_test,
        "selected_filter": selected["filter"] if selected else None,
        "selected_filter_train": selected["train"] if selected else None,
        "selected_filter_test": selected_test,
        "training_candidates": train_candidates,
        "holdout_diagnostics_not_used_for_selection": holdout_candidates,
        "approval_rule": "At least the configured holdout sample, higher net expectancy, win rate no worse than baseline, and lower additive drawdown are all required.",
        "limitations": [
            "Paper-ledger trades are not a substitute for a full candle-by-candle historical replay.",
            "Trade-return percentage drawdown is not account-equity drawdown because position sizing and overlapping exposure are not represented.",
            "A small holdout or correlated trades cannot establish robust future profitability.",
        ],
    }


def main() -> None:
    path = os.getenv("AURELIS_PAPER_LEDGER", "data/aurelis_paper_ledger.json")
    report = validate(load_ledger(path))
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
