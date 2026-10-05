# Build factor portfolios and a comparison report

Everything here is configuration: datasets come from the Data page or are fetched by a run,
strategies and constructors are ordinary plugins, and the report works on any runs.
`configs/examples/benchmarks/` holds ready-made examples (market, 60/40, momentum, value,
profitability, reversal, a quality + momentum composite and a trend filter).

## Data (WRDS)

| Dataset | What it gives |
|---|---|
| `crsp_monthly` / `crsp_daily` | CRSP stock files, delisting returns merged into `ret`. A missing `dlret` on a performance delisting (codes 500, 520-584) is filled with -30% (NYSE/AMEX) or -55% (NASDAQ); both values are source parameters |
| universe `crsp_common` | Share codes and exchanges from `crsp.msenames` (default 10/11 and 1/2/3), point in time |
| `compustat_annual` | Fundamentals stamped `availability_lag_days` (default 180) after fiscal year end, plus Fama-French `book_equity` and `fiscal_year` |
| `crsp_index` | `CRSP_VW`, `CRSP_EW`, `SP500`, ... as tradable series |
| `crsp_treasury` | Constant-maturity Treasury returns (`B10RET`, `T30RET`, ...) |
| `ff_factors` | Fama-French 5 + momentum + `rf`, daily or monthly (pick the frequency) |

Derived fields when the inputs are present: `book_to_market`, `book_to_market_dec`
(book equity over the December market cap of the fiscal year, visible only from that
December on) and `gross_profitability`.

## Run settings

- **Universe** `market_cap_top_n`: top N by `market_cap` above a minimum price, optionally
  inside a source universe (`crsp_common`). Use adjustment `raw` so the price filter sees
  actual prices; returns still come from CRSP `ret`.
- **Strategies** (all emit signals): `trailing_return` (lookback, skip, direction: 12-2
  momentum is 11/1/high, short-term reversal 1/0/low), `field_signal` (any field, e.g.
  `book_to_market_dec` with `min_value: 0`), `composite_signal` (winsorized z-scores of any
  signal strategies, weighted). Multi-asset: `fixed_weights`, `trend_filter`.
- **Constructor** `quantile_long_short`: `weighting: value`, `max_leg_weight` (per-name cap
  within a leg), `gross: 2` for 100% long / 100% short.
- **Risk-free** (`risk_free: wrds:ff_factors:rf`): cash earns the series and Sharpe/Sortino
  use excess returns. A dollar-neutral portfolio's Sharpe and alpha are then those of its
  long-minus-short spread.
- **Splices** (`IEF=wrds:crsp_treasury:B10RET`): returns before the instrument's first price
  come from the proxy; the run shows a warning naming the splice.
- **Benchmark** from another source or dataset: `source:dataset:SYMBOL`, e.g.
  `wrds:crsp_index:CRSP_VW`. Monthly bars from different sources are matched by month.

## Report

Compare page -> **Report export**: pick runs, edit the sub-periods and windows (one
`label, start, end` per line), cost levels and vol scaling, then **Download report**. The
zip has `returns`, `metrics` (gross and net), `regressions` (CAPM, FF5+MOM),
`correlations`, `factor_correlations`, `subperiods`, `crisis_table`, `annual_returns`,
`cost_sensitivity`, `holdings_count`, `cost_reconciliation` and six PNG charts. Same thing
over HTTP: `POST /api/v1/compare/report`.

## From the command line

```bash
backbone preset import configs/examples/benchmarks/*.yaml   # load them in the Lab
backbone run configs/examples/benchmarks/b3_momentum.yaml
```

Note: the legacy CRSP stock files (`crsp.msf`, `crsp.dsf`) end in December 2024.
