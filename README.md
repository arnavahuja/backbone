# Backbone

A local strategy research and backtesting platform. Pull data from Yahoo, WRDS or your own
files, build a run in the browser from plugins (strategy, portfolio constructor, overlays,
costs), run it on a vectorized or event-driven engine, and compare any number of runs in
tables and charts. Everything runs on your machine and binds to `127.0.0.1`.

Adding a strategy, data source, overlay, metric, chart, cost model or portfolio constructor
means writing one file in `user_plugins/`. It shows up in the UI with an auto-generated
parameter form.

## Quick start

Requirements: the `backbone` conda environment (Python 3.12+), Node 20+ and pnpm.

```bash
conda activate backbone
make dev          # pip install -e ".[dev]" and pnpm install
cp .env.example .env
make run          # API on http://127.0.0.1:8000, UI on http://127.0.0.1:5173
```

Try it offline: in the Strategy Lab choose source **synthetic**, instruments `AAA, BBB, CCC`,
benchmark `MKT`, and press **Run backtest**. With network access, the default Yahoo config
(SPY, TLT, GLD) works as well.

From the command line:

```bash
backbone run configs/examples/sma_synthetic.yaml
backbone data pull SPY QQQ --start 2015-01-01 --end 2024-12-31
backbone data import my_prices.csv
backbone new strategy my_strategy
backbone preset import configs/examples/benchmarks/*.yaml
backbone plugins
```

## What's inside

| Area | Highlights |
|---|---|
| Data | Yahoo, WRDS (CRSP with delisting returns, share-code universes, CRSP indices and Treasuries, Compustat by availability date, Fama-French daily/monthly, S&P 500 point-in-time membership, TAQ bars, OptionMetrics), local CSV/Parquet/Excel/Feather import with a mapping wizard, synthetic data. Versioned Parquet cache, DuckDB catalog, data quality reports |
| Engines | Vectorized (closed-form drift, lag >= 1 enforced, open/close execution, rebalance schedules) and event-driven (market/limit/stop/stop-limit, TIF, partial fills, latency, fill models). Parity within 1e-10 at zero cost |
| Pipeline | 19 strategies (incl. generic trailing-return, field and composite signals), 8 portfolio constructors (value-weighted, capped deciles), 30 overlays (sizing, exits, limits, drawdown control, hedging, option hedges, regime filters), before/after reporting per overlay |
| Analytics | 11 metric groups (incl. deflated Sharpe, PSR, bootstrap CIs, factor alpha, option hedge cost), 41 charts, HTML tearsheet, CSV/Parquet export, comparison report (CSV + PNG), risk-free series, date-range brushing that recomputes metrics |
| Research | Grid/random sweeps, walk-forward, Monte Carlo, cost/delay/capacity sensitivity, regime analysis, PBO (CSCV), locked test period |
| Futures & options | Continuous futures with pluggable roll rules and back-adjustment, roll costs, intraday and multi-frequency runs, Black-Scholes pricing, rolling option instruments (chain-priced or model-priced and flagged) |

## Layout

```
backend/backbone/   core, data, engine, strategies, portfolio, analytics, services, api, cli
frontend/           React + Vite + TypeScript UI (generated API client in src/api)
tests/              unit, integration, golden, fixtures (no network needed)
user_plugins/       your plugins (auto-discovered, hot-reloaded in dev mode)
templates/          one copyable example per plugin kind
docs/               how-to guides, ADRs, phase log, performance notes
configs/examples/   example run configs
```

Layering (`core <- data <- engine <- analytics <- services <- api`, plugins depend only on
`core`) is enforced by import-linter.

## Development

```bash
make check        # ruff, mypy --strict, import-linter, pytest, eslint, prettier, tsc, vitest, build
make e2e          # Playwright smoke tests (starts API and UI)
make openapi      # regenerate the OpenAPI schema and the TypeScript client
pytest -m live    # opt-in tests against Yahoo / WRDS
```

## WRDS

Set `WRDS_USERNAME` in `.env`. The password is read from `~/.pgpass` by the `wrds` library;
create it once with `python -c "import wrds; wrds.Connection()"`. Settings -> Test
connection checks it. Nothing secret is stored by Backbone.

## Documentation

- [How-to guides](docs/howto/README.md): add each kind of plugin
- [Architecture decisions](docs/adr/)
- [Build phase log](docs/phases.md): what was built, deferred and known limitations
- [Performance](docs/performance.md)
