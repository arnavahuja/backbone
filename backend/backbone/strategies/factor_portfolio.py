"""Simple multi-factor (Fama-French style) composite score."""

from __future__ import annotations

from typing import ClassVar

import numpy as np
from pydantic import Field

from backbone.core import columns as C
from backbone.core.interfaces import (
    ASSET_EQUITY,
    ENGINE_EVENT,
    ENGINE_VECTORIZED,
    FREQ_DAILY,
    NEEDS_MULTI_ASSET,
    SUPPORTS_SHORT,
    Strategy,
)
from backbone.core.numeric import pct_change, rolling_std, shift
from backbone.core.params import StrategyParams
from backbone.core.registry import register
from backbone.core.types import FloatArray, MarketData, TargetFrame, TargetKind


class FactorParams(StrategyParams):
    """Factor weights (a factor is skipped when its field is missing)."""

    momentum_weight: float = Field(1.0, ge=0, le=10, description="Weight of 12-1 momentum")
    low_vol_weight: float = Field(1.0, ge=0, le=10, description="Weight of low volatility")
    value_weight: float = Field(1.0, ge=0, le=10, description="Weight of book-to-market")
    size_weight: float = Field(0.0, ge=0, le=10, description="Weight of small size")
    value_field: str = Field("book_to_market", description="Point-in-time value field")
    size_field: str = Field("market_cap", description="Point-in-time size field")


def zscore_rows(x: FloatArray) -> FloatArray:
    """Cross-sectional z-score per row (NaN-aware)."""
    finite = np.where(np.isfinite(x), x, np.nan)
    count = np.isfinite(finite).sum(axis=1, keepdims=True)
    safe = np.where(count > 1, 1.0, np.nan)
    mean = np.nansum(finite, axis=1, keepdims=True) / np.maximum(count, 1)
    var = np.nansum((finite - mean) ** 2, axis=1, keepdims=True) / np.maximum(count - 1, 1)
    with np.errstate(divide="ignore", invalid="ignore"):
        return (finite - mean) / np.sqrt(var) * safe


@register(
    "strategy",
    name="factor_portfolio",
    version="1.0.0",
    tags=["factor", "cross-sectional"],
    capabilities=None,
)
class FactorPortfolio(Strategy):
    """Composite of z-scored momentum, low volatility and (if present) value and size.

    Value and size come from point-in-time fields (e.g. Compustat joined on availability
    date). Emits signals; pair with ``quantile_long_short``.
    """

    Params = FactorParams
    params: FactorParams
    output_kind: ClassVar[TargetKind] = TargetKind.SIGNALS
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
    MOM_LOOKBACK: ClassVar[int] = 252
    MOM_SKIP: ClassVar[int] = 21
    VOL_WINDOW: ClassVar[int] = 252

    def warmup(self) -> int:
        """Momentum formation period."""
        return self.MOM_LOOKBACK + self.MOM_SKIP

    def generate_targets(self, data: MarketData) -> TargetFrame:
        """Weighted average of available factor z-scores."""
        p = self.params
        close = data.panel(C.CLOSE)
        parts: list[tuple[float, FloatArray]] = [
            (p.momentum_weight, pct_change(shift(close, self.MOM_SKIP), self.MOM_LOOKBACK)),
            (p.low_vol_weight, -rolling_std(pct_change(close, 1), self.VOL_WINDOW)),
        ]
        if data.has_field(p.value_field):
            parts.append((p.value_weight, data.panel(p.value_field)))
        if data.has_field(p.size_field):
            parts.append((p.size_weight, -np.log(data.panel(p.size_field))))
        total = np.zeros_like(close)
        weight = np.zeros_like(close)
        for w, raw in parts:
            if w == 0:
                continue
            z = zscore_rows(raw)
            ok = np.isfinite(z)
            total += np.where(ok, w * z, 0.0)
            weight += np.where(ok, w, 0.0)
        with np.errstate(divide="ignore", invalid="ignore"):
            score = np.where(weight > 0, total / weight, np.nan)
        return TargetFrame(data.timestamps, data.instruments, score, TargetKind.SIGNALS)
