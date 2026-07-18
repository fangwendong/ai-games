# Shared Historical Market Data

All agents and worktrees on this host must use the canonical cache for the
required market-data source:

```text
SMART: /home/fwd/data/ibkr-quant-bot/historical/5-min-rth
SMART 1m: /home/fwd/data/ibkr-quant-bot/historical/1-min-rth
SMART 30s: /home/fwd/data/ibkr-quant-bot/historical/30-sec-rth
ARCA:  /home/fwd/data/ibkr-quant-bot/historical/5-min-rth-arca
```

`/home` is mounted from the data disk (`/dev/vdb1`), not the system disk. Do
not create a second multi-year cache under an individual worktree. Pass the
canonical path explicitly with `--data-dir` or create a local symlink that
points to it.

The directories are generated state and must never be committed to Git. Never
write SMART and ARCA bars into the same cache directory. Do not mix bar sizes
inside a cache directory either; one directory should contain one source/bar-size
combination only.

## Source Parity Rule

Historical backtests and live signal generation must use the same bar source.
A live session uses exactly one bar source for QQQ, SOXL, and SOXS: all SMART
or all ARCA. Do not mix symbols or switch bar sources after the session source
has been pinned. Live bid/ask/last used for execution always remains SMART; an
ARCA bar fallback never changes the quote source or order route.

Each cache root contains `market-data-source.json`. `refresh-history` records
the selected source, refuses to merge another source into that directory, and
`backtest-momentum --reuse-data` fails closed when `--market-data-exchange`
does not match the cache metadata. A cache without this metadata is treated as
source-unknown and is not valid for a frozen-strategy comparison.

A hybrid validation uses ARCA bars for indicators and historical SMART prices
as the fill proxy. This reproduces the signal/execution split but remains an
approximation until timestamped SMART quote snapshots are archived. Report
that limitation with the result.

## Cache Layout

The cache stores one JSON file per symbol and US trading session:

```text
5-min-rth/
  2026-07-13/
    NVDA__5_mins.json
    QQQ__5_mins.json
  2026-07-14/
    NVDA__5_mins.json
    QQQ__5_mins.json
1-min-rth/
  2026-07-13/
    NVDA__1_min.json
    QQQ__1_min.json
30-sec-rth/
  2026-07-13/
    NVDA__30_secs.json
    QQQ__30_secs.json
```

Files are written by `save_bars_by_day`. Repeated downloads merge and
de-duplicate bars by timestamp, so a bounded recent refresh is safe.

## Safety Setup

Historical downloads require an authenticated IB Gateway but never require
order access. Load the existing local connection settings, then force the
safety switches after loading them:

```bash
cd /home/fwd/work/ai-games-wt-codex-7/apps/ibkr-quant-bot
set -a
source /path/to/local/.env
set +a

export IBKR_READONLY=true
export IBKR_DRY_RUN=true
export IBKR_ALLOW_LIVE_TRADING=false
export IBKR_CLIENT_ID=71
export PYTHONPATH=src

export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1
```

Never put the `.env` path, credentials, account identifiers, or raw account
output in Git or task reports.

## Download Multi-Year History

Use a single worker. Five-minute history is paged backward in one-week chunks,
one-minute history is paged in tighter chunks, sub-minute history is paged in
day-sized chunks, and every completed page is saved immediately.

```bash
nice -n 10 taskset -c 0 \
  python -m ibkr_quant_bot.cli refresh-history \
  --symbols NVDA AMD INTC AAPL AMZN META MSFT PLTR TSLA AVGO \
            BAC C WFC JPM NU SOFI AAL PATH ORCL LCID OPEN MRVL \
            CRWD NBIS MARA QQQ \
  --duration "2 Y" \
  --bar-size "5 mins" \
  --recent-sessions 2 \
  --market-data-exchange SMART \
  --data-dir /home/fwd/data/ibkr-quant-bot/historical/5-min-rth
```

For an ARCA-only validation, change both the exchange and directory:

