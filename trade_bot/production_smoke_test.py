"""End-to-end production smoke test.

Runs one real market-analysis path, validates the resulting setup, records the
setup through the canonical journal API, and sends a clearly labelled Telegram
test message. The Telegram message is explicitly a test, never a trade alert.
"""
import asyncio
import json
import os
from datetime import datetime, timezone
import httpx
from .live_setup import crypto_setup
from .formatter import format_signal
from .journal import record_setup


def _telegram(text: str) -> dict:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        raise RuntimeError("Telegram credentials are not configured: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required")
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
    score = int(setup.score)
    if not 0 <= score <= 100:
        raise RuntimeError("Invalid signal score")
    if setup.direction != "WAIT":
        for field in ("entry_low", "entry_high", "stop_loss", "take_profit_1", "take_profit_2", "risk_reward"):
            if getattr(setup, field, None) is None:
                raise RuntimeError(f"Actionable setup missing {field}")
        if float(setup.risk_reward) <= 0:
            raise RuntimeError("Actionable setup has non-positive R:R")


async def main():
    symbol = os.getenv("SMOKE_TEST_SYMBOL", "BTCUSDT").strip().upper()
    setup = await crypto_setup(symbol)
    _validate_setup(setup)
    journal_id = record_setup(setup)
    message = (
        "🧪 AURELIS PRODUCTION TEST\n\n"
        + format_signal(setup)
        + f"\n\nJournal ID: {journal_id}\n"
        + datetime.now(timezone.utc).strftime("UTC: %Y-%m-%d %H:%M")
        + "\n\nTEST ONLY — not a trade recommendation."
    )
    result = _telegram(message)
    print(json.dumps({"status":"PASS", "telegram_ok":result.get("ok"), "message_id":result.get("result",{}).get("message_id"), "journal_id":journal_id, "symbol":symbol}))


if __name__ == "__main__":
    asyncio.run(main())
