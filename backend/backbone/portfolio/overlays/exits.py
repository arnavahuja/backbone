"""Exit overlays: stop loss, trailing stop, take profit, time-based exit.

A *position run* is a maximal stretch of bars where an instrument's target keeps the same
non-zero sign. The entry price is the close on the run's first decision bar. Once an exit
triggers, the target stays at zero until the strategy's signal changes (a new run starts).
All operations are vectorized with grouped cumulative sums over run ids.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from pydantic import Field

from backbone.core import columns as C
from backbone.core.interfaces import Overlay, OverlayContext
from backbone.core.params import OverlayParams
from backbone.core.registry import register
from backbone.core.types import BoolArray, FloatArray, IntArray, TargetFrame


@dataclass(frozen=True)
class Runs:
    """Position-run bookkeeping for a ``(T, N)`` target panel."""

    sign: FloatArray
    start_idx: IntArray
    run_id: IntArray
    bars_in_run: IntArray


def position_runs(values: FloatArray) -> Runs:
    """Identify runs of constant non-zero sign per column."""
    sign = np.sign(np.nan_to_num(values, nan=0.0))
    n_t = len(sign)
    start = np.ones_like(sign, dtype=bool)
    if n_t > 1:
        start[1:] = sign[1:] != sign[:-1]
    rows = np.arange(n_t)[:, None]
    start_idx = np.maximum.accumulate(np.where(start, rows, 0), axis=0)
    run_id = np.cumsum(start, axis=0)
    return Runs(sign, start_idx, run_id, rows - start_idx)


def first_hit_onwards(hit: BoolArray, runs: Runs) -> BoolArray:
    """True from the first hit within each run to the run's end."""
    cum = np.cumsum(hit, axis=0)
    cols = np.arange(hit.shape[1])[None, :]
    before_start = cum[runs.start_idx, cols] - hit[runs.start_idx, cols]
    return (cum - before_start) > 0


def grouped_cummax(values: FloatArray, runs: Runs) -> FloatArray:
    """Running maximum that resets at each run start (per column)."""
    finite = np.where(np.isfinite(values), values, -np.inf)
    span = np.nanmax(np.abs(np.where(np.isfinite(values), values, 0.0))) * 4.0 + 1.0
    shifted = finite + runs.run_id * span
    return np.maximum.accumulate(shifted, axis=0) - runs.run_id * span


def apply_exit(targets: TargetFrame, exit_mask: BoolArray) -> TargetFrame:
    """Zero targets where the exit mask is set."""
    return targets.replace(values=np.where(exit_mask, 0.0, targets.values))


def _prices(targets: TargetFrame, ctx: OverlayContext) -> FloatArray:
    """Close prices on the targets' grid."""
    return ctx.data.aligned_panel(C.CLOSE, targets.timestamps, targets.instruments)


def _since_entry(targets: TargetFrame, ctx: OverlayContext) -> tuple[Runs, FloatArray]:
    runs = position_runs(targets.values)
    close = _prices(targets, ctx)
    cols = np.arange(close.shape[1])[None, :]
    entry = close[runs.start_idx, cols]
    with np.errstate(divide="ignore", invalid="ignore"):
        ret = runs.sign * (close / entry - 1.0)
    return runs, np.nan_to_num(ret, nan=0.0)


class StopParams(OverlayParams):
    """Stop distance."""

    stop_pct: float = Field(0.10, gt=0, lt=1, description="Loss from entry that triggers exit")


@register("overlay", name="stop_loss", version="1.0.0", tags=["exits"])
class StopLoss(Overlay):
    """Exit a position when its loss from the entry price exceeds a threshold."""

    Params = StopParams
    params: StopParams

    def apply(self, targets: TargetFrame, ctx: OverlayContext) -> TargetFrame:
        """Zero the rest of the run after the stop is hit."""
        runs, ret = _since_entry(targets, ctx)
        hit = (ret <= -self.params.stop_pct) & (runs.sign != 0)
        mask = first_hit_onwards(hit, runs)
        ctx.notes.append(f"{int((hit & ~np.roll(hit, 1, axis=0)).sum())} stop triggers")
        return apply_exit(targets, mask)


class TrailingParams(OverlayParams):
    """Trailing stop distance."""

    trail_pct: float = Field(0.10, gt=0, lt=1, description="Retracement from the best price")


@register("overlay", name="trailing_stop", version="1.0.0", tags=["exits"])
class TrailingStop(Overlay):
    """Exit when the position gives back ``trail_pct`` from its best level since entry."""

    Params = TrailingParams
    params: TrailingParams

    def apply(self, targets: TargetFrame, ctx: OverlayContext) -> TargetFrame:
        """Track the best sign-adjusted log price within each run."""
        runs = position_runs(targets.values)
        close = _prices(targets, ctx)
        with np.errstate(divide="ignore", invalid="ignore"):
            level = runs.sign * np.log(close)
        best = grouped_cummax(level, runs)
        hit = (level - best <= np.log(1.0 - self.params.trail_pct)) & (runs.sign != 0)
        return apply_exit(targets, first_hit_onwards(hit, runs))


class TakeProfitParams(OverlayParams):
    """Profit target."""

    target_pct: float = Field(0.20, gt=0, le=10, description="Gain from entry that exits")


@register("overlay", name="take_profit", version="1.0.0", tags=["exits"])
class TakeProfit(Overlay):
    """Exit a position once its gain from entry reaches a target."""

    Params = TakeProfitParams
    params: TakeProfitParams

    def apply(self, targets: TargetFrame, ctx: OverlayContext) -> TargetFrame:
        """Zero the rest of the run after the target is reached."""
        runs, ret = _since_entry(targets, ctx)
        hit = (ret >= self.params.target_pct) & (runs.sign != 0)
        return apply_exit(targets, first_hit_onwards(hit, runs))


class TimeExitParams(OverlayParams):
    """Maximum holding period."""

    max_bars: int = Field(20, ge=1, le=10_000, description="Bars after entry to exit")


@register("overlay", name="time_exit", version="1.0.0", tags=["exits"])
class TimeExit(Overlay):
    """Exit a position after a fixed number of bars."""

    Params = TimeExitParams
    params: TimeExitParams

    def apply(self, targets: TargetFrame, ctx: OverlayContext) -> TargetFrame:
        """Zero targets once a run is older than ``max_bars``."""
        runs = position_runs(targets.values)
        mask = (runs.bars_in_run >= self.params.max_bars) & (runs.sign != 0)
        return apply_exit(targets, mask)
