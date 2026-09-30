"""Mean reversion on Bollinger-band z-scores."""

from __future__ import annotations

from typing import ClassVar

import numpy as np
from pydantic import Field, model_validator

from backbone.core import columns as C
from backbone.core.interfaces import (
    ASSET_EQUITY,
    ENGINE_EVENT,
    ENGINE_VECTORIZED,
    FREQ_DAILY,
    FREQ_INTRADAY,
    SUPPORTS_SHORT,
    Strategy,
)
from backbone.core.numeric import ffill, rolling_mean, rolling_std
from backbone.core.params import StrategyParams
from backbone.core.registry import register
from backbone.core.types import FloatArray, MarketData, TargetFrame


class MeanReversionParams(StrategyParams):
    """Mean reversion parameters."""

    window: int = Field(20, ge=5, le=252, description="Band window (bars)")
    entry_z: float = Field(2.0, gt=0, le=6, description="Enter when |z| exceeds this")
    exit_z: float = Field(0.5, ge=0, le=6, description="Exit when |z| falls below this")
    allow_short: bool = Field(True, description="Short when z is above +entry")

    @model_validator(mode="after")
    def _check(self) -> MeanReversionParams:
        if self.exit_z >= self.entry_z:
            raise ValueError("exit_z must be below entry_z")
        return self


def band_positions(z: FloatArray, entry: float, exit_: float, allow_short: bool) -> FloatArray:
    """Hysteresis state machine, vectorized: set on entry, clear on exit, hold otherwise."""
    long_entry = z <= -entry
    short_entry = (z >= entry) if allow_short else np.zeros_like(z, dtype=bool)
    flat = np.abs(z) <= exit_
    events = np.where(long_entry, 1.0, np.where(short_entry, -1.0, np.where(flat, 0.0, np.nan)))
    state = ffill(events)
    return np.where(np.isfinite(z), np.nan_to_num(state, nan=0.0), np.nan)


@register("strategy", name="mean_reversion", version="1.0.0", tags=["mean-reversion"])
class MeanReversion(Strategy):
    """Buy when price is ``entry_z`` standard deviations below its mean, exit near the mean."""

    Params = MeanReversionParams
    params: MeanReversionParams
    capabilities: ClassVar[frozenset[str]] = frozenset(
        {ENGINE_VECTORIZED, ENGINE_EVENT, ASSET_EQUITY, FREQ_DAILY, FREQ_INTRADAY, SUPPORTS_SHORT}
    )

    def warmup(self) -> int:
        """Band window."""
        return self.params.window

    def generate_targets(self, data: MarketData) -> TargetFrame:
        """Equal-weight hysteresis positions."""
        p = self.params
        close = data.panel(C.CLOSE)
        with np.errstate(divide="ignore", invalid="ignore"):
            z = (close - rolling_mean(close, p.window)) / rolling_std(close, p.window)
        pos = band_positions(z, p.entry_z, p.exit_z, p.allow_short)
        n = max(len(data.instruments), 1)
        return TargetFrame(data.timestamps, data.instruments, pos / n)
