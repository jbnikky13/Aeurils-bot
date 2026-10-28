"""Research-only execution-cost and final-holdout robustness report.

The last 20% of each symbol's history is a one-time chronological holdout.
Costs are explicit proxies (not exchange-reported historical spread/slippage/funding).
Nothing in this module changes live signals or places orders.
"""
from __future__ import annotations

from collections import defaultdict
import json
import os
from typing import Mapping

import numpy as np
import pandas as pd

from .binance_history import load_symbols
from .cross_asset_patterns import _outcome_r, pattern_key
from .historical_features import add_features

DEFAULT_COST_SCENARIOS = {
    "low": {"fee_bps_per_side": 4.0, "slippage_bps_per_side": 2.0, "funding_bps_per_8h": 0.0},
    "base": {"fee_bps_per_side": 5.0, "slippage_bps_per_side": 3.0, "funding_bps_per_8h": 1.0},
    "stress": {"fee_bps_per_side": 6.0, "slippage_bps_per_side": 8.0, "funding_bps_per_8h": 2.0},
}
HOLDOUT_START_FRACTION = 0.80


def _outcome_and_bars(frame: pd.DataFrame, index: int, direction: str, horizon: int) -> tuple[float, int] | None:
    """Mirror the conservative stop/target outcome and return holding duration."""
    row = frame.iloc[index]
    entry, atr = float(row["close"]), float(row["atr14"])
    if not entry > 0 or not atr > 0 or pd.isna(atr):
        return None
    risk = 1.5 * atr
    stop = entry - risk if direction == "LONG" else entry + risk
    target = entry + 2 * atr if direction == "LONG" else entry - 2 * atr
    future = frame.iloc[index + 1:index + 1 + horizon]
    if len(future) < horizon:
        return None
    for held, candle in enumerate(future.itertuples(index=False), start=1):
        low, high = float(getattr(candle, "low")), float(getattr(candle, "high"))
        hit_stop = low <= stop if direction == "LONG" else high >= stop
        hit_target = high >= target if direction == "LONG" else low <= target
        if hit_stop and hit_target:
            return -1.0, held
        if hit_stop:
            return -1.0, held
        if hit_target:
            return 2.0 / 1.5, held
    exit_price = float(future.iloc[-1]["close"])
    pnl = exit_price - entry if direction == "LONG" else entry - exit_price
    return max(-1.0, min(2.0 / 1.5, pnl / risk)), horizon


def _cost_r(entry: float, atr: float, bars_held: int, scenario: Mapping[str, float]) -> float:
    """Convert round-trip bps plus estimated funding into R using 1.5 ATR initial risk."""
    if entry <= 0 or atr <= 0:
        raise ValueError("entry and ATR must be positive")
    if bars_held < 1:
        raise ValueError("bars_held must be at least one")
    fee = float(scenario["fee_bps_per_side"])
    slippage = float(scenario["slippage_bps_per_side"])
    funding = float(scenario["funding_bps_per_8h"])
    if min(fee, slippage, funding) < 0:
        raise ValueError("cost assumptions cannot be negative")
    total_bps = 2 * (fee + slippage) + funding * (bars_held * 4 / 8)
    risk_fraction = (1.5 * atr) / entry
    return total_bps / (risk_fraction * 10_000)


def _stats(rows: list[dict], cost_scenario: Mapping[str, float]) -> dict:
    if not rows:
        return {"samples": 0, "symbols": 0, "gross_avg_r": 0.0, "net_avg_r": 0.0,
                "win_rate_pct": 0.0, "median_net_r": 0.0, "total_cost_avg_r": 0.0}
    gross = np.asarray([r["gross_r"] for r in rows], dtype=float)
    costs = np.asarray([_cost_r(r["entry"], r["atr"], r["bars_held"], cost_scenario) for r in rows])
    net = gross - costs
    return {
        "samples": int(len(rows)),
        "symbols": len({r["symbol"] for r in rows}),
        "gross_avg_r": round(float(gross.mean()), 5),
        "net_avg_r": round(float(net.mean()), 5),
        "win_rate_pct": round(float((net > 0).mean() * 100), 2),
        "median_net_r": round(float(np.median(net)), 5),
        "total_cost_avg_r": round(float(costs.mean()), 5),
    }


