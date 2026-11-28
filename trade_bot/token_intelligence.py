"""Deterministic Binance spot token research ranking; never trade authorization."""
from __future__ import annotations
import math
from datetime import datetime, timezone

WEIGHTS = {"liquidity_spread":25, "behavior_consistency":20, "trend_structure":15,
           "volatility_quality":15, "signal_quality":15, "data_quality":10}

def _finite(x):
    try: return math.isfinite(float(x))
    except (TypeError, ValueError): return False

def _clamp(x):
    return max(0.0, min(1.0, float(x)))

def analyze_behavior(candles):
    """Use chronologically ordered CLOSED OHLCV candles only."""
    rows = [r for r in candles if all(_finite(r.get(k)) for k in ("open","high","low","close","volume"))
            and float(r["close"]) > 0 and float(r["high"]) >= float(r["low"])]
    if len(rows) < 30:
        return {"eligible":False,"reason":"insufficient_closed_history","rows":len(rows)}
    closes=[float(r["close"]) for r in rows]; highs=[float(r["high"]) for r in rows]
    lows=[float(r["low"]) for r in rows]; vols=[float(r["volume"]) for r in rows]
    returns=[closes[i]/closes[i-1]-1 for i in range(1,len(closes))]
    trend=closes[-1]/closes[-7]-1
    recent=returns[-30:]
    vol=math.sqrt(sum(x*x for x in recent)/len(recent))*math.sqrt(6)*100
    ranges=[(highs[i]-lows[i])/closes[i] for i in range(len(rows)-30,len(rows))]
    avgvol=sum(vols[-30:])/30
    cv=math.sqrt(sum((x-avgvol)**2 for x in vols[-30:])/30)/avgvol if avgvol else float("inf")
    consistency=sum(1 for x in recent if x*trend>0)/len(recent) if trend else .5
    return {"eligible":True,"rows":len(rows),"trend_7d_pct":trend*100,
            "realized_vol_pct":vol,"avg_candle_range_pct":sum(ranges)/len(ranges)*100,
            "volume_avg":avgvol,"volume_cv":cv,"trend_consistency":consistency,
            "latest_close":closes[-1]}

def score_token(metrics, quote_volume_usd, spread_pct, signal_quality=.5):
    if not metrics.get("eligible"): return {"eligible":False,"score":0,"reason":metrics.get("reason","invalid_metrics")}
    if not all(_finite(x) for x in (quote_volume_usd,spread_pct,signal_quality)) or quote_volume_usd < 2_000_000:
        return {"eligible":False,"score":0,"reason":"liquidity_or_input_invalid"}
    if spread_pct < 0 or spread_pct > .35:
        return {"eligible":False,"score":0,"reason":"spread_outside_limit"}
    vol=metrics.get("realized_vol_pct",float("nan"))
    if not _finite(vol): return {"eligible":False,"score":0,"reason":"volatility_invalid"}
    components={
      "liquidity_spread":25*_clamp(math.log10(max(quote_volume_usd,1)/2_000_000)/2)*(1-_clamp(spread_pct/.35)),
      "behavior_consistency":20*_clamp(metrics.get("trend_consistency",0)),
      "trend_structure":15*_clamp(abs(metrics.get("trend_7d_pct",0))/12),
      "volatility_quality":15*_clamp(1-abs(vol-3.5)/7),
      "signal_quality":15*_clamp(signal_quality),
      "data_quality":10*_clamp(1/(1+max(0,metrics.get("volume_cv",1)))),
    }
    return {"eligible":True,"score":round(sum(components.values()),2),
            "components":{k:round(v,2) for k,v in components.items()},"reason":"ranked"}

def select_watchlist(candidates, active_count=10, reserve_count=5):
    valid=[dict(c) for c in candidates if c.get("eligible") and _finite(c.get("score")) and c.get("symbol")]
    valid.sort(key=lambda x:(float(x["score"]),float(x.get("quote_volume_usd",0))),reverse=True)
    return {"selected":valid[:active_count],"reserves":valid[active_count:active_count+reserve_count],
            "unfilled_active_slots":max(0,active_count-len(valid)),
            "unfilled_reserve_slots":max(0,reserve_count-max(0,len(valid)-active_count)),
            "generated_at":datetime.now(timezone.utc).isoformat()}

def rotation_reasons(previous,current):
    old={x["symbol"] for x in previous if x.get("symbol")}
    new={x["symbol"] for x in current if x.get("symbol")}
    return {"added":sorted(new-old),"removed":sorted(old-new),"reason_code":"WEEKLY_RANK_REFRESH"}

def format_watchlist_report(selection):
    lines=["🔎 AURELIS TOKEN INTELLIGENCE","Research/watchlist only · not trade authorization","","TOP 10 WATCH"]
    for i,t in enumerate(selection.get("selected",[]),1):
        lines.append(f"{i}. {t['symbol']} — {float(t.get('score',0)):.1f}/100 | 7d {float(t.get('trend_7d_pct',0)):+.2f}% | vol {float(t.get('realized_vol_pct',0)):.2f}%")
    lines += ["","RESERVES"]+[f"• {t['symbol']} — {float(t.get('score',0)):.1f}" for t in selection.get("reserves",[])]
    if not selection.get("reserves"): lines.append("• None qualified")
    if selection.get("unfilled_active_slots"): lines.append(f"⚠️ Active slots unfilled: {selection['unfilled_active_slots']} (no forced picks)")
    return "\n".join(lines)
