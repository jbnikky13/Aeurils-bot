"""End-to-end production smoke test.

Runs one real market-analysis path, validates the resulting setup, records a
TEST journal event, and sends a clearly labelled Telegram test message.
Never represents the test as a live trade signal.
"""
import asyncio, json, os
from datetime import datetime, timezone
import httpx
from .live_setup import crypto_setup, stock_setup
from .formatter import format_signal
from .journal import record


def _telegram(text: str) -> dict:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    if not token or not chat_id:
        raise RuntimeError("Telegram credentials are not configured")
    r = httpx.post(f"https://api.telegram.org/bot{token}/sendMessage", json={"chat_id": chat_id, "text": text[:4096]}, timeout=20)
    r.raise_for_status()
    payload = r.json()
    if not payload.get("ok"):
        raise RuntimeError(payload.get("description", "Telegram sendMessage failed"))
    return payload


def _validate_setup(setup):
    if setup is None:
        raise RuntimeError("Setup engine returned no result")
    if getattr(setup, "direction", None) not in {"LONG", "SHORT", "WAIT"}:
        raise RuntimeError("Invalid signal direction")
    if not 0 <= int(setup.score) <= 100:
        raise RuntimeError("Invalid signal score")
    if setup.direction != "WAIT":
        for field in ("entry_low", "entry_high", "stop_loss", "take_profit_1", "take_profit_2", "risk_reward"):
            if getattr(setup, field, None) is None:
                raise RuntimeError(f"Actionable setup missing {field}")
        if float(setup.risk_reward) <= 0:
            raise RuntimeError("Actionable setup has non-positive R:R")


async def main():
    symbol = os.getenv("SMOKE_TEST_SYMBOL", "BTCUSDT")
    setup = await crypto_setup(symbol)
    _validate_setup(setup)
    record({"timestamp": datetime.now(timezone.utc).isoformat(), "symbol": symbol, "direction": setup.direction, "score": setup.score, "status": "TEST", "entry": setup.entry_low, "stop_loss": setup.stop_loss, "take_profit_1": setup.take_profit_1, "take_profit_2": setup.take_profit_2, "risk_reward": setup.risk_reward})
    message = "🧪 AURELIS PRODUCTION TEST\n\n" + format_signal(setup) + "\n\nTEST ONLY — not a trade recommendation."
    result = _telegram(message)
    print(json.dumps({"status":"PASS", "telegram_ok":result.get("ok"), "message_id":result.get("result",{}).get("message_id"), "symbol":symbol}))

if __name__ == "__main__":
    asyncio.run(main())
