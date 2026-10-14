"""Research-only diagnostics for AURELIS recurring-pattern walk-forward results.

No live signal/order integration. Filters are comparisons, not auto-promoted strategy rules.
"""
from __future__ import annotations

from collections import defaultdict
import json
import os
from typing import Mapping

import pandas as pd

from .binance_history import load_symbols
from .cross_asset_patterns import _outcome_r, _summarize, pattern_key
from .historical_features import add_features
from .pattern_walk_forward import FOLDS

COST_GRID_R = (0.04, 0.08, 0.12, 0.16)


def _stats(rows: list[dict], cost_r: float = 0.0) -> dict:
    if not rows:
        return {"samples": 0, "symbols": 0, "win_rate_pct": 0.0, "gross_avg_r": 0.0,
                "net_avg_r": 0.0, "median_net_r": 0.0}
    gross = [float(row["gross_r"]) for row in rows]
    net = [value - cost_r for value in gross]
    return {
        "samples": len(rows),
        "symbols": len({row["symbol"] for row in rows}),
        "win_rate_pct": round(sum(value > 0 for value in net) / len(net) * 100, 2),
        "gross_avg_r": round(sum(gross) / len(gross), 4),
        "net_avg_r": round(sum(net) / len(net), 4),
        "median_net_r": round(float(pd.Series(net).median()), 4),
    }


def _dedupe(rows: list[dict], horizon: int) -> list[dict]:
    selected = []
    last: dict[tuple[str, int], int] = {}
    for row in sorted(rows, key=lambda item: (item["symbol"], item["fold"], item["index"])):
        key = (row["symbol"], row["fold"])
        if row["index"] - last.get(key, -horizon) < horizon:
            continue
        selected.append(row)
        last[key] = row["index"]
    return selected


