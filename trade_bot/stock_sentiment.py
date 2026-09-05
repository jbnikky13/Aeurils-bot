import os
import httpx


def score(symbol: str) -> tuple[int, list[str]]:
    key = os.getenv("STOCK_API_KEY")
    if not key:
        return 50, ["stock sentiment unavailable"]
    r = httpx.get("https://www.alphavantage.co/query", params={"function":"NEWS_SENTIMENT","tickers":symbol.upper(),"limit":20,"apikey":key}, timeout=20)
    r.raise_for_status()
    data = r.json()
    feed = data.get("feed", [])
    if not feed:
        return 50, ["no recent stock news sentiment available"]
    values = []
    for item in feed:
        for s in item.get("ticker_sentiment", []):
            if s.get("ticker") == symbol.upper():
                try: values.append(float(s.get("ticker_sentiment_score", 0)))
                except (TypeError, ValueError): pass
    if not values:
        return 50, ["no ticker-level sentiment available"]
    avg = sum(values) / len(values)
    return max(0, min(100, round(50 + avg * 50))), [f"news sentiment score {avg:+.2f}"]
