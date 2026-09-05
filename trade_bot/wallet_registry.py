"""Trusted wallet registry. Gemini candidates are never trusted automatically."""
import json
import os
from pathlib import Path

REGISTRY_PATH = Path(os.getenv("WALLET_REGISTRY_PATH", "trade_bot/wallet_registry.json"))


def load_registry() -> dict:
    if not REGISTRY_PATH.exists():
        return {"whales": {}, "exchanges": {}}
    return json.loads(REGISTRY_PATH.read_text())


def save_registry(registry: dict) -> None:
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_PATH.write_text(json.dumps(registry, indent=2, sort_keys=True))


def verified_addresses() -> tuple[set[str], set[str]]:
    r = load_registry()
    return set(r.get("whales", {})), set(r.get("exchanges", {}))
