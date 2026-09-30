"""Time-series momentum (trend following on each instrument's own past return)."""

from __future__ import annotations

from typing import ClassVar

import numpy as np
from pydantic import Field

from backbone.core import columns as C
from backbone.core.calendar import periods_per_year_for
from backbone.core.interfaces import (
    ASSET_EQUITY,
    ASSET_FUTURE,
    ENGINE_EVENT,
    ENGINE_VECTORIZED,
    FREQ_DAILY,
    SUPPORTS_SHORT,
    Strategy,
)
from backbone.core.numeric import pct_change, rolling_std, shift
from backbone.core.params import StrategyParams
from backbone.core.registry import register
from backbone.core.types import MarketData, TargetFrame


class TsMomentumParams(StrategyParams):
    """Parameters of time-series momentum."""

    lookback: int = Field(252, ge=5, le=1000, description="Momentum lookback (bars)")
    skip: int = Field(21, ge=0, le=63, description="Most recent bars to skip")
    allow_short: bool = Field(True, description="Short instruments with negative momentum")
    vol_scale: bool = Field(True, description="Scale positions by inverse volatility")
    vol_window: int = Field(63, ge=5, le=504, description="Volatility window (bars)")
    target_vol: float = Field(0.10, gt=0, le=1.0, description="Per-instrument target vol")
    max_weight: float = Field(1.0, gt=0, le=5.0, description="Cap per instrument")


@register("strategy", name="ts_momentum", version="1.0.0", tags=["trend", "momentum", "futures"])
class TsMomentum(Strategy):
    """Go long instruments whose trailing return is positive and short those negative.

    Positions are optionally scaled to a per-instrument target volatility and divided by the
    number of instruments (Moskowitz, Ooi and Pedersen 2012 style).
    """

    Params = TsMomentumParams
    params: TsMomentumParams
    capabilities: ClassVar[frozenset[str]] = frozenset(
        {ENGINE_VECTORIZED, ENGINE_EVENT, ASSET_EQUITY, ASSET_FUTURE, FREQ_DAILY, SUPPORTS_SHORT}
    )

    def warmup(self) -> int:
        """Lookback plus skip."""
        return self.params.lookback + self.params.skip

    def generate_targets(self, data: MarketData) -> TargetFrame:
        """Momentum sign, optionally vol-scaled, divided by instrument count."""
        p = self.params
        close = data.panel(C.CLOSE)
        past = shift(close, p.skip) if p.skip else close
        mom = pct_change(past, p.lookback)
        sign = np.sign(mom)
        if not p.allow_short:
            sign = np.clip(sign, 0.0, None)
        if p.vol_scale:
            daily = pct_change(close, 1)
            vol = rolling_std(daily, p.vol_window) * np.sqrt(periods_per_year_for(data))
            with np.errstate(divide="ignore", invalid="ignore"):
                size = np.minimum(p.target_vol / vol, p.max_weight)
        else:
            size = np.ones_like(close)
        n = max(len(data.instruments), 1)
        weights = np.where(np.isfinite(mom), sign * size / n, np.nan)
        return TargetFrame(data.timestamps, data.instruments, weights)
