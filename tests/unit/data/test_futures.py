from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from backbone.core import columns as C
from backbone.core.types import DataRequest, Frequency
from backbone.data.futures import ACTIVE_FIELD, ROLL_FIELD, BackAdjust, build_continuous
from backbone.data.sources.synthetic_markets import SyntheticMarkets
from backbone.data.sources.wrds_crsp import taq_sql, taq_to_canonical

SRC = SyntheticMarkets()
CONTRACTS = SRC.fetch(DataRequest(source="synthetic_markets", dataset="futures_contracts",
                                  instruments=("ES",), start=date(2018, 1, 1),
                                  end=date(2020, 12, 31)))


def _active_returns(cont):
    """Returns of the contract that was active on the previous bar (what a holder earns)."""
    active = cont.frame.get_column(ACTIVE_FIELD).to_list()
    close = CONTRACTS.panel(C.CLOSE)
    col = {c: CONTRACTS.instruments.index(c) for c in set(active)}
    rows = np.searchsorted(CONTRACTS.timestamps, cont.timestamps)
    out = [np.nan]
    for t in range(1, len(active)):
        j = col[active[t - 1]]
        out.append(close[rows[t], j] / close[rows[t - 1], j] - 1)
    return np.array(out)


@pytest.mark.parametrize("rule", ["fixed_days", "volume", "open_interest"])
def test_ratio_back_adjusted_returns_have_no_roll_gaps(rule):
    cont = build_continuous(CONTRACTS, "ES", rule, 5, BackAdjust.RATIO)
    close = cont.panel(C.CLOSE)[:, 0]
    rets = close[1:] / close[:-1] - 1
    np.testing.assert_allclose(rets, _active_returns(cont)[1:], rtol=1e-9)
    assert cont.panel(ROLL_FIELD).sum() >= 10  # quarterly rolls over three years
    assert cont.instrument_meta["ES"].multiplier == 50.0


def test_fixed_days_roll_happens_before_expiry():
    cont = build_continuous(CONTRACTS, "ES", "fixed_days", 7, BackAdjust.NONE)
    meta = CONTRACTS.instrument_meta
    for ts, contract in zip(cont.timestamps, cont.frame.get_column(ACTIVE_FIELD).to_list(),
                            strict=True):
        expiry = np.datetime64(meta[contract].expiry)
        assert ts.astype("datetime64[D]") < expiry - np.timedelta64(7, "D")


def test_difference_adjustment_keeps_point_moves():
    cont = build_continuous(CONTRACTS, "ES", "fixed_days", 5, BackAdjust.DIFFERENCE)
    raw = build_continuous(CONTRACTS, "ES", "fixed_days", 5, BackAdjust.NONE)
    diff = np.diff(cont.panel(C.CLOSE)[:, 0])
    raw_diff = np.diff(raw.panel(C.CLOSE)[:, 0])
    no_roll = raw.panel(ROLL_FIELD)[1:, 0] == 0
    np.testing.assert_allclose(diff[no_roll], raw_diff[no_roll], rtol=1e-9)


def test_taq_bars_are_converted_to_utc():
    rows = pd.DataFrame({"sym_root": ["AAPL", "AAPL"], "bucket": [34200 / 300, 34500 / 300],
                         "open": [10.0, 11.0], "high": [11.0, 12.0], "low": [9.0, 10.5],
                         "close": [10.5, 11.5], "volume": [100, 200]})
    frame = taq_to_canonical(rows, date(2020, 1, 2), 5)
    assert str(frame.get_column(C.TIMESTAMP)[0]) == "2020-01-02 14:30:00+00:00"
    assert "taqm_2020.ctm_20200102" in taq_sql(date(2020, 1, 2), 5)


def test_intraday_periods_per_year():
    from backbone.core.calendar import TradingCalendar

    cal = TradingCalendar()
    assert cal.periods_per_year(Frequency.MIN5) == pytest.approx(cal.sessions_per_year() * 78)
