"""Persist the paper ledger between ephemeral GitHub Actions runners."""
import json, os, sqlite3
from .journal import DB, init_db

STORE=os.getenv('PAPER_LEDGER_PATH','data/aurelis_paper_ledger.json')

def _tables():
    init_db()
    with sqlite3.connect(DB) as con:
        out={}
        for table in ('setups','paper_trades'):
            cols=[r[1] for r in con.execute(f'PRAGMA table_info({table})').fetchall()]
            rows=[dict(zip(cols,row)) for row in con.execute(f'SELECT * FROM {table}').fetchall()]
            out[table]={'columns':cols,'rows':rows}
        return out

def export_ledger():
    os.makedirs(os.path.dirname(STORE) or '.',exist_ok=True)
    tmp=STORE+'.tmp'
    with open(tmp,'w',encoding='utf-8') as f: json.dump(_tables(),f,ensure_ascii=False,indent=2,default=str)
    os.replace(tmp,STORE)

def restore_ledger():
    if not os.path.exists(STORE):
        init_db(); return
    init_db()
    with open(STORE,encoding='utf-8') as f: data=json.load(f)
    with sqlite3.connect(DB) as con:
        for table,payload in data.items():
            cols=payload.get('columns',[])
            if not cols: continue
            placeholders=','.join('?' for _ in cols)
            for row in payload.get('rows',[]):
                values=[row.get(c) for c in cols]
                con.execute(f'INSERT OR REPLACE INTO {table} ({','.join(cols)}) VALUES ({placeholders})',values)
        con.commit()

if __name__=='__main__':
    import sys
    if len(sys.argv)>1 and sys.argv[1]=='restore': restore_ledger()
    else: export_ledger()
