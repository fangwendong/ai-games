# Volatility-Managed Trend Strategy

This strategy is the conservative default for `ibkr-bot`.

## Goal

Keep the bot usable for a small account with low risk tolerance:

- long-only
- low turnover
- avoid trading when recent volatility is elevated
- keep the logic simple enough to audit by hand

## Rule

Use two signals on daily bars:

1. A long trend filter, based on a slow moving average.
2. A recent volatility cap, based on annualized realized volatility.

Behavior:

- Buy 1 share when price is above the trend filter and realized volatility is below the cap.
- Hold the position when the signal remains positive.
- Sell the full long position when price falls below the trend filter or volatility breaks above the cap.
- Stay in cash otherwise.

## Parameters

Default values in code:

- trend window: 60 bars
- volatility window: 20 bars
- volatility cap: 20% annualized
- quantity: 1 share

These values are intentionally conservative. The point is not to maximize return. The point is to keep exposure small and easy to reason about.

## Failure Modes

This strategy still has normal equity-market risks:

- gap risk after market-close news
- long drawdowns during sustained downtrends
- false positives in choppy markets

It is not a hedge fund strategy and it is not market neutral.

## CLI

Run the default strategy:

```bash
ibkr-bot trade-once --symbol SPY
```

Switch back to the moving-average demo:

```bash
ibkr-bot trade-once --symbol SPY --strategy moving_average_cross
```
