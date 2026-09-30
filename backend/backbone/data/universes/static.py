"""Static universe: every configured instrument, whenever it has a price."""

from __future__ import annotations

import numpy as np

from backbone.core import columns as C
from backbone.core.interfaces import UniverseProvider
from backbone.core.registry import register
from backbone.core.types import FloatArray, MarketData


@register("universe", name="static", version="1.0.0", tags=["basic"])
class StaticUniverse(UniverseProvider):
    """All configured instruments; an instrument is tradable on bars where it has a close.

    Point-in-time by construction: a delisted instrument stops having prices.
    """

    def membership(self, data: MarketData) -> FloatArray:
        """1.0 where the instrument has a close price at that bar."""
        return np.isfinite(data.panel(C.CLOSE)).astype(np.float64)
