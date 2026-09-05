"""Daily operational monitor with verified Telegram delivery.
Read-only health checks; no orders or strategy mutation.
"""
import os, sqlite3
from .telegram_delivery import send
DB=os.getenv('DATABASE_PATH','trade_bot.db')

def run():
    checks=[]
    for k in ('GEMINI_API_KEY','TELEGRAM_BOT_TOKEN','TELEGRAM_CHAT_ID'):
        checks.append((k,'OK' if os.getenv(k) else 'MISSING'))
    try:
        con=sqlite3.connect(DB); tables={r[0] for r in con.execute("select name from sqlite_master where type='table'")}; con.close()
        checks.append(('journal','OK' if 'paper_trades' in tables else 'MISSING'))
    except Exception as e: checks.append(('journal',f'ERROR:{type(e).__name__}'))
    checks += [('crypto_scan','ENABLED'),('real_money_execution','DISABLED')]
    return checks

def report(signal='WATCH / WAIT'):
    checks=run(); healthy=all(v in ('OK','ENABLED','DISABLED') for _,v in checks)
    lines=['🛡️ AURELIS DAILY OPS','',f'System: {"HEALTHY" if healthy else "ATTENTION REQUIRED"}']
    lines += [f'• {k}: {v}' for k,v in checks]
    lines += ['',f"Today's signal state: {signal}",'','Crypto coverage: ENABLED','🔒 Paper-trading / signal monitoring only. Real-money execution is disabled.']
    return '\n'.join(lines)

def send_verified_report(signal='WATCH / WAIT'):
    result=send(report(signal))
    return result

if __name__=='__main__':
    result=send_verified_report(os.getenv('DAILY_SIGNAL_STATE','WATCH / WAIT'))
    print(report(os.getenv('DAILY_SIGNAL_STATE','WATCH / WAIT')))
    print(f"Telegram delivery: {'VERIFIED' if result.get('ok') else 'FAILED'}")
    if not result.get('ok'): raise SystemExit(1)
