"""Opening range breakout (intraday, event engine)."""

from __future__ import annotations

from typing import ClassVar

import numpy as np
from pydantic import Field

from backbone.core import columns as C
from backbone.core.interfaces import ASSET_EQUITY, ENGINE_EVENT, FREQ_INTRADAY, Context, Strategy
from backbone.core.params import StrategyParams
from backbone.core.registry import register


class OrbParams(StrategyParams):
    """Opening range breakout parameters."""

    range_bars: int = Field(6, ge=1, le=100, description="Bars that form the opening range")
    flat_bars_before_close: int = Field(
        2, ge=1, le=50, description="Go flat this many bars before the close"
    )
    allow_short: bool = Field(True, description="Short breakdowns below the range")


@register("strategy", name="intraday_orb", version="1.0.0", tags=["intraday", "breakout"])
class IntradayOrb(Strategy):
    """Trade breakouts of the first ``range_bars`` of each session; flat before the close.

    Sessions are detected from calendar-day changes in the bar timestamps; the session length
    is learned from completed sessions only.
    """

    Params = OrbParams
    params: OrbParams
    capabilities: ClassVar[frozenset[str]] = frozenset(
        {ENGINE_EVENT, ASSET_EQUITY, FREQ_INTRADAY, "supports:short"}
    )

    def on_bar(self, ctx: Context) -> None:
        """Decide from today's bars so far."""
        p = self.params
        days = ctx.timestamps().astype("datetime64[D]")
        today = days == days[-1]
        bars_today = int(today.sum())
        st = ctx.state
        if days[-1] != st.get("day"):
            if "day" in st:
                st["session_bars"] = max(st.get("session_bars", 0), st.get("count", 0))
            st["day"], st["count"] = days[-1], 0
        st["count"] = bars_today
        session = st.get("session_bars", 0)
        if session and bars_today >= session - p.flat_bars_before_close:
            ctx.set_target_weights({})
            return
        if bars_today <= p.range_bars:
            return
        window = ctx.history(C.CLOSE, bars_today)
        high = np.nanmax(ctx.history(C.HIGH, bars_today)[: p.range_bars], axis=0)
        low = np.nanmin(ctx.history(C.LOW, bars_today)[: p.range_bars], axis=0)
        now = window[-1]
        n = max(len(ctx.instruments), 1)
        targets = {}
        for j, inst in enumerate(ctx.instruments):
            if now[j] > high[j]:
                targets[inst] = 1.0 / n
            elif p.allow_short and now[j] < low[j]:
                targets[inst] = -1.0 / n
        ctx.set_target_weights(targets)
