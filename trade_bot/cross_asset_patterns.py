""""Cross-asset recurring-pattern research for AURELIS.

Research only: no signal scoring, order placement, or live-trading integration.
Patterns use scale-independent feature buckets, fixed-horizon outcomes, and a
chronological train/validation split. When an OHLC candle touches stop and
target together, the stop is assumed to hit first.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Mapping

import pandas as pd

from .historical_features import add_features

FEATURES = (
    "ret_1", "ret_3", "ret_6", "rsi14", "atr_pct",
    "volume_ratio", "taker_buy_ratio", "trade_intensity",
    "range_pct", "breakout_20", "breakdown_20", "trend_gap_pct",
)


def pattern_key(row) -> tuple[str, ...] | None:
    """Create a compact, cross-asset key from normalized market behaviour."""
    try:
        values = {name: float(row[name]) for name in FEATURES}
    except (KeyError, TypeError, ValueError):
        return None
    if any(pd.isna(v) for v in values.values()):
        return None

    def bucket(value: float, edges: tuple[float, ...], labels: tuple[str, ...]) -> str:
        for edge, label in zip(edges, labels):
            if value < edge:
                return label
        return labels[-1] if len(labels) == len(edges) else f"ge_{edges[-1]}"

    return (
        bucket(values["ret_3"], (-0.04, -0.015, 0.015, 0.04), ("hard_down", "down", "flat", "up", "hard_up")),
        bucket(values["ret_6"], (-0.07, -0.025, 0.025, 0.07), ("hard_down", "down", "flat", "up", "hard_up")),
        bucket(values["rsi14"], (30, 40, 50, 60, 70), ("oversold", "weak", "soft_bear", "neutral", "soft_bull", "overbought")),
        bucket(values["atr_pct"], (1, 2.5, 5), ("low_vol", "normal_vol", "high_vol", "extreme_vol")),
        bucket(values["volume_ratio"], (0.7, 1.2, 2), ("quiet", "normal", "elevated", "spike")),
        bucket(values["trend_gap_pct"], (-2, -0.5, 0.5, 2), ("strong_bear", "bear", "flat", "bull", "strong_bull")),
        bucket(values["breakout_20"], (-0.03, -0.005, 0.005), ("below_range", "range_low", "range", "breakout")),
        bucket(values["breakdown_20"], (-0.03, -0.005, 0.005), ("breakdown", "range_low", "range", "above_range")),
    )


def _outcome_r(frame: pd.DataFrame, index: int, direction: str, horizon: int) -> float | None:
    """Return conservative stop/target/time-exit outcome in R for a prior setup."""
    row = frame.iloc[index]
    entry = float(row["close"])
    atr = float(row["atr14"])
    if not entry > 0 or not atr > 0 or pd.isna(atr):
        return None
    risk = 1.5 * atr
    stop = entry - risk if direction == "LONG" else entry + risk
    target = entry + 2 * atr if direction == "LONG" else entry - 2 * atr
    future = frame.iloc[index + 1:index + 1 + horizon]
    if len(future) < horizon:
        return None
    for candle in future.itertuples(index=False):
        low, high = float(getattr(candle, "low")), float(getattr(candle, "high"))
        hit_stop = low <= stop if direction == "LONG" else high >= stop
        hit_target = high >= target if direction == "LONG" else low <= target
        if hit_stop and hit_target:
            return -1.0
        if hit_stop:
            return -1.0
        if hit_target:
            return 2.0 / 1.5
    exit_price = float(future.iloc[-1]["close"])
    pnl = exit_price - entry if direction == "LONG" else entry - exit_price
    return max(-1.0, min(2.0 / 1.5, pnl / risk))


def _summarize(rows: list[dict]) -> dict:
    if not rows:
        return {"samples": 0, "symbols": 0, "win_rate_pct": 0.0, "avg_r": 0.0}
    outcomes = [float(item["r"]) for item in rows]
    return {
        "samples": len(outcomes),
        "symbols": len({item["symbol"] for item in rows}),
        "win_rate_pct": round(sum(value > 0 for value in outcomes) / len(outcomes) * 100, 2),
        "avg_r": round(sum(outcomes) / len(outcomes), 4),
        "median_r": round(float(pd.Series(outcomes).median()), 4),
    }


def analyze(
    frames: Mapping[str, pd.DataFrame],
    horizon: int = 6,
    train_fraction: float = 0.7,
    min_train_samples: int = 12,
    min_validation_samples: int = 5,
) -> dict:
    """Evaluate recurring pattern keys with a chronological holdout.

    Training outcomes stay entirely inside the training segment, and validation
    outcomes stay entirely inside validation. The default research workflow now
    supplies three years of history so regimes can be compared over longer
    market cycles; the holdout remains strictly chronological.
    """
    if not 0.5 <= train_fraction <= 0.85:
        raise ValueError("train_fraction must be between 0.50 and 0.85")
    if horizon < 1:
        raise ValueError("horizon must be at least 1")

    train: dict[tuple[str, ...], dict[str, list[dict]]] = defaultdict(lambda: {"LONG": [], "SHORT": []})
    validation: dict[tuple[str, ...], dict[str, list[dict]]] = defaultdict(lambda: {"LONG": [], "SHORT": []})
    latest: dict[str, dict] = {}
    symbol_errors = {}
    date_ranges = {}

    for raw_symbol, raw_frame in frames.items():
        symbol = str(raw_symbol).upper()
        try:
            frame = add_features(raw_frame).reset_index(drop=True)
            required = {"open", "high", "low", "close", "volume", "taker_buy_base", "trades"}
            missing = sorted(required - set(frame.columns))
            if missing:
                raise ValueError("missing columns: " + ", ".join(missing))
            if len(frame) < max(100, horizon * 2 + 30):
                raise ValueError("insufficient candles")
            if "open_time" in frame.columns and not frame["open_time"].empty:
                date_ranges[symbol] = {
                    "start": str(frame["open_time"].iloc[0]),
                    "end": str(frame["open_time"].iloc[-1]),
                    "candles": len(frame),
                }
            else:
                date_ranges[symbol] = {"start": None, "end": None, "candles": len(frame)}
            split = int(len(frame) * train_fraction)
            latest_key = pattern_key(frame.iloc[-1])
            latest[symbol] = {"pattern": list(latest_key) if latest_key else None, "rows": len(frame)}
            for i in range(60, len(frame) - horizon):
                key = pattern_key(frame.iloc[i])
                if key is None:
                    continue
                direction_rows = {}
                for direction in ("LONG", "SHORT"):
                    r = _outcome_r(frame, i, direction, horizon)
                    if r is not None:
                        direction_rows[direction] = {"symbol": symbol, "r": r}
                if i + horizon < split:
                    bucket_map = train
                elif i >= split:
                    bucket_map = validation
                else:
                    continue
                for direction, observation in direction_rows.items():
                    bucket_map[key][direction].append(observation)
        except Exception as exc:
            symbol_errors[symbol] = f"{type(exc).__name__}: {exc}"

    results = []
    for key, train_directions in train.items():
        valid_directions = validation.get(key, {"LONG": [], "SHORT": []})
        for direction in ("LONG", "SHORT"):
            train_stats = _summarize(train_directions[direction])
            valid_stats = _summarize(valid_directions[direction])
            if train_stats["samples"] < min_train_samples or valid_stats["samples"] < min_validation_samples:
                continue
            results.append({
                "pattern": list(key),
                "direction": direction,
                "train": train_stats,
                "validation": valid_stats,
                "validation_pass": valid_stats["avg_r"] > 0 and valid_stats["win_rate_pct"] >= 50,
                "latest_symbols_matching": sorted(
                    symbol for symbol, details in latest.items() if details["pattern"] == key
                ),
            })

    results.sort(key=lambda item: (
        item["validation_pass"], item["validation"]["avg_r"],
        item["validation"]["samples"], item["train"]["samples"]
    ), reverse=True)
    return {
        "research_only": True,
        "signal_engine_modified": False,
        "real_money_enabled": False,
        "history_days_requested": int(__import__("os").getenv("AURELIS_PATTERN_DAYS", "1095")),
        "timeframe": "4h",
        "forward_horizon_bars": horizon,
        "forward_horizon_hours": horizon * 4,
        "train_fraction": train_fraction,
        "minimum_train_samples": min_train_samples,
        "minimum_validation_samples": min_validation_samples,
        "symbols_loaded": len(frames) - len(symbol_errors),
        "symbols": latest,
        "date_ranges": date_ranges,
        "symbol_errors": symbol_errors,
        "patterns_evaluated": len(results),
        "validated_patterns": sum(bool(item["validation_pass"]) for item in results),
        "patterns": results[:100],
        "limitations": [
            "Historical patterns are not forecasts or guarantees.",
            "Symbols can be correlated; symbol counts do not imply independent evidence.",
            "Fees, slippage, funding, and executable entry timing are not modeled.",
            "One chronological holdout can still be regime-dependent; validate across multiple market cycles before signal integration.",
        ],
    }


if __name__ == "__main__":
    import json
    import os
    from .binance_history import load_symbols

    symbols = [s.strip().upper() for s in os.getenv(
        "AURELIS_PATTERN_SYMBOLS",
        "BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT,XRPUSDT,ADAUSDT,DOGEUSDT,LINKUSDT,AVAXUSDT,DOTUSDT"
    ).split(",") if s.strip()]
    days = int(os.getenv("AURELIS_PATTERN_DAYS", "1095"))
    data = load_symbols(symbols, interval="4h", days=days)
    report = analyze(data)
    print(json.dumps(report, indent=2, default=str))
