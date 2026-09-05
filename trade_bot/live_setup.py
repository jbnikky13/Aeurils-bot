import os
from .market_data import crypto_klines, stock_daily
from .indicators import score as technical_score
from .signal_engine import build_setup
from .stock_sentiment import score as stock_sentiment
from .whale_provider import fetch_erc20_transfers, summarize_labeled_events
from .gemini_signal import confirm


def _csv_set(name: str) -> set[str]:
    return {x.strip().lower() for x in os.getenv(name, "").split(",") if x.strip()}

def _contract_for(symbol: str) -> str:
    for item in os.getenv("TOKEN_CONTRACTS", "").split(","):
        if ":" in item:
            name, address = item.split(":", 1)
            if name.strip().upper() == symbol.upper(): return address.strip()
    raise RuntimeError(f"No token contract configured for {symbol}")

async def crypto_setup(symbol: str):
    df = crypto_klines(symbol)
    tech, tbias, atr, reasons = technical_score(df)
    whales, exchanges = _csv_set("WHALE_WALLETS"), _csv_set("EXCHANGE_WALLETS")
    if not whales or not exchanges: raise RuntimeError("Verified whale/exchange wallets are required")
    events=[]
    for address in whales: events.extend(await fetch_erc20_transfers(address, _contract_for(symbol)))
    summary=summarize_labeled_events(events, exchanges, whales)
    preliminary=build_setup(symbol,"crypto",float(df.iloc[-1].close),tech,summary.score,50,tbias,summary.bias,atr)
    ai=confirm(symbol,tech,tbias,summary.score,summary.bias,float(df.iloc[-1].close),atr)
    if ai["decision"] != preliminary.direction or ai["confidence"] < float(os.getenv("GEMINI_MIN_CONFIDENCE","70")):
        preliminary.direction="WAIT"; preliminary.entry_low=preliminary.entry_high=preliminary.stop_loss=preliminary.take_profit_1=preliminary.take_profit_2=preliminary.risk_reward=None
        preliminary.invalidation="Gemini confirmation did not meet the configured confidence/consensus gate."
    preliminary.reasons = reasons + summary.reasons + [f"Gemini confirmation: {ai['decision']} ({ai['confidence']:.0f}/100)", ai.get("rationale", "")]
    return preliminary

def stock_setup(symbol: str):
    df=stock_daily(symbol); tech,tbias,atr,reasons=technical_score(df); sentiment,sr=stock_sentiment(symbol)
    return build_setup(symbol,"stock",float(df.iloc[-1].close),tech,50,sentiment,tbias,0.0,atr)
