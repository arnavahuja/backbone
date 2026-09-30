"""Risk-based constructors: inverse volatility, risk parity, minimum variance, HRP.

Selection and side come from the signals; sizing comes from trailing risk estimates.
"""

from __future__ import annotations

import numpy as np
from pydantic import Field

from backbone.core import columns as C
from backbone.core.interfaces import ConstructionContext, PortfolioConstructor
from backbone.core.params import ConstructorParams
from backbone.core.portfolio_math import (
    WeighFn,
    hrp_weights,
    inverse_vol_weights,
    min_variance_weights,
    risk_parity_weights,
    rolling_construct,
    simple_returns,
)
from backbone.core.registry import register
from backbone.core.types import FloatArray, TargetFrame, TargetKind


class RiskParams(ConstructorParams):
    """Common parameters of risk-based constructors."""

    window: int = Field(126, ge=10, le=1260, description="Covariance window (bars)")
    rebalance_every: int = Field(21, ge=1, le=252, description="Recompute weights every N bars")
    allow_short: bool = Field(False, description="Short instruments with negative signals")
    gross: float = Field(1.0, gt=0, le=5, description="Target gross exposure")


class _RiskConstructor(PortfolioConstructor):
    Params = RiskParams
    params: RiskParams

    def weigh(self, cov: FloatArray, signs: FloatArray, values: FloatArray) -> FloatArray:
        raise NotImplementedError

    def construct(self, signals: TargetFrame, ctx: ConstructionContext) -> TargetFrame:
        """Rolling construction on trailing covariance."""
        aligned = signals.reindex(ctx.data.timestamps, ctx.data.instruments)
        rets = simple_returns(ctx.data.panel(C.CLOSE))
        weigh: WeighFn = self.weigh
        w = rolling_construct(
            aligned.values,
            rets,
            weigh,
            every=self.params.rebalance_every,
            window=self.params.window,
            allow_short=self.params.allow_short,
            gross=self.params.gross,
        )
        out = TargetFrame(aligned.timestamps, aligned.instruments, w, TargetKind.WEIGHTS)
        return out.reindex(signals.timestamps, signals.instruments)


@register("portfolio_constructor", name="inverse_volatility", version="1.0.0", tags=["risk"])
class InverseVolatility(_RiskConstructor):
    """Weights proportional to 1 / trailing volatility."""

    def weigh(self, cov: FloatArray, signs: FloatArray, values: FloatArray) -> FloatArray:
        """Inverse volatility."""
        return inverse_vol_weights(cov) * signs


@register("portfolio_constructor", name="risk_parity", version="1.0.0", tags=["risk"])
class RiskParity(_RiskConstructor):
    """Equal risk contribution from each selected instrument."""

    def weigh(self, cov: FloatArray, signs: FloatArray, values: FloatArray) -> FloatArray:
        """ERC on the sign-adjusted covariance."""
        adj = cov * np.outer(signs, signs)
        return risk_parity_weights(adj) * signs


class MinVarParams(RiskParams):
    """Minimum variance parameters."""

    max_weight: float = Field(0.5, gt=0, le=1, description="Maximum weight per instrument")


@register("portfolio_constructor", name="minimum_variance", version="1.0.0", tags=["risk"])
class MinimumVariance(_RiskConstructor):
    """Long-only minimum variance portfolio of the selected instruments."""

    Params = MinVarParams
    params: MinVarParams

    def weigh(self, cov: FloatArray, signs: FloatArray, values: FloatArray) -> FloatArray:
        """Minimum variance."""
        return min_variance_weights(cov, self.params.max_weight) * signs


@register("portfolio_constructor", name="hierarchical_risk_parity", version="1.0.0", tags=["risk"])
class HierarchicalRiskParity(_RiskConstructor):
    """Hierarchical risk parity (single-linkage clustering, recursive bisection)."""

    def weigh(self, cov: FloatArray, signs: FloatArray, values: FloatArray) -> FloatArray:
        """HRP."""
        adj = cov * np.outer(signs, signs)
        return hrp_weights(adj) * signs
