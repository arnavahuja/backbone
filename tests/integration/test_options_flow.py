"""Phase 10 acceptance: protective put overlay on an equity strategy with hedge cost reporting."""

from __future__ import annotations

from pathlib import Path

import pytest

from backbone.core.config import Settings
from backbone.core.run_config import BacktestConfig
from backbone.services.container import Services


@pytest.fixture
def services(tmp_path: Path) -> Services:
    return Services.create(Settings(data_dir=tmp_path / "d", user_plugins_dir=tmp_path / "u"))


BASE = {
    "data": {
        "source": "synthetic",
        "dataset": "gbm",
        "instruments": ["AAA", "BBB", "CCC"],
        "start": "2012-01-01",
        "end": "2020-12-31",
    },
    "strategy": {"name": "buy_and_hold"},
    "costs": [{"name": "bps_notional", "params": {"bps": 2}}],
    "benchmark": "MKT",
}


@pytest.mark.parametrize(
    "overlay", ["protective_put", "collar", "put_spread", "tail_hedge", "covered_call_overwrite"]
)
def test_option_overlays_run_with_hedge_reporting(services, overlay):
    cfg = BacktestConfig.model_validate({**BASE, "overlays": [{"name": overlay}]})
    record = services.execute_run(cfg)
    res = services.store.result(record.id)
    options = [i for i in res.instruments if ":" in i]
    assert options, "option instruments were added"
    j = res.instruments.index(options[0])
    assert abs(res.weights[:, j]).max() > 0
    metrics = services.store.metrics(record.id)
    assert metrics["option_pnl_total"].value is not None
    assert metrics["model_priced"].value == 1.0
    assert any("model-priced" in w for w in res.metadata["warnings"])
    for chart in ("option_payoff", "option_greeks", "hedge_cost_vs_protection"):
        spec = services.results.chart([record.id], chart)
        assert spec.series, chart
    assert "delta" in res.aux


def test_protective_put_delivers_protection_in_stress(services):
    plain = services.execute_run(BacktestConfig.model_validate(BASE))
    hedged = services.execute_run(
        BacktestConfig.model_validate(
            {**BASE, "overlays": [{"name": "protective_put", "params": {"moneyness": 0.95}}]}
        )
    )
    m_plain = services.store.metrics(plain.id)
    m_hedged = services.store.metrics(hedged.id)
    assert m_hedged["max_drawdown"].value > m_plain["max_drawdown"].value  # shallower
    assert m_hedged["option_pnl_in_stress"].value > 0
    assert m_hedged["option_cost_per_year"].value is not None


@pytest.mark.parametrize("strategy", ["covered_call", "protective_put_strategy"])
def test_option_strategies_run_in_both_engines(services, strategy):
    for engine in ("vectorized", "event"):
        cfg = BacktestConfig.model_validate(
            {**BASE, "strategy": {"name": strategy}, "execution": {"engine": engine}}
        )
        res = services.store.result(services.execute_run(cfg).id)
        assert any(":" in i for i in res.instruments)
