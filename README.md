# Aeurils Bot

Automated Telegram market-analysis bot for cryptocurrency and stocks.

The project intentionally uses a single branch: `main`.

## Current architecture
- Live crypto market data
- Stock market data
- Technical indicators
- Crypto whale-flow analysis
- Risk-defined LONG / SHORT / WAIT setups
- Telegram commands and scheduled reports
- Trade-performance journal

Signals are informational market analysis, not guaranteed returns or personalized financial advice.


## AURELIS Performance Audit v2

The paper-trading system includes a read-only performance audit that does not
change signal generation, thresholds, sizing, or execution. It tracks:
- deterministic 5m expiry-boundary resolution
- net P&L after the configured paper fee assumption
- risk multiples (R), MFE/MAE in R, expectancy, profit factor, and max drawdown
- LONG/SHORT, regime, score-band, symbol, and signal-source segmentation
- legacy wall-clock expiry rows separately from strict 5m-boundary results

The scheduled paper-trade workflow runs the unit tests and generates
`data/aurelis_performance_audit_v2.json`.

Paper trading remains simulation only; audit results do not imply future returns.