def _deoverlap(rows: list[dict], horizon: int) -> list[dict]:
    selected, last = [], {}
    for row in sorted(rows, key=lambda r: (r["symbol"], r["index"])):
        key = row["symbol"]
        if row["index"] - last.get(key, -horizon) < horizon:
            continue
        selected.append(row)
        last[key] = row["index"]
    return selected


def _block_bootstrap_ci(rows: list[dict], scenario: Mapping[str, float], horizon: int,
                        iterations: int = 1000, seed: int = 20261015) -> dict:
    """Moving-block bootstrap within each symbol; reports a descriptive 95% CI."""
    if len(rows) < 2:
        return {"iterations": 0, "confidence": 0.95, "lower_net_avg_r": None,
                "upper_net_avg_r": None, "method": "within-symbol moving-block bootstrap"}
    rng = np.random.default_rng(seed)
    by_symbol: dict[str, list[dict]] = defaultdict(list)
    for row in sorted(rows, key=lambda r: (r["symbol"], r["index"])):
        by_symbol[row["symbol"]].append(row)
    nets = {symbol: np.asarray([
        row["gross_r"] - _cost_r(row["entry"], row["atr"], row["bars_held"], scenario)
        for row in group
    ], dtype=float) for symbol, group in by_symbol.items()}
    boot_means = []
    for _ in range(iterations):
        sampled = []
        for symbol, values in nets.items():
            n = len(values)
            block = max(1, min(horizon, n))
            chunks = []
            while sum(len(chunk) for chunk in chunks) < n:
                start = int(rng.integers(0, n))
                chunks.append(np.asarray([values[(start + offset) % n] for offset in range(block)]))
            sampled.extend(np.concatenate(chunks)[:n].tolist())
        if sampled:
            boot_means.append(float(np.mean(sampled)))
    return {
        "iterations": iterations, "confidence": 0.95,
        "lower_net_avg_r": round(float(np.quantile(boot_means, 0.025)), 5),
        "upper_net_avg_r": round(float(np.quantile(boot_means, 0.975)), 5),
        "method": "circular moving-block bootstrap within each symbol; descriptive, not a guarantee",
    }


