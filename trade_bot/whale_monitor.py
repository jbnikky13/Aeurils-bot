import os
from .whale_provider import fetch_erc20_transfers
from .whale_engine import summarize_labeled_events


def configured_addresses(name: str) -> set[str]:
    return {x.strip().lower() for x in os.getenv(name, "").split(",") if x.strip()}


def monitor_token(address: str, contract: str, chainid: int = 1):
    events = fetch_erc20_transfers(address, contract, chainid=chainid)
    return summarize_labeled_events(events, configured_addresses("EXCHANGE_WALLETS"), configured_addresses("WHALE_WALLETS"))
