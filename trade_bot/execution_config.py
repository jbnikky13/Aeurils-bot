"""Demo execution safety and health checks. No live endpoints or live mode."""
import os

def execution_config():
    mode=os.getenv("EXECUTION_MODE","PAPER").upper()
    return {
        "mode":mode,
        "live_enabled":False,
        "demo_enabled":mode=="BINANCE_DEMO",
        "max_positions":int(os.getenv("BINANCE_DEMO_MAX_POSITIONS","3")),
        "max_daily_loss_pct":float(os.getenv("BINANCE_DEMO_MAX_DAILY_LOSS_PCT","2")),
        "max_risk_per_trade_pct":float(os.getenv("BINANCE_DEMO_MAX_RISK_PER_TRADE_PCT","0.5")),
        "max_leverage":int(os.getenv("BINANCE_DEMO_MAX_LEVERAGE","3")),
    }

def assert_demo_only():
    c=execution_config()
    if c["mode"] not in {"PAPER","BINANCE_DEMO"}:
        raise RuntimeError("Unsupported execution mode. Only PAPER or BINANCE_DEMO are allowed.")
    if c["live_enabled"]:
        raise RuntimeError("Live execution is permanently disabled in this adapter.")
    return c
