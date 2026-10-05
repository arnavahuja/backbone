"""Fixed-weight (constant-mix) allocation, e.g. 60/40."""

from __future__ import annotations

from typing import ClassVar

import numpy as np
from pydantic import Field

from backbone.core import columns as C
from backbone.core.errors import DataError
from backbone.core.interfaces import (
    ASSET_EQUITY,
    ASSET_FUTURE,
    ENGINE_EVENT,
    ENGINE_VECTORIZED,
    FREQ_DAILY,
    FREQ_INTRADAY,
    SUPPORTS_SHORT,
    Strategy,
)
from backbone.core.params import StrategyParams
from backbone.core.registry import register
from backbone.core.types import MarketData, TargetFrame


class FixedWeightsParams(StrategyParams):
    """Target weight per instrument (instrument id -> weight)."""

    weights: dict[str, float] = Field(
        default_factory=dict,
        description="Instrument id -> weight, e.g. {SPY: 0.6, IEF: 0.4} (negative weights "
        "short). Empty: equal weight across all instruments",
    )
    renormalize_missing: bool = Field(
        False,
        description="Spread the weight of instruments without a price over the others "
        "(otherwise it stays in cash)",
    )


@register(
    "strategy",
    name="fixed_weights",
    version="1.0.0",
    tags=["benchmark", "allocation", "multi-asset"],
)
class FixedWeights(Strategy):
    """Hold constant weights. Use rebalance ``monthly`` (or ``every_bar``) for constant mix.

    With the default ``on_change`` rule the weights are set once and then drift.
    """

    Params = FixedWeightsParams
    params: FixedWeightsParams
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

    def generate_targets(self, data: MarketData) -> TargetFrame:
        """Configured weights on bars where the instrument has a price."""
        p = self.params
        missing = sorted(set(p.weights) - set(data.instruments))
        if missing:
            raise DataError(
                f"Instruments not in the data: {missing}",
                details={"instruments": list(data.instruments)},
            )
        n = max(len(data.instruments), 1)
        base = np.array([p.weights.get(i, 0.0) if p.weights else 1.0 / n for i in data.instruments])
        valid = np.isfinite(data.panel(C.CLOSE))
        w = np.where(valid, base[None, :], 0.0)
        if p.renormalize_missing:
            total = np.abs(base).sum()
            live = np.abs(w).sum(axis=1, keepdims=True)
            with np.errstate(divide="ignore", invalid="ignore"):
                w = np.where(live > 0, w * total / live, 0.0)
        return TargetFrame(data.timestamps, data.instruments, w)
