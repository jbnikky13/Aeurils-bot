import asyncio
import os
from telegram import Bot
from .daily_report import generate_daily_report

async def main():
    token=os.environ['TELEGRAM_BOT_TOKEN']
    chat_id=os.environ.get('TELEGRAM_CHAT_ID')
    if not chat_id: raise RuntimeError('TELEGRAM_CHAT_ID is required for scheduled delivery')
    text=generate_daily_report()
    async with Bot(token=token) as bot:
        for i in range(0,len(text),3900):
            await bot.send_message(chat_id=chat_id,text=text[i:i+3900])

if __name__=='__main__': asyncio.run(main())
