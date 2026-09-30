"""Phase 9 acceptance: a futures trend follower and intraday strategies in the event engine."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from backbone.core.config import Settings
from backbone.core.run_config import BacktestConfig
from backbone.services.container import Services


@pytest.fixture
def services(tmp_path: Path) -> Services:
    return Services.create(Settings(data_dir=tmp_path / "d", user_plugins_dir=tmp_path / "u"))


def _futures(engine: str) -> BacktestConfig:
    return BacktestConfig.model_validate(
        {
            "data": {
                "source": "synthetic_markets",
                "dataset": "futures_continuous",
                "instruments": ["ES", "CL", "GC"],
                "start": "2016-01-01",
                "end": "2020-12-31",
            },
            "strategy": {"name": "futures_trend"},
            "costs": [{"name": "futures_per_contract", "params": {"per_contract": 2.5}}],
            "execution": {"engine": engine},
        }
    )


def test_futures_trend_runs_in_both_engines_with_roll_costs(services):
    ids = [services.execute_run(_futures(e)).id for e in ("vectorized", "event")]
    vec, evt = (services.store.result(i) for i in ids)
    assert evt.metadata["engine"] == "event"
    assert evt.costs["commission"].sum() > 0 and vec.costs["fees"].sum() > 0
    # both engines agree closely even with roll and contract fees
    assert abs(vec.equity[-1] / evt.equity[-1] - 1) < 0.02
    assert (np.abs(evt.positions) > 0).any()


def _intraday(strategy: str, params: dict | None = None) -> BacktestConfig:
    return BacktestConfig.model_validate(
        {
            "data": {
                "source": "synthetic_markets",
                "dataset": "gbm_intraday",
                "instruments": ["XYZ", "ABC"],
                "start": "2024-01-02",
                "end": "2024-02-29",
                "frequency": "5min",
            },
            "strategy": {"name": strategy, "params": params or {}},
            "costs": [{"name": "bps_notional", "params": {"bps": 1}}],
            "execution": {"engine": "event"},
        }
    )


def test_intraday_orb_is_flat_at_session_end(services):
    record = services.execute_run(_intraday("intraday_orb"))
    res = services.store.result(record.id)
    assert res.trades.height > 10
    days = res.timestamps.astype("datetime64[D]")
    last_bar_of_day = np.append(days[1:] != days[:-1], True)
    assert np.abs(res.weights[last_bar_of_day]).max() < 1e-12
    assert res.periods_per_year > 10_000  # intraday annualization


def test_daily_signals_with_intraday_execution(services):
    record = services.execute_run(
        _intraday("daily_trend_intraday", {"fast_days": 3, "slow_days": 8})
    )
    res = services.store.result(record.id)
    fills = res.fills
    assert fills.height > 0
    # every fill happens on the first or second bar of a session (decided on the first bar
    # after a daily bar completes, executed one bar later)
    minutes = [(t.hour * 60 + t.minute) for t in fills.get_column("timestamp").to_list()]
    assert all(m in (14 * 60 + 35, 14 * 60 + 40) for m in minutes)
