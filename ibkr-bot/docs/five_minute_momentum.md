# Five-Minute Momentum Scan

This strategy is a 5-minute intraday scan for liquid ETFs.

The goal is not millisecond trading. It is a simple, low-complexity intraday filter that can be checked repeatedly during the session without relying on deep order-book logic or rapid cancel/replace loops.

## Rule

At each scan, rank the current symbol by:

- fast versus slow 5-minute moving averages
- short-term momentum over the most recent bars
- relative volume versus the prior bars in the session

It issues a buy signal when momentum and volume confirm the trend, and an exit signal when the short-term structure breaks while a position is held.

## Parameters

Default values in code:

- bar size: 5 mins
- duration: 2 D
- fast window: 3 bars
- slow window: 8 bars
- volume window: 4 bars
- minimum momentum: 0.0%
- minimum volume multiple: 1.0x

## CLI

Scan the signal:

```bash
ibkr-bot scan --strategy five_minute_momentum
```

Override the bar size or lookback if you want to inspect a different slice:

```bash
ibkr-bot scan --strategy five_minute_momentum --duration '3 D' --bar-size '5 mins'
```

## Notes

This is a validation path, not a production HFT engine.

The scan prints a ranked list of the strongest intraday candidates with their momentum, volume multiple, and signal direction.

Use it to check whether the signal quality is stable before wiring it into any execution path.
