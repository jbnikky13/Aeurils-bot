from .market_data import crypto_klines, stock_daily
from .indicators import enrich, score as technical_score
from .signal_engine import build_setup
from .stock_sentiment import score as stock_sentiment
from .whale_engine import WhaleEvent, whale_bias


def crypto_setup(symbol: str):
    df = crypto_klines(symbol)
    tech, tbias, atr, reasons = technical_score(df)
    # Whale provider is intentionally fail-closed until labeled on-chain events are supplied.
    wbias, whale = 0.0, 50
    setup = build_setup(symbol, "crypto", float(df.iloc[-1].close), tech, whale, 50, tbias, wbias, atr)
    setup.reasons = reasons + ["whale-flow data not yet confirmed by labeled wallet events"]
    return setup


def stock_setup(symbol: str):
    df = stock_daily(symbol)
    tech, tbias, atr, reasons = technical_score(df)
    sentiment, s_reasons = stock_sentiment(symbol)
    setup = build_setup(symbol, "stock", float(df.iloc[-1].close), tech, 50, sentiment, tbias, 0.0, atr)
    setup.reasons = reasons + s_reasons + ["whale-flow component is crypto-only"]
    return setup