def analyze_losses(
    frames: Mapping[str, pd.DataFrame],
    horizon: int = 6,
    selection_cost_r: float = 0.08,
    min_train_samples: int = 20,
    min_train_win_rate_pct: float = 50.0,
) -> dict:
    """Compare predeclared filters only on chronological out-of-sample observations."""
    if horizon < 1:
        raise ValueError("horizon must be at least 1")
    if selection_cost_r < 0:
        raise ValueError("selection_cost_r cannot be negative")

    prepared, errors = {}, {}
    for raw_symbol, raw in frames.items():
        symbol = str(raw_symbol).upper()
        try:
            frame = add_features(raw).reset_index(drop=True)
            required = {"open", "high", "low", "close", "volume", "taker_buy_base", "trades",
                        "atr_pct", "trend_gap_pct", "ret_3", "rsi14"}
            missing = sorted(required - set(frame.columns))
            if missing:
                raise ValueError("missing columns: " + ", ".join(missing))
            if len(frame) < 200:
                raise ValueError("insufficient candles")
            prepared[symbol] = frame
        except Exception as exc:
            errors[symbol] = f"{type(exc).__name__}: {exc}"

    test_rows: list[dict] = []
    fold_summary = []
    for fold_no, (train_fraction, test_fraction) in enumerate(FOLDS, 1):
        train: dict[tuple[str, ...], dict[str, list[dict]]] = defaultdict(
            lambda: {"LONG": [], "SHORT": []}
        )
        candidates = []
        for symbol, frame in prepared.items():
            n = len(frame)
            train_end, test_end = int(n * train_fraction), int(n * test_fraction)
            for i in range(60, n - horizon):
                row = frame.iloc[i]
                key = pattern_key(row)
                if key is None:
                    continue
                for direction in ("LONG", "SHORT"):
                    outcome = _outcome_r(frame, i, direction, horizon)
                    if outcome is None:
                        continue
                    item = {"symbol": symbol, "index": i, "fold": fold_no,
                            "pattern": key, "direction": direction, "gross_r": float(outcome),
                            "trend_gap_pct": float(row["trend_gap_pct"]),
                            "ret_3": float(row["ret_3"]) if pd.notna(row["ret_3"]) else 0.0,
                            "atr_pct": float(row["atr_pct"]) if pd.notna(row["atr_pct"]) else 999.0,
                            "rsi14": float(row["rsi14"]) if pd.notna(row["rsi14"]) else 50.0}
                    if i + horizon < train_end:
                        train[key][direction].append(item)
                    elif train_end <= i and i + horizon < test_end:
                        candidates.append(item)

        chosen = {}
        for key, directions in train.items():
            passing = []
            for direction, observations in directions.items():
                observations = _dedupe([{**item, "fold": 0} for item in observations], horizon)
                stats = _stats(observations, selection_cost_r)
                if (stats["samples"] >= min_train_samples and stats["net_avg_r"] > 0
                        and stats["win_rate_pct"] >= min_train_win_rate_pct):
                    passing.append((stats["net_avg_r"], stats["samples"], direction, stats))
            if passing:
                best = max(passing, key=lambda item: (item[0], item[1]))
                chosen[key] = {"direction": best[2], "training": best[3]}

        for item in candidates:
            selected = chosen.get(item["pattern"])
            if selected and selected["direction"] == item["direction"]:
                test_rows.append({**item, "training_avg_net_r": selected["training"]["net_avg_r"]})

        fold_rows = _dedupe([r for r in test_rows if r["fold"] == fold_no], horizon)
        fold_summary.append({"fold": fold_no, "selected_pattern_directions": len(chosen),
                             "out_of_sample_at_selection_cost": _stats(fold_rows, selection_cost_r)})

    rows = _dedupe(test_rows, horizon)
    filters = {
        "baseline": lambda r: True,
        "trend_aligned": lambda r: (r["direction"] == "LONG" and r["trend_gap_pct"] > 0)
                                   or (r["direction"] == "SHORT" and r["trend_gap_pct"] < 0),
        "moderate_volatility_atr_pct_le_5": lambda r: r["atr_pct"] <= 5.0,
        "momentum_confirmed": lambda r: (r["direction"] == "LONG" and r["ret_3"] > 0)
                                        or (r["direction"] == "SHORT" and r["ret_3"] < 0),
        "trend_and_moderate_volatility": lambda r: r["atr_pct"] <= 5.0 and (
            (r["direction"] == "LONG" and r["trend_gap_pct"] > 0)
            or (r["direction"] == "SHORT" and r["trend_gap_pct"] < 0)),
        "trend_and_momentum": lambda r: (
            (r["direction"] == "LONG" and r["trend_gap_pct"] > 0 and r["ret_3"] > 0)
            or (r["direction"] == "SHORT" and r["trend_gap_pct"] < 0 and r["ret_3"] < 0)),
    }
    comparisons = {}
    for name, predicate in filters.items():
        subset = [r for r in rows if predicate(r)]
        comparisons[name] = {
            "at_selection_cost": _stats(subset, selection_cost_r),
            "cost_sensitivity": {str(cost): _stats(subset, cost) for cost in COST_GRID_R},
            "by_fold": {str(fold): _stats([r for r in subset if r["fold"] == fold], selection_cost_r)
                        for fold in range(1, len(FOLDS) + 1)},
            "by_symbol": {symbol: _stats([r for r in subset if r["symbol"] == symbol], selection_cost_r)
                          for symbol in sorted(prepared)},
        }

    def aggregate(key_fn):
        buckets = defaultdict(list)
        for row in rows:
            buckets[key_fn(row)].append(row)
        return [{"group": list(key) if isinstance(key, tuple) else key,
                 **_stats(items, selection_cost_r)}
                for key, items in buckets.items()]

    pattern_groups = aggregate(lambda r: (r["pattern"], r["direction"]))
    pattern_groups.sort(key=lambda x: (x["net_avg_r"], -x["samples"]))
    direction = aggregate(lambda r: r["direction"])
    regimes = aggregate(lambda r: "high_volatility" if r["atr_pct"] > 5 else "normal_or_low_volatility")
    return {
        "research_only": True,
        "signal_engine_modified": False,
        "real_money_enabled": False,
        "purpose": "loss attribution, predeclared filter comparison, and cost sensitivity; no filter is auto-promoted",
        "timeframe": "4h",
        "forward_horizon_bars": horizon,
        "selection_cost_r": selection_cost_r,
        "cost_sensitivity_grid_r": list(COST_GRID_R),
        "symbols_loaded": len(prepared),
        "symbol_errors": errors,
        "folds": fold_summary,
        "baseline": comparisons["baseline"],
        "filter_comparisons": comparisons,
        "by_direction": direction,
        "by_volatility_regime": regimes,
        "worst_pattern_directions": pattern_groups[:20],
        "best_pattern_directions": list(reversed(pattern_groups[-20:])),
        "observations": len(rows),
        "limitations": [
            "The cost grid is an R-based stress test, not measured exchange fees, slippage, spread, or funding.",
            "Filters are exploratory and are not selected or promoted based on the test results.",
            "Repeated and correlated crypto observations are not statistically independent.",
            "No live signal generation, order placement, or real-money settings are changed.",
        ],
    }


if __name__ == "__main__":
    symbols = [s.strip().upper() for s in os.getenv(
        "AURELIS_PATTERN_SYMBOLS",
        "BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT,XRPUSDT,ADAUSDT,DOGEUSDT,LINKUSDT,AVAXUSDT,DOTUSDT"
    ).split(",") if s.strip()]
    days = int(os.getenv("AURELIS_PATTERN_DAYS", "1095"))
    cost = float(os.getenv("AURELIS_PATTERN_COST_R", "0.08"))
    frames = load_symbols(symbols, interval="4h", days=days)
    print(json.dumps(analyze_losses(frames, selection_cost_r=cost), indent=2, default=str))
