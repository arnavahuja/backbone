"""Mean-variance optimization with signals as expected-return views."""

from __future__ import annotations

import numpy as np
from pydantic import Field

from backbone.core import columns as C
from backbone.core.interfaces import ConstructionContext, PortfolioConstructor
from backbone.core.params import ConstructorParams
from backbone.core.portfolio_math import mean_variance_weights, rolling_construct, simple_returns
from backbone.core.registry import register
from backbone.core.types import FloatArray, TargetFrame, TargetKind


class MeanVarianceParams(ConstructorParams):
    """Mean-variance parameters."""

    window: int = Field(126, ge=10, le=1260, description="Covariance window (bars)")
    rebalance_every: int = Field(21, ge=1, le=252, description="Recompute every N bars")
    risk_aversion: float = Field(5.0, gt=0, le=1000, description="Risk aversion")
    signal_scale: float = Field(0.1, gt=0, le=10, description="Annual return per unit signal")
    max_weight: float = Field(0.3, gt=0, le=2, description="Maximum absolute weight")
    long_only: bool = Field(True, description="Long-only")
    gross: float = Field(1.0, gt=0, le=5, description="Maximum gross exposure")


@register("portfolio_constructor", name="mean_variance", version="1.0.0", tags=["optimizer"])
class MeanVariance(PortfolioConstructor):
    """Maximize expected return minus a risk penalty; signals are expected-return views."""

    Params = MeanVarianceParams
    params: MeanVarianceParams

    def construct(self, signals: TargetFrame, ctx: ConstructionContext) -> TargetFrame:
        """Rolling mean-variance optimization."""
        p = self.params
        aligned = signals.reindex(ctx.data.timestamps, ctx.data.instruments)
        rets = simple_returns(ctx.data.panel(C.CLOSE))
        per_bar = p.signal_scale / ctx.periods_per_year

        def weigh(cov: FloatArray, signs: FloatArray, values: FloatArray) -> FloatArray:
            return mean_variance_weights(
                values * per_bar, cov, p.risk_aversion, p.max_weight, p.long_only, p.gross
            )

        w = rolling_construct(
            aligned.values,
            rets,
            weigh,
            every=p.rebalance_every,
            window=p.window,
            allow_short=not p.long_only,
            gross=p.gross,
            normalize=False,
        )
        out = TargetFrame(
            aligned.timestamps, aligned.instruments, np.nan_to_num(w), TargetKind.WEIGHTS
        )
        return out.reindex(signals.timestamps, signals.instruments)
