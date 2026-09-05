"""Verified Telegram delivery and delivery-journal helpers."""
import json, os, sqlite3, urllib.request, urllib.parse, uuid
DB=os.getenv('DATABASE_PATH','trade_bot.db')

def send(message):
    token=os.getenv('TELEGRAM_BOT_TOKEN'); chat=os.getenv('TELEGRAM_CHAT_ID')
    if not token or not chat: return {'ok':False,'error':'missing Telegram configuration'}
    url=f'https://api.telegram.org/bot{token}/sendMessage'
    data=urllib.parse.urlencode({'chat_id':chat,'text':message}).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(url,data=data,method='POST'),timeout=15) as r: payload=json.loads(r.read().decode())
        ok=bool(payload.get('ok')); _record(ok,payload.get('result',{}).get('message_id'),None if ok else payload.get('description'))
        return {'ok':ok,'message_id':payload.get('result',{}).get('message_id'),'error':payload.get('description')}
    except Exception as e: _record(False,None,type(e).__name__); return {'ok':False,'error':type(e).__name__}

def _record(ok,message_id,error):
    try:
        con=sqlite3.connect(DB); con.execute('CREATE TABLE IF NOT EXISTS telegram_delivery (id TEXT PRIMARY KEY, delivered_at TEXT DEFAULT CURRENT_TIMESTAMP, ok INTEGER, message_id TEXT, error TEXT)')
        con.execute('INSERT INTO telegram_delivery(id,ok,message_id,error) VALUES(?,?,?,?)',(str(uuid.uuid4()),int(ok),str(message_id) if message_id else None,error)); con.commit(); con.close()
    except Exception: pass
