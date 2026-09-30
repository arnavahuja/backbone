# ADR 0002: Dependency log

Status: living document. One line of justification per dependency.

## Python (runtime)

| Package | Why |
|---|---|
| numpy | Array math for engines and metrics |
| polars | Data-layer dataframes (the single dataframe convention, see ADR 0004) |
| pyarrow | Parquet I/O and polars/pandas interchange |
| pandas | Only at library boundaries (yfinance, exchange_calendars, statsmodels) |
| duckdb | SQL over Parquet for the dataset catalog |
| pydantic, pydantic-settings | Params/config models, JSON Schema for forms, `.env` settings |
| structlog | Structured logging with bound run ids |
| exchange_calendars | Trading sessions and holidays, annualization factors |
| yfinance | Yahoo Finance data source |
| fastapi, uvicorn, python-multipart, websockets | Local API, uploads, job progress streaming |
| typer | CLI |
| PyYAML | Config and import-mapping files |
| scipy | Statistics (normal/t distributions, optimization for MVO/risk parity) |
| statsmodels | OLS with t-stats for factor regressions, cointegration for pairs |
| openpyxl | Excel import |
| watchfiles | Hot reload of `user_plugins/` |
| wrds (optional extra) | WRDS/CRSP/Compustat access |

## Python (dev)

pytest, pytest-cov, hypothesis (property tests), mypy, ruff, import-linter (layering),
empyrical-reloaded (reference implementation to cross-check metrics),
pre-commit, httpx (FastAPI TestClient), pandas-stubs, types-PyYAML.
