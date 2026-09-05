import os
from .market_data import crypto_klines, stock_daily
from .indicators import enrich, score as technical_score
from .signal_engine import build_setup
from .stock_sentiment import score as stock_sentiment
from .whale_provider import fetch_erc20_transfers, summarize_labeled_events


def _csv_set(name: str) -> set[str]:
    return {x.strip().lower() for x in os.getenv(name, "").split(",") if x.strip()}


def _contract_for(symbol: str) -> str:
    for item in os.getenv("TOKEN_CONTRACTS", "").split(","):
        if ":" in item:
            name, address = item.split(":", 1)
            if name.strip().upper() == symbol.upper():
                return address.strip()
    raise RuntimeError(f"No token contract configured for {symbol}")


async def crypto_setup(symbol: str):
    df = crypto_klines(symbol)
    tech, tbias, atr, reasons = technical_score(df)
    contract = _contract_for(symbol)
    whale_addresses = _csv_set("WHALE_WALLETS")
    exchange_addresses = _csv_set("EXCHANGE_WALLETS")
    if not whale_addresses or not exchange_addresses:
        raise RuntimeError("WHALE_WALLETS and EXCHANGE_WALLETS must be configured before crypto signals are published")
    events = []
    for address in whale_addresses:
        events.extend(await fetch_erc20_transfers(address, contract))
    summary = summarize_labeled_events(events, exchange_addresses, whale_addresses)
    setup = build_setup(symbol, "crypto", float(df.iloc[-1].close), tech, summary.score, 50, tbias, summary.bias, atr)
    setup.reasons = reasons + summary.reasons
    return setup


def stock_setup(symbol: str):
    df = stock_daily(symbol)
    tech, tbias, atr, reasons = technical_score(df)
    sentiment, s_reasons = stock_sentiment(symbol)
    setup = build_setup(symbol, "stock", float(df.iloc[-1].close), tech, 50, sentiment, tbias, 0.0, atr)
    setup.reasons = reasons + s_reasons + ["whale-flow component is crypto-only"]
    return setup