def analyze_execution_robustness(
    frames: Mapping[str, pd.DataFrame],
    horizon: int = 6,
    holdout_start_fraction: float = HOLDOUT_START_FRACTION,
    min_train_samples: int = 20,
    min_train_win_rate_pct: float = 50.0,
    bootstrap_iterations: int = 1000,
) -> dict:
    if horizon < 1:
        raise ValueError("horizon must be at least 1")
    if not 0.6 <= holdout_start_fraction <= 0.9:
        raise ValueError("holdout_start_fraction must be between 0.60 and 0.90")
    if min_train_samples < 1:
        raise ValueError("min_train_samples must be at least 1")
    if bootstrap_iterations < 100:
        raise ValueError("bootstrap_iterations must be at least 100")

    prepared, errors = {}, {}
    for raw_symbol, raw in frames.items():
        symbol = str(raw_symbol).upper()
        try:
            frame = add_features(raw).reset_index(drop=True)
            required = {"open", "high", "low", "close", "volume", "taker_buy_base", "trades", "atr14"}
            missing = sorted(required - set(frame.columns))
            if missing:
                raise ValueError("missing columns: " + ", ".join(missing))
            if len(frame) < 250:
                raise ValueError("insufficient candles for final holdout")
            prepared[symbol] = frame
        except Exception as exc:
            errors[symbol] = f"{type(exc).__name__}: {exc}"

    training: dict[tuple[str, ...], dict[str, list[dict]]] = defaultdict(lambda: {"LONG": [], "SHORT": []})
    test_candidates = []
    boundaries = {}
    for symbol, frame in prepared.items():
        n = len(frame)
        split = int(n * holdout_start_fraction)
        boundaries[symbol] = {
            "candles": n,
            "training_end": str(frame["open_time"].iloc[split - 1]) if "open_time" in frame else split - 1,
            "holdout_start": str(frame["open_time"].iloc[split]) if "open_time" in frame else split,
            "holdout_end": str(frame["open_time"].iloc[-1]) if "open_time" in frame else n - 1,
            "training_candles": split,
            "holdout_candles": n - split,
        }
        for i in range(60, n - horizon):
            key = pattern_key(frame.iloc[i])
            if key is None:
                continue
            for direction in ("LONG", "SHORT"):
                outcome = _outcome_and_bars(frame, i, direction, horizon)
                if outcome is None:
                    continue
                gross_r, bars_held = outcome
                item = {
                    "symbol": symbol, "index": i, "pattern": key, "direction": direction,
                    "gross_r": gross_r, "bars_held": bars_held,
                    "entry": float(frame.iloc[i]["close"]), "atr": float(frame.iloc[i]["atr14"]),
                }
                if i + horizon < split:
                    training[key][direction].append(item)
                elif i >= split and i + horizon < n:
                    test_candidates.append(item)

    base = DEFAULT_COST_SCENARIOS["base"]
    selected_directions = {}
    for key, directions in training.items():
        passing = []
        for direction, observations in directions.items():
            observations = _deoverlap(observations, horizon)
            adjusted = [r["gross_r"] - _cost_r(r["entry"], r["atr"], r["bars_held"], base)
                        for r in observations]
            wins = sum(value > 0 for value in adjusted)
            if (len(observations) >= min_train_samples and adjusted
                    and float(np.mean(adjusted)) > 0
                    and wins / len(adjusted) * 100 >= min_train_win_rate_pct):
                passing.append((float(np.mean(adjusted)), len(observations), direction))
        if passing:
            best = max(passing, key=lambda item: (item[0], item[1]))
            selected_directions[key] = best[2]

    selected = _deoverlap([
        row for row in test_candidates
        if selected_directions.get(row["pattern"]) == row["direction"]
    ], horizon)
    scenarios = {
        name: {
            **_stats(selected, assumptions),
            "by_symbol": {
                symbol: _stats([r for r in selected if r["symbol"] == symbol], assumptions)
                for symbol in sorted(prepared)
            },
        }
        for name, assumptions in DEFAULT_COST_SCENARIOS.items()
    }
    ci = _block_bootstrap_ci(selected, base, horizon, bootstrap_iterations)
    return {
        "research_only": True,
        "signal_engine_modified": False,
        "real_money_enabled": False,
        "method": "single final chronological holdout; direction selection uses only the first 80% of each symbol history",
        "timeframe": "4h",
        "forward_horizon_bars": horizon,
        "holdout_start_fraction": holdout_start_fraction,
        "symbols_loaded": len(prepared),
        "symbol_errors": errors,
        "date_boundaries": boundaries,
        "selected_training_pattern_directions": len(selected_directions),
        "holdout_selected_observations": len(selected),
        "cost_assumptions": {
            name: {**assumptions, "meaning": "per-side fee/slippage bps; funding bps per 8h held"}
            for name, assumptions in DEFAULT_COST_SCENARIOS.items()
        },
        "cost_scenarios": scenarios,
        "base_cost_bootstrap_ci": ci,
        "holdout_pass": bool(selected and scenarios["base"]["net_avg_r"] > 0
                             and ci["lower_net_avg_r"] is not None
                             and ci["lower_net_avg_r"] > 0
                             and scenarios["stress"]["net_avg_r"] > 0),
        "limitations": [
            "Fee, slippage, and funding values are explicit proxy assumptions, not historical exchange measurements.",
            "Entry is approximated at the signal candle close; real execution may differ, including gaps.",
            "Funding is approximated at a fixed rate per 8 hours, not actual historical funding by symbol.",
            "The holdout is one chronological period and is not reused for tuning by this workflow.",
            "Bootstrap intervals are descriptive and cannot remove regime shifts or cross-asset dependence.",
            "No live signal generation, order placement, or real-money settings are changed.",
        ],
    }


if __name__ == "__main__":
    symbols = [s.strip().upper() for s in os.getenv(
        "AURELIS_PATTERN_SYMBOLS",
        "BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT,XRPUSDT,ADAUSDT,DOGEUSDT,LINKUSDT,AVAXUSDT,DOTUSDT"
    ).split(",") if s.strip()]
    days = int(os.getenv("AURELIS_PATTERN_DAYS", "1095"))
    iterations = int(os.getenv("AURELIS_BOOTSTRAP_ITERATIONS", "1000"))
    frames = load_symbols(symbols, interval="4h", days=days)
    print(json.dumps(analyze_execution_robustness(frames, bootstrap_iterations=iterations), indent=2, default=str))
