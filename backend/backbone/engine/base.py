"""Engine interface shared by the vectorized and event-driven engines."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

import numpy as np

from backbone.core import columns as C
from backbone.core.errors import EngineError
from backbone.core.interfaces import Strategy
from backbone.core.results import BacktestResult
from backbone.core.run_config import BacktestConfig
from backbone.core.types import FloatArray, MarketData, TargetFrame
from backbone.engine.pipeline import Pipeline

__all__ = ["BacktestConfig", "BacktestResult", "Engine", "RunOptions", "align_targets"]

ProgressFn = Callable[[float, str], None]


@dataclass(frozen=True)
class RunOptions:
    """Run-level inputs prepared by the runner.

    Attributes:
        periods_per_year: Annualization factor for the data frequency and calendar.
        benchmark_id: Benchmark instrument id present in ``data`` (or ``None``).
        strategy_instruments: Instruments the strategy may see and trade (default: all).
        membership: Point-in-time universe mask ``(T, N)`` aligned to ``data`` (1 = member).
        progress: Callback ``(fraction, message)``.
        cancelled: Returns True when the run should stop.
    """

    periods_per_year: float
    benchmark_id: str | None = None
    strategy_instruments: tuple[str, ...] | None = None
    membership: FloatArray | None = None
    progress: ProgressFn | None = None
    cancelled: Callable[[], bool] | None = None
    extras: dict[str, object] = field(default_factory=dict)

    def report(self, fraction: float, message: str) -> None:
        """Report progress if a callback is set."""
        if self.progress is not None:
            self.progress(fraction, message)


class Engine(Protocol):
    """A backtest engine."""

    name: str

    def run(
        self,
        config: BacktestConfig,
        data: MarketData,
        strategy: Strategy,
        pipeline: Pipeline,
        options: RunOptions,
    ) -> BacktestResult:
        """Run a backtest and return the result."""
        ...


def align_targets(targets: TargetFrame, data: MarketData) -> TargetFrame:
    """Align strategy output to the data grid (all instruments, all bars).

    Raises:
        EngineError: If the strategy returned timestamps not in the data.
    """
    grid = data.timestamps
    if len(targets.timestamps) and not np.isin(targets.timestamps, grid).all():
        raise EngineError("Strategy returned timestamps that are not in the data")
    unknown = set(targets.instruments) - set(data.instruments)
    if unknown:
        raise EngineError(
            "Targets reference instruments not in the data", details={"unknown": sorted(unknown)}
        )
    return targets.reindex(grid, data.instruments)


def apply_membership(targets: TargetFrame, membership: FloatArray | None) -> TargetFrame:
    """Set targets to ``NaN`` where an instrument is not in the universe."""
    if membership is None:
        return targets
    values = np.where(membership > 0, targets.values, np.nan)
    return targets.replace(values=values)


def close_panel(data: MarketData) -> FloatArray:
    """Close prices panel."""
    return data.panel(C.CLOSE)
