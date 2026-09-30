"""Daily trend signal with intraday execution (multi-frequency, event engine)."""

from __future__ import annotations

from typing import ClassVar

import numpy as np
from pydantic import Field

from backbone.core import columns as C
from backbone.core.interfaces import (
    ASSET_EQUITY,
    ASSET_FUTURE,
    ENGINE_EVENT,
    FREQ_INTRADAY,
    Context,
    Strategy,
)
from backbone.core.params import StrategyParams
from backbone.core.registry import register


class DailyTrendParams(StrategyParams):
    """Parameters."""

    fast_days: int = Field(5, ge=2, le=100, description="Fast SMA of daily closes")
    slow_days: int = Field(20, ge=3, le=400, description="Slow SMA of daily closes")


@register(
    "strategy",
    name="daily_trend_intraday",
    version="1.0.0",
    tags=["trend", "intraday", "multi-frequency"],
)
class DailyTrendIntraday(Strategy):
    """Signals from completed daily bars, executed on the intraday bar stream.

    Uses ``ctx.resampled(close, "1d")`` so only finished days are visible; the resulting
    target changes are executed on the next intraday bar.
    """

    Params = DailyTrendParams
    params: DailyTrendParams
    capabilities: ClassVar[frozenset[str]] = frozenset(
        {ENGINE_EVENT, ASSET_EQUITY, ASSET_FUTURE, FREQ_INTRADAY}
    )

    def on_bar(self, ctx: Context) -> None:
        """Recompute when a new daily bar has completed."""
        p = self.params
        daily = ctx.resampled(C.CLOSE, "1d", p.slow_days)
        if len(daily) < p.slow_days or ctx.state.get("days") == len(ctx.resampled(C.CLOSE, "1d")):
            return
        ctx.state["days"] = len(ctx.resampled(C.CLOSE, "1d"))
        fast = np.nanmean(daily[-p.fast_days :], axis=0)
        slow = np.nanmean(daily, axis=0)
        n = max(len(ctx.instruments), 1)
        ctx.set_target_weights(
            {i: 1.0 / n for i, f, s in zip(ctx.instruments, fast, slow, strict=True) if f > s}
        )