```bash
nice -n 10 taskset -c 0 \
  python -m ibkr_quant_bot.cli refresh-history \
  --symbols SOXL SOXS QQQ \
  --duration "2 M" \
  --bar-size "5 mins" \
  --recent-sessions 2 \
  --market-data-exchange ARCA \
  --data-dir /home/fwd/data/ibkr-quant-bot/historical/5-min-rth-arca
```

For lower-latency evaluation caches, use the matching minute-based directory
and bar size:

```bash
nice -n 10 taskset -c 0 \
  python -m ibkr_quant_bot.cli refresh-history \
  --symbols SOXL SOXS QQQ \
  --duration "180 D" \
  --bar-size "1 min" \
  --recent-sessions 2 \
  --market-data-exchange SMART \
  --data-dir /home/fwd/data/ibkr-quant-bot/historical/1-min-rth

nice -n 10 taskset -c 0 \
  python -m ibkr_quant_bot.cli refresh-history \
  --symbols SOXL SOXS QQQ \
  --duration "60 D" \
  --bar-size "30 secs" \
  --recent-sessions 2 \
  --market-data-exchange SMART \
  --data-dir /home/fwd/data/ibkr-quant-bot/historical/30-sec-rth
```

The tracked wrapper is preferred for unattended work because it processes one
symbol at a time, retries bounded request timeouts, preserves and safely merges
pages already saved in the shared cache, and runs the offline audit at the end.
A retry can re-request part of the requested window, but it does not duplicate
cached bars:

```bash
scripts/refresh-shared-history --duration "2 Y" \
  NVDA AMD INTC AAPL AMZN META MSFT PLTR TSLA AVGO \
  BAC C WFC JPM NU SOFI AAL PATH ORCL LCID OPEN MRVL CRWD NBIS MARA QQQ
```

The fetch is intentionally low priority and each worker is bound to one CPU
core. Default to one worker. For a large one-time bootstrap, cap concurrency at
`min(2, nproc)`, give each worker a different `IBKR_CLIENT_ID`, and split the
symbol list so workers never request the same symbol. IBKR can still throttle
historical requests; if throttling or Gateway instability appears, return to
one worker. Never let historical-download concurrency exceed the machine's CPU

If a long download is interrupted, already written days remain valid. Restart
with only the unfinished symbols. Re-running a symbol is safe but will request
its window again before the cache de-duplicates it.

Newly listed stocks can legitimately have less than two years of data. Record
their first available session instead of treating pre-listing dates as gaps.

## Read Cached Bars

Application and research code should use the shared cache reader:

```python
from ibkr_quant_bot.historical_cache import load_bars

bars = load_bars(
    "/home/fwd/data/ibkr-quant-bot/historical/5-min-rth",
    "NVDA",
    "5 mins",
)
```

The reader loads all matching daily files, sorts timestamps, and de-duplicates
overlapping refreshes. A bounded read can also pass `duration` and `end_time`.

CLI backtests must pass the same canonical directory:

```bash
PYTHONPATH=src python -m ibkr_quant_bot.orb_research \
  --config config/orb-stocks-in-play-v1.json \
  --data-dir /home/fwd/data/ibkr-quant-bot/historical/5-min-rth \
  --chronological-split
```

For the frozen v2 CLI, make the source explicit:

```bash
PYTHONPATH=src python -m ibkr_quant_bot.cli backtest-momentum \
  --profile rotation-hysteresis-v2 \
  --duration "2 M" \
  --reuse-data \
  --bar-size "5 mins" \
  --market-data-exchange ARCA \
  --data-dir /home/fwd/data/ibkr-quant-bot/historical/5-min-rth-arca
```

## Confirm Completeness

Run the offline audit after a download and before every backtest:

```bash
PYTHONPATH=src python -m ibkr_quant_bot.history_audit \
  --symbols NVDA AMD INTC AAPL AMZN META MSFT PLTR TSLA AVGO \
            BAC C WFC JPM NU SOFI AAL PATH ORCL LCID OPEN MRVL \
            CRWD NBIS MARA QQQ \
  --bar-size "5 mins" \
  --recent-sessions 2 \
  --data-dir /home/fwd/data/ibkr-quant-bot/historical/5-min-rth
```

