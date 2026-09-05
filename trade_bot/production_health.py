"""Phase 10 production health checks. Read-only; no trading or strategy mutation."""
import os, sqlite3
DB=os.getenv('DATABASE_PATH','trade_bot.db')

def check():
    out=[]
    for k in ('TELEGRAM_BOT_TOKEN','TELEGRAM_CHAT_ID'):
        out.append((k,'OK' if os.getenv(k) else 'MISSING'))
    try:
        con=sqlite3.connect(DB); tables={r[0] for r in con.execute("select name from sqlite_master where type='table'")}; con.close()
        out.append(('database','OK' if 'paper_trades' in tables else 'MISSING_PAPER_TRADES_TABLE'))
    except Exception as e: out.append(('database',f'ERROR:{type(e).__name__}'))
    out.append(('real_money_execution','DISABLED'))
    return out

def format_report():
    checks=check(); ok=all(v in ('OK','DISABLED') for _,v in checks)
    lines=['🛡️ AURELIS PRODUCTION HEALTH','',f'Status: {"HEALTHY" if ok else "ATTENTION_REQUIRED"}']
    lines += [f'• {k}: {v}' for k,v in checks]
    lines += ['', '🔒 Health check is read-only. Real-money execution remains disabled.']
    return '\n'.join(lines)

if __name__=='__main__': print(format_report())
