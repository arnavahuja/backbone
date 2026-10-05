"""Price-versus-moving-average trend filter across several sleeves (e.g. 10-month SMA)."""

from __future__ import annotations

from typing import ClassVar, Literal

import numpy as np
from pydantic import Field

from backbone.core import columns as C
from backbone.core.interfaces import (
    ASSET_EQUITY,
    ASSET_FUTURE,
    ENGINE_EVENT,
    ENGINE_VECTORIZED,
    FREQ_DAILY,
    FREQ_INTRADAY,
    Strategy,
)
from backbone.core.numeric import rolling_mean
from backbone.core.params import StrategyParams
from backbone.core.registry import register
from backbone.core.types import MarketData, TargetFrame


class TrendFilterParams(StrategyParams):
    """Trend filter parameters."""

    window: int = Field(10, ge=2, le=500, description="Moving-average window (bars)")
    weighting: Literal["active", "all"] = Field(
        "all",
        description="'all': each sleeve gets 1/N (inactive sleeves sit in cash); "
        "'active': equal weight across sleeves currently in an uptrend",
    )


@register("strategy", name="trend_filter", version="1.0.0", tags=["trend", "multi-asset"])
class TrendFilter(Strategy):
    """Long a sleeve while its price is above its moving average, otherwise cash.

    Sleeves start when they have ``window`` bars of history, so a run covering instruments
    with different start dates uses fewer sleeves early on.
    """

    Params = TrendFilterParams
    params: TrendFilterParams
    capabilities: ClassVar[frozenset[str]] = frozenset(
        {ENGINE_VECTORIZED, ENGINE_EVENT, ASSET_EQUITY, ASSET_FUTURE, FREQ_DAILY, FREQ_INTRADAY}
    )

    def warmup(self) -> int:
        """Moving-average window."""
        return self.params.window

    def generate_targets(self, data: MarketData) -> TargetFrame:
        """1/N per sleeve in an uptrend (N = all sleeves with history, or active ones)."""
        p = self.params
        close = data.panel(C.CLOSE)
        sma = rolling_mean(close, p.window)
        ready = np.isfinite(sma) & np.isfinite(close)
        up = ready & (close > sma)
        base = ready if p.weighting == "all" else up
        n = base.sum(axis=1, keepdims=True)
        with np.errstate(divide="ignore", invalid="ignore"):
            w = np.where(up & (n > 0), 1.0 / n, 0.0)
        return TargetFrame(data.timestamps, data.instruments, w)
