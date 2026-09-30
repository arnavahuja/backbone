"""Point-in-time joins of slower datasets (fundamentals) onto price data.

Fundamental rows are stamped with their public availability date. A backward as-of join per
instrument makes each value visible from that date on and never earlier, so strategies cannot
see a number before it was published.
"""

from __future__ import annotations

from typing import Final

import polars as pl

from backbone.core import columns as C
from backbone.core.types import MarketData

MILLIONS: Final = 1_000_000.0
"""Compustat reports amounts in millions."""


def asof_join(prices: MarketData, extra: MarketData, prefix: str = "") -> MarketData:
    """Join every field of ``extra`` onto ``prices`` using the latest row at or before each bar.

    Args:
        prices: Price data (defines the grid).
        extra: Data stamped at availability dates.
        prefix: Optional prefix for the joined field names.

    Returns:
        Prices with the extra fields added.
    """
    fields = [f for f in extra.fields if f not in prices.fields]
    if not fields or extra.is_empty():
        return prices
    right = extra.frame.select([*C.KEY_COLUMNS, *fields]).rename(
        {f: f"{prefix}{f}" for f in fields}
    ).sort(C.TIMESTAMP)
    left = prices.frame.sort(C.TIMESTAMP)
    joined = left.join_asof(right, on=C.TIMESTAMP, by=C.INSTRUMENT, strategy="backward")
    return MarketData(joined, prices.frequency, prices.instrument_meta, prices.metadata)


def derive_ratios(data: MarketData) -> MarketData:
    """Add common ratios when their inputs exist (book-to-market from equity and market cap)."""
    frame = data.frame
    if "book_equity" in frame.columns and "market_cap" in frame.columns:
        frame = frame.with_columns(
            pl.when(pl.col("market_cap") > 0)
            .then(pl.col("book_equity") * MILLIONS / pl.col("market_cap"))
            .otherwise(None)
            .alias("book_to_market")
        )
    return MarketData(frame, data.frequency, data.instrument_meta, data.metadata)
