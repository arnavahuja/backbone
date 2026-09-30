# ADR 0005: Vectorized engine design

Status: accepted

## Context
The vectorized engine must support rebalance schedules with position drift, execution lag,
open or close execution, proportional and per-unit costs, borrow and cash interest, without
Python loops over bars.

## Decision
- **Timing.** `lag_bars >= 1` (enforced by the config model). A target decided with data up to
  the close of bar `t` trades at the close (or open) of bar `t + lag`. Same-bar execution is
  impossible by construction.
- **Rebalancing.** Default rule `on_change`: trade only when the (lagged) target differs from
  the previous one, so constant targets mean buy-and-hold with drift. `every_bar` gives a
  constant mix; `weekly`/`monthly`/`quarterly`/`every_n` are calendar schedules.
- **Drift in closed form.** Between rebalances units are constant, so a position's value
  relative to post-trade equity is `E_i(s) * I_i(t) / I_i(s)` with `I` the cumulative
  total-return index. Cash (`1 - sum E`, including short proceeds, negative when levered)
  grows at the cash rate. All bars are computed with fancy indexing
  (`engine/simulation.py`).
- **Open execution** interleaves each bar into an overnight and an intraday half-step and
  rebalances at the open half-steps; the same kernel is reused.
- **Costs** are cost/slippage plugins returning `(T, N)` fractions of equity. Per-unit models
  need equity, which depends on costs, so costs are computed against the gross path and then
  recomputed once against the resulting net path (two passes). The residual error is second
  order in the cost rate (e.g. under 0.01 bp of equity for 5 bp costs).
- **Return basis.** A `ret` field (CRSP total return including delisting returns) wins; else
  close plus explicit dividends (and split ratios for raw prices); else adjusted closes. The
  basis is recorded in the result metadata.
- **Missing prices.** An instrument without a price at the trade bar cannot be traded; its
  target is forced to zero. A `NaN` return while held contributes zero.
- **Trades.** Round trips are maximal runs of same-sign end-of-bar weights. Trade PnL sums
  `w[t-1] * r[t] * V[t-1]`, so trade PnLs add up to gross PnL exactly (tested).

## Consequences
Fast (milliseconds for thousands of bars x hundreds of instruments) and exact for the drift
model. Intrabar path dependence (stops, limits) belongs to the event engine.
