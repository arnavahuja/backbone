"""Pairs trading on a cointegrated spread (rolling hedge ratio)."""

from __future__ import annotations

from typing import ClassVar

import numpy as np
from pydantic import Field

from backbone.core import columns as C
from backbone.core.errors import ConfigError
from backbone.core.interfaces import (
    ASSET_EQUITY,
    ENGINE_EVENT,
    ENGINE_VECTORIZED,
    FREQ_DAILY,
    NEEDS_MULTI_ASSET,
    SUPPORTS_SHORT,
    Strategy,
)
from backbone.core.numeric import ffill, rolling_mean, rolling_std
from backbone.core.params import StrategyParams
from backbone.core.registry import register
from backbone.core.types import FloatArray, MarketData, TargetFrame

EPS = 1e-12


class PairsParams(StrategyParams):
    """Pairs trading parameters."""

    leg_a: str = Field("", description="First instrument (default: first in the data)")
    leg_b: str = Field("", description="Second instrument (default: second in the data)")
    window: int = Field(60, ge=20, le=1260, description="Hedge ratio and z-score window")
    entry_z: float = Field(2.0, gt=0, le=6, description="Enter when |z| exceeds this")
    exit_z: float = Field(0.5, ge=0, le=6, description="Exit when |z| is below this")
    gross: float = Field(1.0, gt=0, le=5, description="Gross exposure while in a trade")


def rolling_hedge_ratio(log_a: FloatArray, log_b: FloatArray, window: int) -> FloatArray:
    """Trailing OLS slope of log(a) on log(b)."""
    ma, mb = rolling_mean(log_a, window), rolling_mean(log_b, window)
    cov = rolling_mean(log_a * log_b, window) - ma * mb
    var = rolling_mean(log_b * log_b, window) - mb**2
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(var > EPS, cov / var, np.nan)


@register(
    "strategy", name="pairs_trading", version="1.0.0", tags=["stat-arb", "pairs", "cointegration"]
)
class PairsTrading(Strategy):
    """Trade the spread ``log(a) - beta log(b)`` when its z-score is stretched.

    Long the spread (long a, short beta x b) below ``-entry_z``, short above ``+entry_z``,
    flat once ``|z| < exit_z``. The hedge ratio and z-score use trailing windows. Use the
    research tools (or statsmodels' ``coint``) to pick cointegrated pairs.
    """

    Params = PairsParams
    params: PairsParams
    capabilities: ClassVar[frozenset[str]] = frozenset(
        {
            ENGINE_VECTORIZED,
            ENGINE_EVENT,
            ASSET_EQUITY,
            FREQ_DAILY,
            SUPPORTS_SHORT,
            NEEDS_MULTI_ASSET,
        }
    )

    def warmup(self) -> int:
        """Two windows (hedge ratio, then z-score)."""
        return 2 * self.params.window

    def _legs(self, data: MarketData) -> tuple[int, int]:
        insts = data.instruments
        a = self.params.leg_a or (insts[0] if insts else "")
        b = self.params.leg_b or (insts[1] if len(insts) > 1 else "")
        if a not in insts or b not in insts or a == b:
            raise ConfigError("Pairs trading needs two distinct instruments in the data")
        return insts.index(a), insts.index(b)

    def generate_targets(self, data: MarketData) -> TargetFrame:
        """Spread z-score with hysteresis."""
        p = self.params
        ia, ib = self._legs(data)
        close = data.panel(C.CLOSE)
        with np.errstate(divide="ignore", invalid="ignore"):
            la, lb = np.log(close[:, ia]), np.log(close[:, ib])
        beta = rolling_hedge_ratio(la, lb, p.window)
        spread = la - beta * lb
        with np.errstate(divide="ignore", invalid="ignore"):
            z = (spread - rolling_mean(spread, p.window)) / rolling_std(spread, p.window)
        events = np.where(
            z <= -p.entry_z,
            1.0,
            np.where(z >= p.entry_z, -1.0, np.where(np.abs(z) <= p.exit_z, 0.0, np.nan)),
        )
        state = np.nan_to_num(ffill(events), nan=0.0)
        scale = p.gross / (1.0 + np.abs(np.nan_to_num(beta, nan=1.0)))
        w = np.full(close.shape, np.nan)
        valid = np.isfinite(z)
        w[:, ia] = np.where(valid, state * scale, np.nan)
        w[:, ib] = np.where(valid, -state * scale * np.nan_to_num(beta, nan=1.0), np.nan)
        return TargetFrame(data.timestamps, data.instruments, w)
