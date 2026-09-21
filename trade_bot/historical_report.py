"""Build a Binance historical-intelligence report for AURELIS."""
from __future__ import annotations
import json, os
from .binance_history import fetch_klines
from .historical_features import add_features, feature_snapshot
from .historical_intelligence import match


def build(symbols=None, days=None):
    symbols=symbols or [s.strip().upper() for s in os.getenv("AURELIS_HISTORY_SYMBOLS","BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT,XRPUSDT").split(",") if s.strip()]
    days=days or int(os.getenv("AURELIS_HISTORY_DAYS","180"))
    result={"days":days,"symbols":{}}
    for symbol in symbols:
        try:
            df=fetch_klines(symbol,"4h",days)
            x=add_features(df)
            snap=feature_snapshot(x)
            result["symbols"][symbol]={
                "rows":len(x),
                "start":str(x.open_time.min()),
                "end":str(x.open_time.max()),
                "latest_features":snap,
                "long":match(x,snap,"LONG"),
                "short":match(x,snap,"SHORT"),
            }
        except Exception as exc:
            result["symbols"][symbol]={"error":str(exc)}
    return result


if __name__=="__main__":
    print(json.dumps(build(),indent=2))
