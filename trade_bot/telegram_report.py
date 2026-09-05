"""Send the daily performance report through the existing Telegram bot."""
import os
import httpx
from .performance_report import build_report


def send_report():
    token=os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id=os.environ["TELEGRAM_CHAT_ID"]
    url=f"https://api.telegram.org/bot{token}/sendMessage"
    response=httpx.post(url,json={"chat_id":chat_id,"text":build_report()},timeout=20)
    response.raise_for_status()
    data=response.json()
    if not data.get("ok"): raise RuntimeError("Telegram rejected performance report")
    return data

if __name__ == "__main__":
    result=send_report()
    print(f"Telegram performance report sent: message_id={result['result']['message_id']}")
