# AURELIS FV1 — prospective paper validation

FV1 is a separate, paper-only cohort. It does not change the strategy, authorize orders, or enable live trading.

## Cohort boundary

The first `trade_bot.paper_persistence restore` after rollout creates the immutable freeze timestamp and strategy fingerprint. Only new paper trades created after that timestamp, with the matching fingerprint and cohort ID, are admitted. Existing ledger rows are legacy data and are excluded. If one of the fingerprinted strategy files changes, new FV1 intake stops with an error; create a separately versioned cohort rather than silently mixing strategies.

The scheduler registers signals after creating their paper-trade rows. The monitor synchronizes resolved outcomes from `paper_trades`. FV1 metadata, cohort rows, and watchlist history are exported into the same persistent JSON ledger so scheduled GitHub runners can restore them.

## Validation metrics

The report uses FV1 cohort rows only:
- eligible signal count; scored TP/SL outcomes; expiries; win rate
- mean realized R converted using the fixed 0.25% risk-per-trade assumption; profit factor
- daily moving-block bootstrap confidence interval
- integrity checks against the frozen fingerprint and positive initial risk

FV1 now records a time-stamped portfolio-equity snapshot after each paper-monitor run. It sums each cohort trade's realised R and open-position unrealised R, so overlapping positions are marked together rather than applied as a sequential trade curve. The fixed 0.25% per-trade risk budget is applied to the cohort's starting equity index (100); this is a documented paper-equity simulation, not the user's live account balance, and does not model funding, slippage, fees, or margin. Maximum drawdown is measured from the snapshot equity high-water mark.

The monitor records critical events for invalid risk records, more than three concurrent FV1 positions, aggregate open risk above 1%, daily equity loss at or beyond 1%, and weekly equity loss at or beyond 3%. These events are persisted alongside the snapshots and included in the FV1 gate. The monitor does not alter signal generation or place orders. No snapshots means drawdown and risk-breach evidence remain `PENDING`; missing evidence never counts as a pass.

## Token Intelligence

The Token Intelligence candidate pool uses symbols represented in the persisted AURELIS paper-trade ledger (including legacy history for immediate coverage), with at least three trades and two scored outcomes. This retrospective ranking is strictly separate from FV1; legacy records never enter FV1 validation metrics. Each candidate must then pass current Binance spot checks:
- 24-hour quote volume at least USD 2 million
- bid/ask spread no greater than 0.35%
- at least 30 closed 4-hour candles for a seven-day trend and dailyized volatility snapshot

The shared selector returns up to 10 active symbols and five reserves. It does not fill slots artificially. The ranking is research/watchlist information, not an instruction to trade. If there is not enough history or Binance market data, slots remain empty. Watchlist changes and weekly refreshes are recorded in the persistent ledger.

## Reports and preview

Run locally after restoring the ledger:

```bash
python -m trade_bot.paper_persistence restore
python -m trade_bot.fv1_preview
```

The preview command prints the combined performance, FV1, and Token Intelligence report. It does **not** send Telegram messages. CI restores the committed ledger, generates the preview, and uploads it as the `aurelis-telegram-preview` artifact. The scheduled paper monitor also generates and archives a preview. The separate performance-report workflow restores the ledger before sending its scheduled Telegram report.

## Current status

FV1 begins only after this code is deployed and the first persistent restore creates the freeze metadata. The historical AURELIS audit is not FV1 evidence. The cohort still needs at least 200 prospective signals, 100 scored outcomes, and 30 calendar days, plus every validation gate. The risk monitor must accumulate snapshots during ordinary paper-monitor runs; a green CI run alone does not establish a 30-day validation result. Keep the PR paper-only.
