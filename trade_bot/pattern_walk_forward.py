"""Leakage-aware walk-forward validation for AURELIS pattern research.

This module is research-only. Pattern direction is selected using past data only,
then evaluated in the next chronological block. Outcomes are cost-adjusted by a
configurable conservative cost budget expressed in R. It never changes live signals.
"""
from __future__ import annotations

from collections import defaultdict
import os
from typing import Mapping

import pandas as pd

from .cross_asset_patterns import _outcome_r, _summarize, pattern_key
from .historical_features import add_features

DEFAULT_COST_R = 0.08
FOLDS = ((0.50, 0.65), (0.65, 0.80), (0.80, 0.95))


def _net_r(value: float, cost_r: float) -> float:
    """Subtract estimated round-trip costs without allowing cost-adjusted wins to inflate."""
    return float(value) - cost_r


def _deoverlap(rows: list[dict], horizon: int) -> list[dict]:
    """Keep at most one observation per symbol per outcome horizon."""
    selected = []
    last_index: dict[tuple[str, int], int] = {}
    for item in sorted(rows, key=lambda row: (row["symbol"], row["index"])):
        key = (item["symbol"], item["fold"])
        previous = last_index.get(key, -horizon)
        if item["index"] - previous < horizon:
            continue
        selected.append(item)
        last_index[key] = item["index"]
    return selected


def _stats(rows: list[dict]) -> dict:
    return _summarize([{"symbol": row["symbol"], "r": row["r"]} for row in rows])


def walk_forward(
    frames: Mapping[str, pd.DataFrame],
    horizon: int = 6,
    cost_r: float = DEFAULT_COST_R,
    min_train_samples: int = 20,
    min_train_win_rate_pct: float = 50.0,
) -> dict:
    """Select pattern directions on prior history, test only on the next block."""
    if horizon < 1:
        raise ValueError("horizon must be at least 1")
    if cost_r < 0:
        raise ValueError("cost_r cannot be negative")
    if min_train_samples < 1:
        raise ValueError("min_train_samples must be at least 1")

    prepared: dict[str, pd.DataFrame] = {}
    errors = {}
    date_ranges = {}
    for raw_symbol, raw_frame in frames.items():
        symbol = str(raw_symbol).upper()
        try:
            frame = add_features(raw_frame).reset_index(drop=True)
            required = {"open", "high", "low", "close", "volume", "taker_buy_base", "trades"}
            missing = sorted(required - set(frame.columns))
            if missing:
                raise ValueError("missing columns: " + ", ".join(missing))
            if len(frame) < max(160, horizon * 4 + 60):
                raise ValueError("insufficient candles for walk-forward folds")
            prepared[symbol] = frame
            date_ranges[symbol] = {
                "start": str(frame["open_time"].iloc[0]) if "open_time" in frame else None,
                "end": str(frame["open_time"].iloc[-1]) if "open_time" in frame else None,
                "candles": len(frame),
            }
        except Exception as exc:
            errors[symbol] = f"{type(exc).__name__}: {exc}"

    fold_results = []
    all_test = []
    for fold_no, (train_end_fraction, test_end_fraction) in enumerate(FOLDS, start=1):
        training: dict[tuple[str, ...], dict[str, list[dict]]] = defaultdict(
            lambda: {"LONG": [], "SHORT": []}
        )
        test_rows = []
        for symbol, frame in prepared.items():
            n = len(frame)
            train_end = int(n * train_end_fraction)
            test_end = int(n * test_end_fraction)
            for i in range(60, n - horizon):
                key = pattern_key(frame.iloc[i])
                if key is None:
                    continue
                if i + horizon < train_end:
                    for direction in ("LONG", "SHORT"):
                        value = _outcome_r(frame, i, direction, horizon)
                        if value is not None:
                            training[key][direction].append({
                                "symbol": symbol, "index": i,
                                "r": _net_r(value, cost_r),
                            })
                elif train_end <= i and i + horizon < test_end:
                    for direction in ("LONG", "SHORT"):
                        value = _outcome_r(frame, i, direction, horizon)
                        if value is not None:
                            test_rows.append({
                                "symbol": symbol, "index": i, "fold": fold_no,
                                "pattern": key, "direction": direction,
                                "r": _net_r(value, cost_r),
                            })

        selected_directions = {}
        for key, directions in training.items():
            candidates = []
            for direction, rows in directions.items():
                rows = _deoverlap([{**row, "fold": 0} for row in rows], horizon)
                stats = _stats(rows)
                if (
                    stats["samples"] >= min_train_samples
                    and stats["avg_r"] > 0
                    and stats["win_rate_pct"] >= min_train_win_rate_pct
                ):
                    candidates.append((stats["avg_r"], stats["samples"], direction, stats))
            if candidates:
                best = max(candidates, key=lambda candidate: (candidate[0], candidate[1]))
                selected_directions[key] = {
                    "direction": best[2], "train_stats": best[3],
                }

        qualifying = [
            row for row in test_rows
            if row["pattern"] in selected_directions
            and row["direction"] == selected_directions[row["pattern"]]["direction"]
        ]
        qualifying = _deoverlap(qualifying, horizon)
        all_test.extend(qualifying)
        stats = _stats(qualifying)
        fold_results.append({
            "fold": fold_no,
            "training_fraction_end": train_end_fraction,
            "test_fraction_end": test_end_fraction,
            "selected_pattern_directions": len(selected_directions),
            "out_of_sample": stats,
            "cost_adjusted": True,
        })

    overall = _stats(all_test)
    per_symbol = {}
    for symbol in sorted(prepared):
        rows = [row for row in all_test if row["symbol"] == symbol]
        per_symbol[symbol] = _stats(rows)

    return {
        "research_only": True,
        "signal_engine_modified": False,
        "real_money_enabled": False,
        "method": "expanding-window walk-forward; train-only direction selection; chronological next-block test",
        "timeframe": "4h",
        "forward_horizon_bars": horizon,
        "forward_horizon_hours": horizon * 4,
        "estimated_cost_r_per_trade": round(cost_r, 4),
        "minimum_training_samples_per_pattern_direction": min_train_samples,
        "minimum_training_win_rate_pct": min_train_win_rate_pct,
        "symbols_loaded": len(prepared),
        "symbols": date_ranges,
        "symbol_errors": errors,
        "folds": fold_results,
        "overall_out_of_sample": overall,
        "out_of_sample_by_symbol": per_symbol,
        "observations": len(all_test),
        "limitations": [
            "Cost budget is a configurable R-based stress assumption, not a measured fee/slippage/funding model.",
            "Cross-asset returns can remain correlated; symbol count is not independent evidence.",
            "Walk-forward folds reduce selection leakage but do not guarantee future performance.",
            "Research output is not connected to live signal generation or order placement.",
        ],
    }


if __name__ == "__main__":
    import json
    from .binance_history import load_symbols

    symbols = [
        item.strip().upper()
        for item in os.getenv(
            "AURELIS_PATTERN_SYMBOLS",
            "BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT,XRPUSDT,ADAUSDT,DOGEUSDT,LINKUSDT,AVAXUSDT,DOTUSDT",
        ).split(",")
        if item.strip()
    ]
    days = int(os.getenv("AURELIS_PATTERN_DAYS", "1095"))
    cost_r = float(os.getenv("AURELIS_PATTERN_COST_R", str(DEFAULT_COST_R)))
    data = load_symbols(symbols, interval="4h", days=days)
    print(json.dumps(walk_forward(data, cost_r=cost_r), indent=2, default=str))
