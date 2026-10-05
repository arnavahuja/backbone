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
DECEMBER: Final = 12


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
    right = (
        extra.frame.select([*C.KEY_COLUMNS, *fields])
        .rename({f: f"{prefix}{f}" for f in fields})
        .sort(C.TIMESTAMP)
    )
    left = prices.frame.sort(C.TIMESTAMP)
    joined = left.join_asof(right, on=C.TIMESTAMP, by=C.INSTRUMENT, strategy="backward")
    return MarketData(joined, prices.frequency, prices.instrument_meta, prices.metadata)


def derive_ratios(data: MarketData) -> MarketData:
    """Add common ratios when their inputs exist.

    * ``book_to_market``: book equity / current market cap.
    * ``book_to_market_dec``: book equity / market cap at the end of December of the fiscal
      year (Fama-French timing; needs ``fiscal_year``). Only bars at or after that December
      can see the value, so it never uses a future price.
    * ``gross_profitability``: (revenue - cost of goods sold) / total assets.
    """
    frame = data.frame
    cols = set(frame.columns)
    if {"book_equity", "market_cap"} <= cols:
        frame = frame.with_columns(
            pl.when(pl.col("market_cap") > 0)
            .then(pl.col("book_equity") * MILLIONS / pl.col("market_cap"))
            .otherwise(None)
            .alias("book_to_market")
        )
        if "fiscal_year" in cols:
            frame = _december_ratio(frame)
    if {"revenue", "cogs", "total_assets"} <= cols:
        frame = frame.with_columns(
            pl.when(pl.col("total_assets") > 0)
            .then((pl.col("revenue") - pl.col("cogs")) / pl.col("total_assets"))
            .otherwise(None)
            .alias("gross_profitability")
        )
    return MarketData(frame, data.frequency, data.instrument_meta, data.metadata)


def _december_ratio(frame: pl.DataFrame) -> pl.DataFrame:
    """Book equity over the December market cap of the fiscal year."""
    december = (
        frame.filter(pl.col(C.TIMESTAMP).dt.month() == DECEMBER)
        .with_columns(pl.col(C.TIMESTAMP).dt.year().cast(pl.Float64).alias("fiscal_year"))
        .sort(C.TIMESTAMP)
        .group_by([C.INSTRUMENT, "fiscal_year"])
        .agg(
            pl.col("market_cap").last().alias("_me_dec"),
            pl.col(C.TIMESTAMP).last().alias("_dec_ts"),
        )
    )
    joined = frame.join(december, on=[C.INSTRUMENT, "fiscal_year"], how="left")
    visible = pl.col("_dec_ts").is_not_null() & (pl.col("_dec_ts") <= pl.col(C.TIMESTAMP))
    return joined.with_columns(
        pl.when(visible & (pl.col("_me_dec") > 0))
        .then(pl.col("book_equity") * MILLIONS / pl.col("_me_dec"))
        .otherwise(None)
        .alias("book_to_market_dec")
    ).drop("_me_dec", "_dec_ts")
