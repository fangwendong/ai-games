# Quality + Low Volatility Rotation

This strategy is a conservative rotation model for small accounts.

It does not require fundamentals or a separate market-data vendor. In this repository, "quality" is a practical proxy built from price behavior:

- positive trailing return
- smoother day-to-day path
- lower realized volatility
- smaller drawdown

The goal is not to reproduce an institutional factor portfolio exactly. The goal is to get a usable approximation that can run on the data already available in the bot.

The strategy ranks a built-in liquid ETF catalog by default. You can override that catalog with `IBKR_ROTATION_SYMBOLS`, but you do not need to maintain a universe manually for the default path.

## Rule

At each rebalance point, rank the configured universe by a composite score:

- trailing return over the lookback window
- fraction of positive daily returns
- annualized realized volatility
- maximum drawdown
- average daily volume over the recent window

Select the top-ranked symbol only if it clears the minimum score and the volatility cap.
Symbols with insufficient average volume are discarded before ranking.
The low-turnover profile also requires positive trailing return and keeps the
current holding when its score is close enough to the top-ranked candidate.

Trading behavior:

- buy the top-ranked symbol if it is not already held
- sell any current long positions that are not the selected symbol
- move to cash if nothing clears the filters
- avoid switching when the current holding is still inside the configured score margin

## Parameters

Default values in code:

- lookback: 60 bars
- volatility window: 20 bars
- volume window: 20 bars
- volatility cap: 20% annualized
- minimum average volume: 1,000,000 shares
- minimum trailing return: disabled by default
- switch score margin: disabled by default
- quantity: 1 share

These defaults are intentionally conservative.

The `low_turnover` backtest profile is more suitable for small accounts:

- rebalance frequency: weekly
- lookback: 60 bars
- volatility window: 20 bars
- volume window: 20 bars
- volatility cap: 25% annualized
- minimum trailing return: 0%
- switch score margin: 0.03

## CLI

Scan the ranked universe:

```bash
ibkr-bot scan --strategy quality_low_vol_rotation
```

Rebalance into the top candidate:

```bash
ibkr-bot rebalance
```

Backtest with adjustable cadence:

```bash
ibkr-bot backtest --duration '3 Y' --profile monthly
ibkr-bot backtest --duration '3 Y' --profile daily
ibkr-bot backtest --duration '3 Y' --profile low_turnover
ibkr-bot backtest --duration '3 Y' --rebalance-frequency monthly
ibkr-bot backtest --duration '3 Y' --rebalance-frequency weekly --lookback 60 --volatility-window 20 --volume-window 20
ibkr-bot backtest --duration '3 Y' --rebalance-frequency daily --lookback 20 --volatility-window 10 --volume-window 10
ibkr-bot backtest --duration '3 Y' --profile low_turnover --switch-score-margin 0.05 --min-trailing-return 0.01
```

## Notes

This is still an equity strategy. It can lose money during market-wide drawdowns and it can whipsaw in choppy tape.

The main point is lower turnover, lower exposure, and simpler execution than a short-term mean reversion or pair-trading system.
