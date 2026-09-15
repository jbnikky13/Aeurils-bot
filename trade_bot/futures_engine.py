"""Futures momentum/continuation intelligence for AURELIS.

This module is deliberately read-only. It identifies conditions where a strong
4H trend can continue even when RSI is already stretched. It never places orders.
"""
from __future__ import annotations

from dataclasses import dataclass
import pandas as pd


@dataclass(frozen=True)
class ContinuationAssessment:
    mode: str
    score: int
    direction: str
    breakout: bool
    trend_aligned: bool
    momentum_confirmed: bool
    volume_confirmed: bool
    flow_confirmed: bool
    liquidation_pressure: bool
    reasons: list[str]


def _b(v: bool) -> int:
    return 1 if v else 0


def assess(df: pd.DataFrame, direction: str, flow: dict | None = None) -> ContinuationAssessment:
    """Score a directional futures continuation setup from completed candles."""
    flow = flow or {}
    if len(df) < 30:
        return ContinuationAssessment("NORMAL", 0, direction, False, False, False, False, False, False,
                                     ["Insufficient candles for continuation analysis."])

    r = df.iloc[-1]
    prior = df.iloc[:-1]
    required = ["close", "high", "low", "volume", "ema20", "ema50", "ema200", "rsi", "adx", "macd_hist", "atr", "volume_ratio"]
    if any(k not in df.columns for k in required):
        return ContinuationAssessment("NORMAL", 0, direction, False, False, False, False, False, False,
                                     ["Continuation indicators are unavailable."])

    atr = float(r.atr or 0)
    close = float(r.close)
    if atr <= 0 or close <= 0:
        return ContinuationAssessment("NORMAL", 0, direction, False, False, False, False, False, False,
                                     ["Invalid ATR/price for continuation analysis."])

    lookback = min(20, len(prior))
    prev_high = float(prior.tail(lookback).high.max())
    prev_low = float(prior.tail(lookback).low.min())
    buffer = 0.10 * atr

    trend_long = close > float(r.ema20) > float(r.ema50) > float(r.ema200)
    trend_short = close < float(r.ema20) < float(r.ema50) < float(r.ema200)
    trend_aligned = trend_long if direction == "LONG" else trend_short

    breakout = (close > prev_high + buffer) if direction == "LONG" else (close < prev_low - buffer)
    momentum = (float(r.macd_hist) > 0 and float(r.rsi) >= 45) if direction == "LONG" else (float(r.macd_hist) < 0 and float(r.rsi) <= 55)
    volume = float(r.volume_ratio) >= 1.20
    acceleration_volume = float(r.volume_ratio) >= 1.50
    strong_trend = float(r.adx) >= 25

    oi = flow.get("oi_change_pct")
    taker = flow.get("taker_ratio")
    oi_confirmed = (oi is not None and float(oi) >= 0.50)
    taker_confirmed = (taker is not None and ((float(taker) > 1.03) if direction == "LONG" else (float(taker) < 0.97)))
    flow_confirmed = oi_confirmed or taker_confirmed

    liquidation = bool(flow.get("liquidation_pressure", False))
    # Liquidations strengthen an already-confirmed trend; they never create a
    # trade by themselves.
    score = (
        25 * _b(trend_aligned)
        + 20 * _b(breakout)
        + 15 * _b(momentum)
        + 15 * _b(volume)
        + 15 * _b(flow_confirmed)
        + 10 * _b(strong_trend and acceleration_volume)
    )

    reasons = [
        f"4H trend alignment: {'yes' if trend_aligned else 'no'}",
        f"20-candle {'breakout' if direction == 'LONG' else 'breakdown'}: {'yes' if breakout else 'no'}",
        f"Momentum confirmation: {'yes' if momentum else 'no'}",
        f"Volume: {float(r.volume_ratio):.2f}x average",
        f"ADX: {float(r.adx):.1f}",
    ]
    if oi is not None:
        reasons.append(f"Futures OI change: {float(oi):+.2f}%")
    if taker is not None:
        reasons.append(f"Futures taker ratio: {float(taker):.2f}")
    if liquidation:
        reasons.append("Liquidation pressure supports the existing trend")

    if score >= 70 and trend_aligned and (breakout or strong_trend) and momentum:
        mode = "BREAKOUT" if breakout else "CONTINUATION"
    else:
        mode = "NORMAL"

    return ContinuationAssessment(mode, int(score), direction, breakout, trend_aligned, momentum,
                                  volume, flow_confirmed, liquidation, reasons)
