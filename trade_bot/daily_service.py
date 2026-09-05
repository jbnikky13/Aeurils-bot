"""Authoritative non-polling entry point for the scheduled daily signal service."""
import asyncio
from types import SimpleNamespace
from .scheduler import daily_scan

class _Bot:
    async def send_message(self, chat_id, text):
        from .telegram_delivery import send
        result=send(text)
        if not result.get('ok'):
            raise RuntimeError(f"Telegram delivery failed: {result.get('error','unknown error')}")

async def main():
    context=SimpleNamespace(bot=_Bot())
    await daily_scan(context)

if __name__=='__main__':
    asyncio.run(main())
