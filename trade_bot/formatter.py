from .signal_engine import Signal


def money(value: float | None) -> str:
    if value is None:
        return "—"
    return f"${value:,.4f}" if value < 10 else f"${value:,.2f}"


def format_signal(s: Signal) -> str:
    """Return the intentionally minimal daily trade setup."""
    if s.direction == "WAIT":
        return f"WAIT {s.symbol}"
    action = "BUY" if s.direction == "LONG" else "SELL"
    entry = money((float(s.entry_low) + float(s.entry_high)) / 2) if s.entry_low is not None and s.entry_high is not None else money(None)
    lines = [
        f"{action} {s.symbol} @ {entry}",
        f"TP1. {money(s.take_profit_1)}",
        f"TP2. {money(s.take_profit_2)}",
        f"SL. {money(s.stop_loss)}",
        "",
        "MANAGE RISK ⚠️",
    ]
    return "\n".join(lines)
