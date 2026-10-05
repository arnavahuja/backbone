"""Building blocks of factor and multi-asset portfolios."""

from __future__ import annotations

import numpy as np
import pandas as pd
import polars as pl
import pytest

from backbone.analytics.stats import align_series
from backbone.core import columns as C
from backbone.core.types import Frequency, MarketData
from backbone.data.fundamentals import derive_ratios
from backbone.data.sources.wrds_crsp import WrdsParams, book_equity, fill_delisting_returns
from backbone.portfolio.construction.quantile import leg_weights
from backbone.services.runner import splice_returns
from backbone.strategies.cross_sectional import TrailingReturn, trailing_return, winsorize_rows
from backbone.strategies.fixed_weights import FixedWeights
from backbone.strategies.trend_filter import TrendFilter


def _make(cls, params):
    return cls(params=cls.Params(**params))


def _monthly(
    values: dict[str, list[float]],
    field: str = C.CLOSE,
    start: str = "2020-01-31",
    extra: dict[str, dict[str, list[float]]] | None = None,
) -> MarketData:
    n = len(next(iter(values.values())))
    dates = pd.date_range(start, periods=n, freq="ME", tz="UTC")
    rows = []
    for inst, vals in values.items():
        for k, (d, v) in enumerate(zip(dates, vals, strict=True)):
            row = {C.TIMESTAMP: d.to_pydatetime(), C.INSTRUMENT: inst, field: v}
            for f, per in (extra or {}).items():
                row[f] = per[inst][k]
            rows.append(row)
    return MarketData(pl.DataFrame(rows), Frequency.MO1)


def test_trailing_return_window_and_skip():
    close = [100, 110, 121, 133.1, 146.41, 161.051]  # +10% every month
    data = _monthly({"A": close})
    out = trailing_return(data, lookback=2, skip=1)[:, 0]
    assert np.isnan(out[:3]).all()
    np.testing.assert_allclose(out[3:], 1.1**2 - 1)
    reversal = _make(TrailingReturn, {"lookback": 1, "skip": 0, "direction": "low"})
    sig = reversal.generate_targets(data).values[:, 0]
    np.testing.assert_allclose(sig[1:], -0.1)


def test_trailing_return_uses_ret_field_and_requires_full_window():
    data = _monthly(
        {"A": [10, 10, 10, 10]},
        field=C.CLOSE,
        extra={C.RETURN: {"A": [np.nan, 0.05, np.nan, 0.02]}},
    )
    out = trailing_return(data, lookback=1, skip=0)[:, 0]
    assert out[1] == pytest.approx(0.05)  # ret field wins (dividends, delistings)
    assert out[2] == pytest.approx(0.0)  # falls back to the price return when ret is missing


def test_winsorize_clips_tails_per_row():
    x = np.array([[1.0, 2.0, 3.0, 100.0, np.nan]])
    w = winsorize_rows(x, 0.25)
    assert w[0, 3] < 100 and np.isnan(w[0, 4])


def test_leg_weights_value_weighted_with_cap():
    member = np.array([[True, True, True, False]])
    size = np.array([[80.0, 15.0, 5.0, 1000.0]])
    w = leg_weights(member, size, cap=0.5)[0]
    assert w.sum() == pytest.approx(1.0)
    assert w[0] == pytest.approx(0.5) and w[3] == 0
    assert w[1] / w[2] == pytest.approx(3.0)  # excess spread pro rata


def test_fixed_weights_and_trend_filter():
    data = _monthly({"A": [1, 2, 3, 4], "B": [4, 3, 2, 1]})
    fw = _make(FixedWeights, {"weights": {"A": 0.6, "B": 0.4}}).generate_targets(data)
    np.testing.assert_allclose(fw.values, [[0.6, 0.4]] * 4)
    tf = _make(TrendFilter, {"window": 2}).generate_targets(data).values
    np.testing.assert_allclose(tf[1:], [[0.5, 0.0]] * 3)  # B below its average: cash
    active = _make(TrendFilter, {"window": 2, "weighting": "active"}).generate_targets(data)
    np.testing.assert_allclose(active.values[1:], [[1.0, 0.0]] * 3)


