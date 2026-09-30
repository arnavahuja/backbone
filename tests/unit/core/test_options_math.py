from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import numpy as np
import pandas as pd
import polars as pl
import pytest

from backbone.core.options_math import (
    RollingOption,
    bs_greeks,
    bs_price,
    chain_option_frame,
    implied_vol,
    rolling_option_index,
    select_by_delta,
)
from backbone.core.types import OptionRight
from backbone.data.sources.wrds_crsp import optionm_to_canonical


def test_put_call_parity_and_limits():
    s, k, t, r, v = 100.0, 95.0, 0.5, 0.03, 0.2
    call = float(bs_price(s, k, t, r, v, OptionRight.CALL))
    put = float(bs_price(s, k, t, r, v, OptionRight.PUT))
    assert call - put == pytest.approx(s - k * np.exp(-r * t), rel=1e-10)
    assert float(bs_price(s, k, 0.0, r, v, OptionRight.PUT)) == 0.0
    assert float(bs_price(90.0, k, 0.0, r, v, OptionRight.PUT)) == 5.0


def test_greeks_match_finite_differences():
    s, k, t, r, v = 100.0, 100.0, 0.25, 0.01, 0.3
    g = bs_greeks(s, k, t, r, v, OptionRight.CALL)
    h = 1e-4
    up = float(bs_price(s + h, k, t, r, v, OptionRight.CALL))
    dn = float(bs_price(s - h, k, t, r, v, OptionRight.CALL))
    mid = float(bs_price(s, k, t, r, v, OptionRight.CALL))
    assert float(g["delta"]) == pytest.approx((up - dn) / (2 * h), rel=1e-5)
    assert float(g["gamma"]) == pytest.approx((up - 2 * mid + dn) / h**2, rel=1e-3)
    vega_fd = (float(bs_price(s, k, t, r, v + h, OptionRight.CALL)) - mid) / h
    assert float(g["vega"]) == pytest.approx(vega_fd, rel=1e-3)
    theta_fd = (float(bs_price(s, k, t - h, r, v, OptionRight.CALL)) - mid) / h
    assert float(g["theta"]) == pytest.approx(theta_fd, rel=1e-3)


def test_implied_vol_round_trip():
    price = float(bs_price(100, 105, 0.3, 0.02, 0.27, OptionRight.PUT))
    assert implied_vol(price, 100, 105, 0.3, 0.02, OptionRight.PUT) == pytest.approx(0.27, 1e-6)
    assert np.isnan(implied_vol(1000.0, 100, 105, 0.3, 0.02, OptionRight.PUT))


def _series(n=200):
    ts = np.array(
        [np.datetime64("2020-01-01") + np.timedelta64(k, "D") for k in range(n)],
        dtype="datetime64[us]",
    )
    spot = 100 * np.exp(np.cumsum(np.random.default_rng(0).normal(0, 0.01, n)))
    return ts, spot


def test_rolling_index_returns_are_consistent():
    ts, spot = _series()
    spec = RollingOption(OptionRight.PUT, 0.95, 30, 30)
    idx = rolling_option_index(ts, spot, np.full(len(ts), 0.2), spec)
    assert idx.roll.sum() == 7
    assert (idx.price >= 0).all()
    t = 30  # roll bar: expired old put pays intrinsic on its own strike
    old_k = 0.95 * spot[0]
    intrinsic = max(old_k - spot[t], 0.0)
    assert idx.ret[t] == pytest.approx(intrinsic / idx.price[t - 1] - 1.0)
    within = 10  # ordinary bar: price ratio
    assert idx.ret[within] == pytest.approx(idx.price[within] / idx.price[within - 1] - 1.0)


def test_chain_pricing_matches_model_on_a_model_chain():
    ts, spot = _series(120)
    rows = []
    for i, t in enumerate(ts):
        d = t.astype("datetime64[D]").astype(date)
        for exp_off in (28, 56, 84):
            exp = d + timedelta(days=exp_off - (i % 28))
            for m in (0.9, 0.95, 1.0):
                k = round(m * spot[i] / 5) * 5
                tau = (exp - d).days / 365
                rows.append(
                    {
                        "timestamp": datetime.combine(d, datetime.min.time(), tzinfo=UTC),
                        "option_id": f"P{k}-{exp}",
                        "underlying": "SPX",
                        "right": "put",
                        "strike": float(k),
                        "expiry": exp.isoformat(),
                        "mid": float(bs_price(spot[i], k, tau, 0.0, 0.2, OptionRight.PUT)),
                        "delta": float(
                            bs_greeks(spot[i], k, tau, 0.0, 0.2, OptionRight.PUT)["delta"]
                        ),
                    }
                )
    chain = pl.DataFrame(rows)
    built = chain_option_frame(ts, "SPX", spot, chain, RollingOption(OptionRight.PUT, 0.95, 28, 20))
    assert built is not None
    frame, inst = built
    assert inst == "SPX:P95-28D"
    # the fixture only lists strikes near spot, so a held contract can drop out of the chain
    rets = frame.get_column("ret").drop_nulls()
    assert frame.height > 80 and rets.is_finite().mean() > 0.9
    picks = select_by_delta(chain, -0.3, OptionRight.PUT, 20, 40)
    assert picks.height > 0.7 * len(ts)  # some fixture days list no 20-40 DTE contract
    assert picks.get_column("dte").is_between(20, 40).all()


def test_optionmetrics_rows_to_chain():
    rows = pd.DataFrame(
        {
            "date": pd.to_datetime(["2020-01-02", "2020-01-02"]),
            "exdate": pd.to_datetime(["2020-01-17", "2020-01-17"]),
            "cp_flag": ["P", "C"],
            "strike_price": [320000, 330000],
            "best_bid": [1.0, 2.0],
            "best_offer": [1.2, 2.4],
            "impl_volatility": [0.15, 0.13],
            "delta": [-0.3, 0.4],
            "gamma": [0.01, 0.01],
            "vega": [20.0, 25.0],
            "theta": [-30.0, -28.0],
            "open_interest": [1000, 2000],
            "volume": [10, 20],
            "optionid": [111.0, 222.0],
            "ticker": ["SPY", "SPY"],
        }
    )
    chain, meta = optionm_to_canonical(rows)
    assert chain.get_column("strike").to_list() == [320.0, 330.0]
    assert chain.get_column("mid").to_list() == pytest.approx([1.1, 2.2])
    assert meta["111"].right.value == "put" and meta["111"].multiplier == 100.0


def test_ledger_settles_expired_options():
    from backbone.core.types import AssetClass, Instrument
    from backbone.engine.event.ledger import Ledger

    meta = {
        "SPY": Instrument(id="SPY", symbol="SPY"),
        "PUT": Instrument(
            id="PUT",
            symbol="PUT",
            asset_class=AssetClass.OPTION,
            multiplier=100.0,
            underlying="SPY",
            strike=300.0,
            expiry=date(2020, 3, 20),
            right=OptionRight.PUT,
        ),
    }
    ledger = Ledger(("PUT", "SPY"), meta, cash=0.0, cash_rate=0.0, periods_per_year=252)
    ledger.units[:] = [2.0, 0.0]
    moved = ledger.settle_expiries(np.datetime64("2020-03-20"), np.array([5.0, 280.0]))
    assert moved == pytest.approx(2 * 20 * 100)
    assert ledger.units[0] == 0 and ledger.cash == pytest.approx(4000.0)
