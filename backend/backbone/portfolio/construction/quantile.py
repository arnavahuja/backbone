"""Top-N and quantile long-short constructor."""

from __future__ import annotations

import numpy as np
from pydantic import Field

from backbone.core.interfaces import ConstructionContext, PortfolioConstructor
from backbone.core.params import ConstructorParams
from backbone.core.registry import register
from backbone.core.types import FloatArray, IntArray, TargetFrame, TargetKind


class QuantileParams(ConstructorParams):
    """Quantile long-short parameters."""

    quantiles: int = Field(10, ge=2, le=100, description="Number of quantile buckets")
    top_n: int = Field(0, ge=0, le=5000, description="If > 0, hold top/bottom N instead")
    long_only: bool = Field(False, description="Hold only the top bucket")
    gross: float = Field(1.0, gt=0, le=5, description="Target gross exposure")
    min_names: int = Field(4, ge=1, description="Minimum instruments with a signal to trade")


def rank_rows(values: FloatArray) -> IntArray:
    """Row-wise 0-based rank of finite values (NaN rows get -1)."""
    filled = np.where(np.isfinite(values), values, np.inf)
    order = np.argsort(filled, axis=1, kind="stable")
    ranks = np.empty_like(order)
    np.put_along_axis(ranks, order, np.arange(values.shape[1])[None, :], axis=1)
    return np.where(np.isfinite(values), ranks, -1)


@register(
    "portfolio_constructor",
    name="quantile_long_short",
    version="1.0.0",
    tags=["cross-sectional"],
    capabilities={"supports:short"},
)
class QuantileLongShort(PortfolioConstructor):
    """Long the top quantile (or top N), short the bottom one, equal weight within legs."""

    Params = QuantileParams
    params: QuantileParams

    def construct(self, signals: TargetFrame, ctx: ConstructionContext) -> TargetFrame:
        """Rank signals cross-sectionally each bar."""
        p = self.params
        s = signals.values
        count = np.isfinite(s).sum(axis=1, keepdims=True)
        ranks = rank_rows(s)
        if p.top_n > 0:
            n = np.minimum(p.top_n, count // 2 if not p.long_only else count)
            long = (ranks >= count - n) & (ranks >= 0)
            short = (ranks >= 0) & (ranks < n)
        else:
            bucket = np.where(ranks >= 0, (ranks * p.quantiles) // np.maximum(count, 1), -1)
            long = bucket == p.quantiles - 1
            short = bucket == 0
        if p.long_only:
            short = np.zeros_like(short)
        enough = count >= p.min_names
        n_long = long.sum(axis=1, keepdims=True)
        n_short = short.sum(axis=1, keepdims=True)
        legs = 1.0 if p.long_only else 2.0
        with np.errstate(divide="ignore", invalid="ignore"):
            w = np.where(long, p.gross / legs / n_long, 0.0) - np.where(
                short, p.gross / legs / n_short, 0.0
            )
        w = np.where(enough, np.nan_to_num(w), 0.0)
        return signals.replace(values=w, kind=TargetKind.WEIGHTS)