def test_delisting_fill_by_exchange():
    delist = pd.DataFrame(
        {
            "permno": [1, 2, 3, 4],
            "dlstdt": pd.to_datetime(["2020-01-15"] * 4),
            "dlret": [np.nan, np.nan, -0.1, np.nan],
            "dlstcd": [550, 560, 550, 233],
            "exchcd": [1, 3, 1, 1],
        }
    )
    out = fill_delisting_returns(delist, WrdsParams()).set_index("permno")["dlret"]
    assert out[1] == -0.30 and out[2] == -0.55 and out[3] == -0.1
    assert 4 not in out.index  # merger code: no fill, no row


def test_ff_book_equity_fallbacks():
    df = pd.DataFrame(
        {
            "seq": [100.0, np.nan, np.nan],
            "ceq": [0, 80.0, np.nan],
            "pstk": [10.0, 5.0, np.nan],
            "at": [0, 0, 300.0],
            "lt": [0, 0, 200.0],
            "txditc": [3.0, np.nan, 1.0],
            "pstkrv": [np.nan, np.nan, np.nan],
            "pstkl": [4.0, np.nan, np.nan],
        }
    )
    np.testing.assert_allclose(book_equity(df), [100 + 3 - 4, 80 + 5 - 5, 100 + 1])


def test_december_book_to_market_is_point_in_time():
    dates = pd.date_range("2019-11-30", periods=10, freq="ME", tz="UTC")
    frame = pl.DataFrame(
        {
            C.TIMESTAMP: [d.to_pydatetime() for d in dates],
            C.INSTRUMENT: ["A"] * 10,
            C.CLOSE: [1.0] * 10,
            "market_cap": [1e9 * (k + 1) for k in range(10)],
            "book_equity": [500.0] * 10,
            "fiscal_year": [2019.0] * 10,
        }
    )
    out = derive_ratios(MarketData(frame, Frequency.MO1)).panel("book_to_market_dec")[:, 0]
    assert np.isnan(out[0])  # November 2019: December not yet observed
    np.testing.assert_allclose(out[1:], 500e6 / 2e9)  # December 2019 market cap thereafter


def test_splice_extends_a_late_series_with_proxy_returns():
    main = _monthly({"A": [np.nan, np.nan, 100.0, 102.0]})
    main = MarketData(
        main.frame.drop_nulls(C.CLOSE).filter(pl.col(C.CLOSE).is_not_nan()), Frequency.MO1
    )
    grid_owner = _monthly({"B": [1.0, 1.0, 1.0, 1.0]})
    data = main.concat(grid_owner)
    # proxy dated at month start (another source): matched by month
    proxy_dates = pd.date_range("2020-01-01", periods=4, freq="MS", tz="UTC")
    proxy = MarketData(
        pl.DataFrame(
            {
                C.TIMESTAMP: [d.to_pydatetime() for d in proxy_dates],
                C.INSTRUMENT: ["P"] * 4,
                C.CLOSE: [1.0, 1.1, 1.21, 1.3],
                C.RETURN: [np.nan, 0.1, 0.1, 0.07],
            }
        ),
        Frequency.MO1,
    )
    out = splice_returns(data, "A", proxy, "P")
    close = out.panel(C.CLOSE)[:, out.instruments.index("A")]
    ret = out.panel(C.RETURN)[:, out.instruments.index("A")]
    np.testing.assert_allclose(close[:3], [100 / 1.1 / 1.1, 100 / 1.1, 100.0])
    assert ret[3] == pytest.approx(0.02)
    assert out.metadata["splices"]["A"]["series"] == "P"


def test_align_series_matches_months_when_days_differ():
    grid = np.array(["2020-01-31", "2020-02-28"], dtype="datetime64[ns]")
    other = np.array(["2020-01-01", "2020-02-01"], dtype="datetime64[ns]")
    np.testing.assert_allclose(align_series(grid, other, np.array([1.0, 2.0])), [1.0, 2.0])
