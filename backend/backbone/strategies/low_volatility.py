"""Low-volatility anomaly: prefer the least volatile instruments."""

from __future__ import annotations

from typing import ClassVar

from pydantic import Field

from backbone.core import columns as C
from backbone.core.interfaces import (
    ASSET_EQUITY,
    ENGINE_EVENT,
    ENGINE_VECTORIZED,
    FREQ_DAILY,
    NEEDS_MULTI_ASSET,
    Strategy,
)
from backbone.core.numeric import pct_change, rolling_std
from backbone.core.params import StrategyParams
from backbone.core.registry import register
from backbone.core.types import MarketData, TargetFrame, TargetKind


class LowVolParams(StrategyParams):
    """Low volatility parameters."""

    window: int = Field(252, ge=20, le=1260, description="Volatility window (bars)")


@register("strategy", name="low_volatility", version="1.0.0", tags=["factor", "defensive"])
class LowVolatility(Strategy):
    """Signal = minus trailing volatility (higher is better).

    Emits signals: use ``quantile_long_short`` (long-only for a low-vol portfolio) or a
    risk-based constructor.
    """

    Params = LowVolParams
    params: LowVolParams
    output_kind: ClassVar[TargetKind] = TargetKind.SIGNALS
    capabilities: ClassVar[frozenset[str]] = frozenset(
        {ENGINE_VECTORIZED, ENGINE_EVENT, ASSET_EQUITY, FREQ_DAILY, NEEDS_MULTI_ASSET}
    )

    def warmup(self) -> int:
        """Volatility window."""
        return self.params.window

    def generate_targets(self, data: MarketData) -> TargetFrame:
        """Negative trailing volatility."""
        vol = rolling_std(pct_change(data.panel(C.CLOSE), 1), self.params.window)
        return TargetFrame(data.timestamps, data.instruments, -vol, TargetKind.SIGNALS)
