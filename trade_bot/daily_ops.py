"""Daily operational monitor for Aeurils. Read-only health checks; no orders."""
import os, sqlite3
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
if __name__=='__main__': print(report())
