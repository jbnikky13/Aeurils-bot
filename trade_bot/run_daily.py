"""Production daily signal service entrypoint."""
import asyncio
import os
from types import SimpleNamespace
from telegram import Bot
from .scheduler import daily_scan

async def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required for scheduled delivery")
    if not chat_id:
        raise RuntimeError("TELEGRAM_CHAT_ID is required for scheduled delivery")

    # Use the same production gate as the scheduler instead of a separate
    # report-only path. This guarantees that only signals passing the full
    # configured score gate are published as actionable trades.
    async with Bot(token=token) as bot:
        context = SimpleNamespace(bot=bot)
        await daily_scan(context)

if __name__ == "__main__":
    asyncio.run(main())
