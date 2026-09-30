"""Simple moving average crossover."""

from __future__ import annotations

from typing import ClassVar

import numpy as np
from pydantic import Field, model_validator

from backbone.core import columns as C
from backbone.core.interfaces import (
    ASSET_EQUITY,
    ASSET_FUTURE,
    ENGINE_EVENT,
    ENGINE_VECTORIZED,
    FREQ_DAILY,
    FREQ_INTRADAY,
    SUPPORTS_SHORT,
    Context,
    Strategy,
)
from backbone.core.numeric import rolling_mean
from backbone.core.params import StrategyParams
from backbone.core.registry import register
from backbone.core.types import FloatArray, MarketData, TargetFrame


class SmaCrossoverParams(StrategyParams):
    """Parameters of the SMA crossover strategy."""

    fast: int = Field(20, ge=2, le=200, description="Fast window (bars)")
    slow: int = Field(100, ge=5, le=500, description="Slow window (bars)")
    allow_short: bool = Field(False, description="Go short when fast < slow")

    @model_validator(mode="after")
    def _check(self) -> SmaCrossoverParams:
        if self.fast >= self.slow:
            raise ValueError("fast must be smaller than slow")
        return self


def crossover_signal(close: FloatArray, fast: int, slow: int, allow_short: bool) -> FloatArray:
    """+1 when fast SMA > slow SMA, else 0 (or -1 if shorting); NaN during warm-up."""
    f = rolling_mean(close, fast)
    s = rolling_mean(close, slow)
    low = -1.0 if allow_short else 0.0
    sig = np.where(f > s, 1.0, low)
    return np.where(np.isfinite(f) & np.isfinite(s), sig, np.nan)


@register("strategy", name="sma_crossover", version="1.0.0", tags=["trend", "technical"])
class SmaCrossover(Strategy):
    """Long when the fast moving average is above the slow one, equal-weighted."""

    Params = SmaCrossoverParams
    params: SmaCrossoverParams
    capabilities: ClassVar[frozenset[str]] = frozenset(
        {
            ENGINE_VECTORIZED,
            ENGINE_EVENT,
            ASSET_EQUITY,
            ASSET_FUTURE,
            FREQ_DAILY,
            FREQ_INTRADAY,
            SUPPORTS_SHORT,
        }
    )

    def warmup(self) -> int:
        """Slow window."""
        return self.params.slow

    def generate_targets(self, data: MarketData) -> TargetFrame:
        """Signal divided by the number of instruments."""
        p = self.params
        close = data.panel(C.CLOSE)
        sig = crossover_signal(close, p.fast, p.slow, p.allow_short)
        n = max(len(data.instruments), 1)
        return TargetFrame(data.timestamps, data.instruments, sig / n)

    def on_bar(self, ctx: Context) -> None:
        """Event form: same rule on the trailing window."""
        p = self.params
        close = ctx.history(C.CLOSE, p.slow)
        if len(close) < p.slow:
            return
        sig = crossover_signal(close, p.fast, p.slow, p.allow_short)[-1]
        n = max(len(ctx.instruments), 1)
        ctx.set_target_weights(
            {i: float(s) / n for i, s in zip(ctx.instruments, sig, strict=True) if np.isfinite(s)}
        )
