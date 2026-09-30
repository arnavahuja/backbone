from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import polars as pl

from backbone.core import columns as C
from backbone.core.types import MarketData
from backbone.data.fundamentals import asof_join, derive_ratios


def test_asof_join_never_uses_future_values():
    days = [datetime(2024, 1, d, tzinfo=UTC) for d in range(1, 11)]
    prices = MarketData(pl.DataFrame({C.TIMESTAMP: days, C.INSTRUMENT: ["A"] * 10,
                                      C.CLOSE: [10.0] * 10, "market_cap": [1e9] * 10}))
    funda = MarketData(pl.DataFrame({
        C.TIMESTAMP: [datetime(2024, 1, 4, tzinfo=UTC), datetime(2024, 1, 8, tzinfo=UTC)],
        C.INSTRUMENT: ["A", "A"], "book_equity": [100.0, 200.0],
    }))
    joined = derive_ratios(asof_join(prices, funda))
    be = joined.panel("book_equity")[:, 0]
    assert np.isnan(be[:3]).all()
    np.testing.assert_array_equal(be[3:7], 100.0)
    np.testing.assert_array_equal(be[7:], 200.0)
    np.testing.assert_allclose(joined.panel("book_to_market")[7:, 0], 0.2)
