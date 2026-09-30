"""Channel breakout with protective stop orders (event engine only, path dependent)."""

from __future__ import annotations

from typing import ClassVar

import numpy as np
from pydantic import Field

from backbone.core import columns as C
from backbone.core.interfaces import (
    ASSET_EQUITY,
    ASSET_FUTURE,
    ENGINE_EVENT,
    FREQ_DAILY,
    Context,
    Strategy,
)
from backbone.core.params import StrategyParams
from backbone.core.registry import register
from backbone.core.types import OrderType


class BreakoutParams(StrategyParams):
    """Breakout parameters."""

    channel: int = Field(55, ge=5, le=500, description="Breakout channel length (bars)")
    stop_pct: float = Field(0.05, gt=0, lt=1, description="Stop distance below entry")
    allocation: float = Field(0.95, gt=0, le=1, description="Fraction of equity per position")


@register("strategy", name="breakout_stop", version="1.0.0", tags=["trend", "event", "stops"])
class BreakoutStop(Strategy):
    """Buy on a close above the prior channel high; exit on a resting stop order.

    Each instrument gets ``allocation / N`` of equity. The stop is a real stop order held by
    the broker, so the exit price depends on the intrabar path (event engine only).
    """

    Params = BreakoutParams
    params: BreakoutParams
    capabilities: ClassVar[frozenset[str]] = frozenset(
        {ENGINE_EVENT, ASSET_EQUITY, ASSET_FUTURE, FREQ_DAILY}
    )

    def warmup(self) -> int:
        """Channel length."""
        return self.params.channel + 1

    def on_bar(self, ctx: Context) -> None:
        """Enter on breakout, place a protective stop, re-arm once flat."""
        p = self.params
        close = ctx.history(C.CLOSE, p.channel + 1)
        if len(close) <= p.channel:
            return
        prior_high = np.nanmax(close[:-1], axis=0)
        now = close[-1]
        held = {pos.instrument: pos.quantity for pos in ctx.portfolio.positions}
        pending = {o.instrument for o in ctx.open_orders()}
        budget = ctx.portfolio.equity * p.allocation / max(len(ctx.instruments), 1)
        for j, inst in enumerate(ctx.instruments):
            price = now[j]
            if not np.isfinite(price) or inst in pending:
                continue
            if held.get(inst, 0.0) == 0 and price > prior_high[j]:
                qty = float(np.floor(budget / price))
                if qty > 0:
                    ctx.order(inst, qty, tag="entry")
                    ctx.order(
                        inst, -qty, OrderType.STOP, stop_price=price * (1 - p.stop_pct), tag="stop"
                    )
