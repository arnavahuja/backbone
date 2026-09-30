# ADR 0007: Point-in-time data, universes, fundamentals and factors

Status: accepted

## Decision
- **Universes.** A universe provider may name a source-side universe (`request_universe`,
  e.g. `sp500`). The source then returns every instrument that was a member at any time in the
  range (including later delistings) plus a `universe_member` field; membership masks targets
  point-in-time.
- **Fundamentals** are separate datasets stamped at their availability date (Compustat:
  `datadate + 180 days` by default, configurable). `DataSpec.extra_datasets` lists
  `source:dataset` entries that are backward as-of joined per instrument onto the price grid;
  `book_to_market` is derived when book equity and market cap exist.
- **CRSP** returns (`ret`, with delisting returns merged) drive the engines' return basis, so
  delisted stocks lose value correctly instead of disappearing.
- **Factors** (`BacktestConfig.factors`, e.g. `wrds:ff_factors`) are fetched through the same
  cache, stored with the run and used by factor metrics and charts. A synthetic factor dataset
  makes the flow testable offline.

## Consequences
The WRDS source is tested against a fake WRDS backend (SQL-by-table fixtures); a `live`-marked
test hits the real service when credentials exist.
