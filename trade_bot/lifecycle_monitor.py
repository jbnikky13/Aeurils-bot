"""Monitor open signals and close them when TP/SL levels are reached."""
import httpx
from .signal_lifecycle import open_signals, close_signal


def _price(symbol):
    r = httpx.get("https://api.binance.com/api/v3/ticker/price", params={"symbol": symbol.upper()}, timeout=15)
    r.raise_for_status()
    return float(r.json()["price"])


def _outcome(direction, price, stop, tp1, tp2):
    if direction == "LONG":
        if tp2 is not None and price >= tp2: return "WIN_TP2"
        if tp1 is not None and price >= tp1: return "WIN_TP1"
        if stop is not None and price <= stop: return "LOSS_SL"
    elif direction == "SHORT":
        if tp2 is not None and price <= tp2: return "WIN_TP2"
        if tp1 is not None and price <= tp1: return "WIN_TP1"
        if stop is not None and price >= stop: return "LOSS_SL"
    return None


def monitor_once():
    closed = []
    for signal in open_signals():
        try:
            price = _price(signal["symbol"])
            outcome = _outcome(signal["direction"], price, signal["stop_loss"], signal["tp1"], signal["tp2"])
            if outcome and close_signal(signal["id"], outcome):
                closed.append({"id": signal["id"], "symbol": signal["symbol"], "outcome": outcome, "price": price})
        except Exception as exc:
            print(f"monitor error signal={signal.get('id')}: {exc}")
    return closed


if __name__ == "__main__":
    print(monitor_once())
