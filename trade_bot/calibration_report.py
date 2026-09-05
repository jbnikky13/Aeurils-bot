"""Telegram delivery for calibration analytics."""
import os, httpx
from .calibration import format_report

def send():
    token=os.environ["TELEGRAM_BOT_TOKEN"]; chat=os.environ["TELEGRAM_CHAT_ID"]
    r=httpx.post(f"https://api.telegram.org/bot{token}/sendMessage",json={"chat_id":chat,"text":format_report()},timeout=20)
    r.raise_for_status(); data=r.json()
    if not data.get("ok"): raise RuntimeError("Telegram rejected calibration report")
    return data
if __name__ == "__main__": print(f"Calibration report sent: {send()['result']['message_id']}")
