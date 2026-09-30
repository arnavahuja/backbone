"""Phase 7 acceptance, offline: cross-sectional momentum on CRSP with a survivorship-free,
point-in-time S&P 500 universe, joined fundamentals and factor attribution (fake WRDS)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from backbone.core.config import Settings
from backbone.core.run_config import BacktestConfig
from backbone.data.sources.wrds_crsp import WrdsSource
from backbone.services.container import Services
from tests.fixtures.fake_wrds import DELISTED, JOINS_LATE, FakeWrds


@pytest.fixture
def services(tmp_path: Path, monkeypatch) -> Services:
    fake = FakeWrds()
    monkeypatch.setattr(
        WrdsSource,
        "_query",
        lambda self, sql, params=None, date_cols=None: fake.query(sql, params, date_cols),
    )
    monkeypatch.setattr(WrdsSource, "available", lambda self: (True, ""))
    return Services.create(Settings(data_dir=tmp_path / "data", user_plugins_dir=tmp_path / "up"))


CONFIG = {
    "name": "xs momentum crsp",
    "data": {
        "source": "wrds",
        "dataset": "crsp_daily",
        "instruments": [],
        "universe": {"name": "index_membership", "params": {"index": "sp500"}},
        "start": "2017-06-01",
        "end": "2020-12-31",
        "adjustment": "total_return",
        "extra_datasets": ["wrds:compustat_annual"],
    },
    "strategy": {"name": "xs_momentum", "params": {"lookback": 126, "skip": 5}},
    "constructor": {"name": "quantile_long_short", "params": {"quantiles": 3, "min_names": 3}},
    "costs": [{"name": "bps_notional", "params": {"bps": 5}}],
    "factors": "wrds:ff_factors",
}


def test_crsp_momentum_with_pit_universe_and_factor_attribution(services):
    record = services.execute_run(BacktestConfig.model_validate(CONFIG))
    res = services.store.result(record.id)
    assert res.metadata["return_basis"].startswith("ret field")  # CRSP returns incl. dlret
    assert str(DELISTED) in res.instruments  # survivorship-free
    j = res.instruments.index(str(JOINS_LATE))
    before = res.timestamps.astype("datetime64[D]") < np.datetime64("2019-01-02")
    assert np.abs(res.target_weights[before, j]).max() == 0  # not tradable before joining
    d = res.instruments.index(str(DELISTED))
    after = res.timestamps.astype("datetime64[D]") > np.datetime64("2019-07-03")
    assert np.abs(res.weights[after, d]).max() == 0
    metrics = services.store.metrics(record.id)
    assert metrics["ff5m_alpha"].value is not None
    assert metrics["factor_table"].table
    for chart in ("factor_exposures", "rolling_factor_betas", "factor_attribution"):
        spec = services.results.chart([record.id], chart)
        assert spec.series and not spec.warnings, chart
    assert "extra:wrds:compustat_annual" in record.data_refs
    assert "factors" in record.data_refs


def test_synthetic_factors_offline(tmp_path: Path):
    services = Services.create(Settings(data_dir=tmp_path / "d", user_plugins_dir=tmp_path / "u"))
    cfg = BacktestConfig.model_validate(
        {
            "data": {
                "source": "synthetic",
                "dataset": "gbm",
                "instruments": ["AAA", "BBB"],
                "start": "2018-01-01",
                "end": "2020-12-31",
            },
            "strategy": {"name": "buy_and_hold"},
            "factors": "synthetic:ff_factors",
        }
    )
    record = services.execute_run(cfg)
    metrics = services.store.metrics(record.id)
    assert metrics["ff3_mkt_beta"].value == pytest.approx(0.8, abs=0.15)
