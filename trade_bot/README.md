# Aeurils Trade Bot

Telegram market-analysis bot for daily cryptocurrency and stock trade setups.

## Planned live pipeline
Market data → technical indicators → crypto whale-flow analysis → sentiment/news → weighted signal score → risk/reward setup → Telegram → performance journal.

Whale activity is confirmation, not proof of future price direction. The system should never fabricate missing whale or market data.

## Commands
/start
/today
/crypto
/stocks
/setup BTCUSDT
/help

## Environment
Copy `.env.example` to `.env` locally or configure the same variables as deployment secrets. Never commit real API keys or Telegram tokens.

## Status
The repository contains the initial signal engine, whale classifier, formatter, Telegram interface and dependency configuration. Live market/whale/stock adapters and persistent performance tracking are the next implementation phase.

## Disclaimer
This software provides informational market analysis and does not guarantee returns or constitute personalized financial advice.
