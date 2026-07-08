# Weekly Momentum Rotation

This strategy sits between the conservative monthly rotation and the fast intraday scan.
It is designed for a small account that can tolerate a bit more trading, but not
continuous churn.

The model uses:

- trailing return over a short lookback
- positive-return consistency
- realized volatility
- drawdown
- average volume
- a market filter on `SPY` to stay in cash when the broad market is weak

Trading behavior:

- rebalance weekly
- keep the current holding if its score remains close to the top-ranked candidate
- move to cash when no candidate clears the score threshold or the market filter is off

Default parameters in code:

- lookback: 20 bars
- volatility window: 10 bars
- volume window: 10 bars
- volatility cap: 30% annualized
- minimum trailing return: 0%
- switch score margin: 0.02
- market filter window: 50 bars

CLI examples:

```bash
ibkr-bot scan --strategy weekly_momentum_rotation
ibkr-bot backtest --strategy weekly_momentum_rotation --duration '1 Y' --capital 3000
ibkr-bot backtest --strategy weekly_momentum_rotation --profile weekly
```

The strategy is not meant to be a high-frequency system. It is a medium-turnover
rotation model with a stronger momentum tilt than `quality_low_vol_rotation`.
