from .signal_engine import Signal


def money(value: float | None) -> str:
    if value is None:
        return "—"
    return f"${value:,.4f}" if value < 10 else f"${value:,.2f}"


def format_signal(s: Signal) -> str:
    """Format a signal with an estimated TP horizon, not a forced expiry."""
    if s.direction == "WAIT":
        return f"WAIT {s.symbol}"
    action = "BUY" if s.direction == "LONG" else "SELL"
    entry = money((float(s.entry_low) + float(s.entry_high)) / 2) if s.entry_low is not None and s.entry_high is not None else money(None)
    eta1 = f"~{s.tp1_eta_hours:.1f}h" if s.tp1_eta_hours is not None else "—"
    eta2 = f"~{s.tp2_eta_hours:.1f}h" if s.tp2_eta_hours is not None else "—"
    if s.horizon_status == "WITHIN_24H":
        horizon = "✅ WITHIN 24H"
    elif s.horizon_status == "OVER_24H":
        horizon = "⚠️ EXTENDED (>24H)"
    else:
        horizon = "ℹ️ ESTIMATE UNAVAILABLE"
    lines = [
        f"{action} {s.symbol} @ {entry}",
        f"TP1. {money(s.take_profit_1)} ({eta1})",
        f"TP2. {money(s.take_profit_2)} ({eta2})",
        f"SL. {money(s.stop_loss)}",
        f"HORIZON. {horizon}",
        f"EXPECTED TP1. {eta1}",
        "",
        "MANAGE RISK ⚠️",
    ]
    return "\n".join(lines)