The audit exits with code zero only when:

- every requested active symbol reaches the same latest cached session
- the latest requested sessions exist for every symbol
- each internal regular session has the expected bar count for the selected bar
  size, or the matching early-close count for that bar size
- timestamps inside a session remain evenly spaced by the requested bar size
- full sessions run from 09:30 through 15:55 America/New_York, and standard
  early-close sessions run from 09:30 through 12:55
- there are no missing trading sessions between a symbol's first and latest
  cached session

Because a two-year request can start during the first boundary session, one
partial first session is reported separately and does not fail the audit. Any
partial session inside the history does fail it.

`refresh-history` also checks the newest cached sessions against IBKR's
historical liquid-hours schedule. The schedule check and offline audit are
complementary: the former establishes what IBKR considers a completed session;
the latter checks the whole local cache.

Do not declare a backtest complete when the audit exits nonzero. Refresh the
affected symbol/date range first and rerun the audit.

## Add the Latest Sessions

For the normal daily update, refresh a small overlapping window. Ten calendar
days covers weekends, a holiday, and recent corrections without downloading
the full history again:

```bash
nice -n 10 taskset -c 0 \
  python -m ibkr_quant_bot.cli refresh-history \
  --symbols NVDA AMD INTC AAPL AMZN META MSFT PLTR TSLA AVGO \
            BAC C WFC JPM NU SOFI AAL PATH ORCL LCID OPEN MRVL \
            CRWD NBIS MARA QQQ \
  --duration "10 D" \
  --bar-size "5 mins" \
  --recent-sessions 2 \
  --market-data-exchange SMART \
  --data-dir /home/fwd/data/ibkr-quant-bot/historical/5-min-rth
```

For 1-minute and 30-second caches, point the refresh at the matching public
directory and reuse the same symbol list:

```bash
nice -n 10 taskset -c 0 \
  python -m ibkr_quant_bot.cli refresh-history \
  --symbols SOXL SOXS QQQ \
  --duration "10 D" \
  --bar-size "1 min" \
  --recent-sessions 2 \
  --market-data-exchange SMART \
  --data-dir /home/fwd/data/ibkr-quant-bot/historical/1-min-rth

nice -n 10 taskset -c 0 \
  python -m ibkr_quant_bot.cli refresh-history \
  --symbols SOXL SOXS QQQ \
  --duration "10 D" \
  --bar-size "30 secs" \
  --recent-sessions 2 \
  --market-data-exchange SMART \
  --data-dir /home/fwd/data/ibkr-quant-bot/historical/30-sec-rth
```

The equivalent retrying wrapper command is:

```bash
scripts/refresh-shared-history --duration "10 D" \
  NVDA AMD INTC AAPL AMZN META MSFT PLTR TSLA AVGO \
  BAC C WFC JPM NU SOFI AAL PATH ORCL LCID OPEN MRVL CRWD NBIS MARA QQQ
```

Run this only after the latest regular session is complete. The command asks
IBKR for its historical session schedule and fails closed when recent cached
bars do not match that schedule. A market holiday therefore does not create a
fake missing-session alert.

After the refresh:

1. Check that `refresh-history` exits with code zero.
2. Confirm its `latest_completed_session` and recent per-symbol bar counts.
3. Run `ibkr_quant_bot.history_audit` for the symbols used by the backtest.
4. Only then start the backtest.

## Worktree Compatibility

Agents should reference the absolute canonical path. If a legacy command
requires a worktree-relative cache, create a symlink rather than copying data:

```bash
mkdir -p .ibkr_bot_data
ln -s /home/fwd/data/ibkr-quant-bot/historical/5-min-rth \
  .ibkr_bot_data/historical
```

Before creating the link, verify that `.ibkr_bot_data/historical` does not
already contain unique data. Merge unique files into the canonical directory
first. Do not replace the live checkout's cache while a live or refresh task is
running.
