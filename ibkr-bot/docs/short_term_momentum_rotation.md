# Short-Term Momentum Rotation

This strategy is a daily rotation model for liquid ETFs.

It is meant for faster-cycle trading than the monthly quality rotation model. The design goal is simple: keep exposure only when a symbol has strong recent relative strength, and step aside to cash when nothing is leading.

## Rule

At each rebalance point, rank the configured universe by a short-term momentum score:

- trailing return over the lookback window
- minimum average volume filter
- tie-breaks favor smoother, less drawdown-heavy candidates

Select the top-ranked symbol only if it clears the score threshold.

Trading behavior:

- buy the strongest symbol if it is not already held
- sell any current long positions that are not the selected symbol
- move to cash when nothing clears the threshold

## Parameters

Default values in code:

- lookback: 30 bars
- volatility window: 10 bars
- volume window: 20 bars
- minimum average volume: 1,000,000 shares
- quantity: 1 share

## CLI

Run a daily backtest:

```bash
ibkr-bot backtest --strategy short_term_momentum_rotation --duration '1 Y'
```

You can still override the default windows if you want to experiment:

```bash
ibkr-bot backtest --strategy short_term_momentum_rotation --duration '1 Y' --lookback 20 --volatility-window 10 --volume-window 20
```

## Notes

This is a relative-strength system, not a mean-reversion system.

For small accounts, the main advantage is simplicity: one long position at a time, explicit cash filter, and no leverage or short borrow dependency.
