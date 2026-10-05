"""Monthly CRSP factor portfolios end to end (fake WRDS): share-code universe, size filter,
value-weighted capped deciles, risk-free cash, CAPM, cross-source benchmark, comparison report."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backbone.api.app import create_app
from backbone.core.config import Settings
from backbone.core.run_config import BacktestConfig
from backbone.data.sources.wrds_crsp import WrdsSource
from backbone.services.container import Services
from backbone.services.jobs import JobManager
from tests.fixtures.fake_wrds import FakeWrds

API = "/api/v1"
NON_COMMON = "10002"


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


def _config(strategy: dict[str, Any], name: str, **extra: Any) -> dict[str, Any]:
    cfg: dict[str, Any] = {
        "name": name,
        "data": {
            "source": "wrds",
            "dataset": "crsp_monthly",
            "frequency": "1mo",
            "adjustment": "raw",
            "universe": {
                "name": "market_cap_top_n",
                "params": {"top_n": 4, "min_price": 5, "source_universe": "crsp_common"},
            },
            "start": "2017-01-01",
            "end": "2020-12-31",
            "extra_datasets": ["wrds:compustat_annual"],
        },
        "strategy": strategy,
        "constructor": {
            "name": "quantile_long_short",
            "params": {
                "quantiles": 2,
                "min_names": 2,
                "gross": 2.0,
                "weighting": "value",
                "max_leg_weight": 0.6,
            },
        },
        "costs": [
            {"name": "bps_notional", "params": {"bps": 10}},
            {"name": "short_borrow_fee", "params": {"annual_rate": 0.005}},
        ],
        "execution": {"rebalance": "every_bar"},
        "factors": "wrds:ff_factors",
        "risk_free": "wrds:ff_factors:rf",
        "benchmark": "wrds:crsp_index:CRSP_VW",
    }
    cfg.update(extra)
    return cfg


MOMENTUM = {"name": "trailing_return", "params": {"lookback": 5, "skip": 1}}
VALUE = {"name": "field_signal", "params": {"field": "book_to_market_dec", "min_value": 0}}
COMPOSITE = {
    "name": "composite_signal",
    "params": {
        "components": [
            {"strategy": "trailing_return", "params": {"lookback": 5, "skip": 1}},
            {"strategy": "field_signal", "params": {"field": "gross_profitability"}},
        ]
    },
}


def test_monthly_long_short_on_crsp(services):
    record = services.execute_run(BacktestConfig.model_validate(_config(MOMENTUM, "mom")))
    res = services.store.result(record.id)
    assert NON_COMMON not in res.instruments  # share code filter at the source
    assert res.benchmark_returns is not None and np.isfinite(res.benchmark_returns[1:]).all()
    assert res.risk_free is not None and res.risk_free[1:].min() > 0
    w = res.weights
    traded = np.abs(w).sum(axis=1) > 0
    assert traded.any()
    longs = np.clip(w, 0, None).sum(axis=1)[traded]
    shorts = -np.clip(w, None, 0).sum(axis=1)[traded]
    # each leg is 100% at rebalance; drift and a delisted short can move single bars
    assert (np.abs(longs - 1.0) < 0.15).mean() > 0.9
    assert (np.abs(shorts - 1.0) < 0.15).mean() > 0.9
    targets = res.target_weights[traded]
    assert np.abs(targets).max() <= 0.6 + 1e-9  # per-name cap within a leg
    assert res.costs["borrow"].sum() > 0
    metrics = services.store.metrics(record.id)
    assert metrics["capm_alpha"].value is not None  # monthly factors matched by month
    assert metrics["capm_beta"].value is not None
    assert "risk_free" in record.data_refs and "benchmark" in record.data_refs


@pytest.mark.parametrize("strategy", [VALUE, COMPOSITE], ids=["value", "composite"])
def test_fundamental_signals_run(services, strategy):
    record = services.execute_run(BacktestConfig.model_validate(_config(strategy, "f")))
    res = services.store.result(record.id)
    assert (np.abs(res.weights).sum(axis=1) > 0).any()


def test_comparison_report(services, tmp_path):
    ids = [
        services.execute_run(BacktestConfig.model_validate(_config(MOMENTUM, "mom"))).id,
        services.execute_run(BacktestConfig.model_validate(_config(VALUE, "value"))).id,
    ]
    settings = services.settings
    jobs = JobManager(settings, max_workers=1, use_processes=False)
    app = create_app(services=services, jobs=jobs)
    body = {
        "run_ids": ids,
        "periods": [
            {"label": "early", "start": "2017-01-01", "end": "2018-12-31"},
            {"label": "late", "start": "2019-01-01", "end": "2020-12-31"},
        ],
        "crisis_windows": [{"label": "covid", "start": "2020-02-01", "end": "2020-04-30"}],
        "cost_levels_bps": [0, 10, 30],
        "rolling_window": 6,
    }
    with TestClient(app) as client:
        resp = client.post(f"{API}/compare/report", json=body)
    jobs.shutdown()
    assert resp.status_code == 200, resp.text
    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    names = set(zf.namelist())
    for f in (
        "returns.csv",
        "metrics.csv",
        "regressions.csv",
        "correlations.csv",
        "subperiods.csv",
        "crisis_table.csv",
        "annual_returns.csv",
        "cost_sensitivity.csv",
        "factor_correlations.csv",
        "holdings_count.csv",
        "cost_reconciliation.csv",
        "README.txt",
    ):
        assert f in names, f
    pngs = [n for n in names if n.endswith(".png")]
    assert len(pngs) == 6
    metrics = pd.read_csv(zf.open("metrics.csv"))
    assert set(metrics["variant"]) == {"gross", "net"}
    assert {"sharpe", "max_dd_peak", "avg_longs", "avg_shorts"} <= set(metrics.columns)
    returns = pd.read_csv(zf.open("returns.csv"))
    assert any("vol-scaled" in c for c in returns.columns)  # long-short runs are neutral
    costs = pd.read_csv(zf.open("cost_sensitivity.csv"))
    mom = costs[costs.strategy == "mom"].sort_values("one_way_bps")
    assert mom["net_ann_return_arithmetic"].is_monotonic_decreasing
    recon = pd.read_csv(zf.open("cost_reconciliation.csv"))
    assert recon["max_abs_difference"].max() < 1e-9
    regs = pd.read_csv(zf.open("regressions.csv"))
    assert set(regs["model"]) == {"CAPM", "FF5+MOM"}
