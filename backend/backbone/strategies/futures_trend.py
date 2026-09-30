"""Futures trend follower: EWMA crossovers scaled to a volatility target per contract."""

from __future__ import annotations

import warnings
from typing import ClassVar

import numpy as np
from pydantic import Field

from backbone.core import columns as C
from backbone.core.calendar import periods_per_year_for
from backbone.core.interfaces import (
    ASSET_FUTURE,
    ENGINE_EVENT,
    ENGINE_VECTORIZED,
    FREQ_DAILY,
    SUPPORTS_SHORT,
    Strategy,
)
from backbone.core.numeric import ewm_mean, pct_change, rolling_std
from backbone.core.params import StrategyParams
from backbone.core.registry import register
from backbone.core.types import MarketData, TargetFrame

FORECAST_CAP = 2.0


class FuturesTrendParams(StrategyParams):
    """Futures trend parameters."""

    fast_spans: list[int] = Field(
        default_factory=lambda: [16, 32, 64], description="Fast EWMA half-lives of each crossover"
    )
    slow_multiple: int = Field(4, ge=2, le=10, description="Slow half-life = fast x multiple")
    vol_window: int = Field(63, ge=10, le=504, description="Volatility window (bars)")
    target_vol: float = Field(0.15, gt=0, le=1, description="Portfolio target volatility")
    max_weight: float = Field(2.0, gt=0, le=10, description="Cap per instrument")


@register(
    "strategy", name="futures_trend", version="1.0.0", tags=["trend", "futures", "managed-futures"]
)
class FuturesTrend(Strategy):
    """Average of normalized EWMA crossover forecasts, each instrument vol-targeted.

    Designed for continuous (back-adjusted) futures series; works on any price series.
    """

    Params = FuturesTrendParams
    params: FuturesTrendParams
    capabilities: ClassVar[frozenset[str]] = frozenset(
        {ENGINE_VECTORIZED, ENGINE_EVENT, ASSET_FUTURE, "asset:equity", FREQ_DAILY, SUPPORTS_SHORT}
    )

    def warmup(self) -> int:
        """Longest slow span."""
        return max(self.params.fast_spans, default=16) * self.params.slow_multiple

    def generate_targets(self, data: MarketData) -> TargetFrame:
        """Forecast in [-2, 2] times the vol-targeted position size."""
        p = self.params
        close = data.panel(C.CLOSE)
        ppy = periods_per_year_for(data)
        daily_vol = rolling_std(pct_change(close, 1), p.vol_window)
        price_vol = daily_vol * close
        forecasts = []
        for span in p.fast_spans:
            fast = ewm_mean(close, span)
            slow = ewm_mean(close, span * p.slow_multiple)
            with np.errstate(divide="ignore", invalid="ignore"):
                raw = (fast - slow) / price_vol
            forecasts.append(np.clip(raw, -FORECAST_CAP, FORECAST_CAP))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)  # warm-up rows are all NaN
            forecast = np.nanmean(np.stack(forecasts), axis=0) / FORECAST_CAP
        n = max(len(data.instruments), 1)
        with np.errstate(divide="ignore", invalid="ignore"):
            size = p.target_vol / (daily_vol * np.sqrt(ppy)) / np.sqrt(n)
        w = np.clip(forecast * size, -p.max_weight, p.max_weight)
        warm = np.arange(len(close))[:, None] < self.warmup()
        return TargetFrame(data.timestamps, data.instruments, np.where(warm, np.nan, w))
