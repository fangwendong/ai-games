# Quality + Low Volatility Rotation

This strategy is a conservative monthly rotation model for small accounts.

It does not require fundamentals or a separate market-data vendor. In this repository, "quality" is a practical proxy built from price behavior:

- positive trailing return
- smoother day-to-day path
- lower realized volatility
- smaller drawdown

The goal is not to reproduce an institutional factor portfolio exactly. The goal is to get a usable approximation that can run on the data already available in the bot.

## Rule

Each month, rank the configured universe by a composite score:

- trailing return over the lookback window
- fraction of positive daily returns
- annualized realized volatility
- maximum drawdown

Select the top-ranked symbol only if it clears the minimum score and the volatility cap.

Trading behavior:

- buy the top-ranked symbol if it is not already held
- sell any current long positions that are not the selected symbol
- move to cash if nothing clears the filters

## Parameters

Default values in code:

- lookback: 252 bars
- volatility window: 63 bars
- volatility cap: 20% annualized
- quantity: 1 share

These defaults are intentionally conservative.

## CLI

Scan the ranked universe:

```bash
ibkr-bot scan --strategy quality_low_vol_rotation
```

Rebalance into the top candidate:

```bash
ibkr-bot rebalance
```

## Notes

This is still an equity strategy. It can lose money during market-wide drawdowns and it can whipsaw in choppy tape.

The main point is lower turnover, lower exposure, and simpler execution than a short-term mean reversion or pair-trading system.
