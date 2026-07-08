# Tech / Semiconductor Rotation

This strategy is a medium-turnover ETF rotation model for a small account.
It is designed for the trade-off between broad tech exposure and higher-beta
semiconductor exposure.

Universe:

- `QQQ`
- `XLK`
- `IYW`
- `SMH`
- `SOXX`

Core idea:

- rank the ETF universe by trailing return and consistency
- penalize volatility and drawdown
- use a broad-market filter on `SPY`
- stay in cash when no candidate clears the threshold

Default code parameters:

- lookback: 60 bars
- volatility window: 20 bars
- volume window: 20 bars
- annualized volatility cap: 35%
- switch score margin: 0.03
- market filter window: 50 bars

Suggested usage:

```bash
ibkr-bot scan --strategy tech_semiconductor_rotation
ibkr-bot backtest --strategy tech_semiconductor_rotation --duration '1 Y' --capital 3000 --profile weekly
```

Operational note:

- `QQQ` and `XLK` are the lower-risk core exposure
- `SMH` and `SOXX` are the higher-beta satellite exposure
- this is not a high-frequency strategy
- keep the semiconductor sleeve small if the account is tiny
