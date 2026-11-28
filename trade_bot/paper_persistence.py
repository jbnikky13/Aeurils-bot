"""Persist the paper ledger between ephemeral GitHub Actions runners."""
import json, os, sqlite3
from .journal import DB, init_db
from .paper_trader import init_paper_db

STORE=os.getenv('PAPER_LEDGER_PATH','data/aurelis_paper_ledger.json')

def _tables():
    init_paper_db()
    from .fv1_runtime import initialize
    from .fv1_risk_ledger import initialize as initialize_risk_ledger
    initialize()
    initialize_risk_ledger()
    out={}
    with sqlite3.connect(DB) as con:
        for table in ('setups','paper_trades','fv1_meta','fv1_cohort','fv1_watchlist_history','fv1_equity_snapshots','fv1_risk_events'):
            exists=con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone()
            if not exists: continue
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
    init_paper_db()
    from .fv1_runtime import initialize
    from .fv1_risk_ledger import initialize as initialize_risk_ledger
    initialize()
    initialize_risk_ledger()
    if not os.path.exists(STORE): return
    with open(STORE,encoding='utf-8') as f: data=json.load(f)
    with sqlite3.connect(DB) as con:
        for table,payload in data.items():
            if table not in {'setups','paper_trades','fv1_meta','fv1_cohort','fv1_watchlist_history','fv1_equity_snapshots','fv1_risk_events'}: continue
            exists=con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone()
            if not exists: continue
            source_cols=payload.get('columns',[])
            if not source_cols: continue
            target_cols={r[1] for r in con.execute(f'PRAGMA table_info({table})').fetchall()}
            cols=[c for c in source_cols if c in target_cols]
            if not cols: continue
            placeholders=','.join('?' for _ in cols)
            col_sql=','.join(cols)
            for row in payload.get('rows',[]):
                values=[row.get(c) for c in cols]
                con.execute(f'INSERT OR REPLACE INTO {table} ({col_sql}) VALUES ({placeholders})',values)
        con.commit()

if __name__=='__main__':
    import sys
    if len(sys.argv)>1 and sys.argv[1]=='restore': restore_ledger()
    else: export_ledger()
