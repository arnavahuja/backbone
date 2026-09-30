"""Cross-sectional momentum (emit signals; pair with a quantile long-short constructor)."""

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
    SUPPORTS_SHORT,
    Strategy,
)
from backbone.core.numeric import pct_change, shift
from backbone.core.params import StrategyParams
from backbone.core.registry import register
from backbone.core.types import MarketData, TargetFrame, TargetKind


class XsMomentumParams(StrategyParams):
    """Cross-sectional momentum parameters."""

    lookback: int = Field(252, ge=20, le=1000, description="Formation period (bars)")
    skip: int = Field(21, ge=0, le=63, description="Most recent bars skipped (reversal)")


@register(
    "strategy", name="xs_momentum", version="1.0.0", tags=["cross-sectional", "momentum", "factor"]
)
class XsMomentum(Strategy):
    """Signal = trailing return over ``lookback`` skipping the last ``skip`` bars (12-1).

    Emits signals: combine with ``quantile_long_short`` for long-short decile portfolios.
    """

    Params = XsMomentumParams
    params: XsMomentumParams
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

    def warmup(self) -> int:
        """Lookback plus skip."""
        return self.params.lookback + self.params.skip

    def generate_targets(self, data: MarketData) -> TargetFrame:
        """Momentum score per instrument."""
        close = data.panel(C.CLOSE)
        past = shift(close, self.params.skip) if self.params.skip else close
        score = pct_change(past, self.params.lookback)
        return TargetFrame(data.timestamps, data.instruments, score, TargetKind.SIGNALS)
