"""End-to-end runs: determinism, storage round trip, compatibility errors, CLI."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import yaml
from typer.testing import CliRunner

from backbone.core.config import Settings
from backbone.core.errors import CompatibilityError
from backbone.core.run_config import PluginRef
from backbone.services.container import Services
from tests.helpers import config


@pytest.fixture
def services(tmp_path: Path) -> Services:
    return Services.create(Settings(data_dir=tmp_path / "data", user_plugins_dir=tmp_path / "up"))


def _cfg():
    cfg = config("sma_crossover", {"fast": 10, "slow": 50}, instruments=("AAA", "BBB"))
    return cfg.model_copy(
        update={
            "costs": [PluginRef(name="bps_notional", params={"bps": 5})],
            "slippage": PluginRef(name="half_spread"),
            "benchmark": "MKT",
            "experiment": "exp1",
        }
    )


def test_same_config_gives_identical_results(services):
    a = services.execute_run(_cfg())
    b = services.execute_run(_cfg())
    ra, rb = services.store.result(a.id), services.store.result(b.id)
    np.testing.assert_array_equal(ra.equity, rb.equity)
    np.testing.assert_array_equal(ra.weights, rb.weights)
    assert a.config_hash == b.config_hash
    ma, mb = services.store.metrics(a.id), services.store.metrics(b.id)
    assert ma["sharpe"].value == mb["sharpe"].value
    # the second run of the experiment counts two trials
    assert services.store.trials("exp1")[0] == 2


def test_result_round_trip_and_provenance(services):
    record = services.execute_run(_cfg())
    res = services.store.result(record.id)
    assert res.benchmark_id == "MKT"
    assert res.benchmark_returns is not None
    assert "strategy:sma_crossover" in record.plugin_versions
    assert record.data_refs["main"]["cache_key"]
    assert record.headline["sharpe"] is not None
    assert "completed" in services.store.logs(record.id)
    assert services.store.metrics(record.id)["top_drawdowns"].table


def test_incompatible_config_is_rejected(services):
    bad = _cfg().model_copy(
        update={"strategy": PluginRef(name="sma_crossover", params={"fast": 50, "slow": 10})}
    )
    with pytest.raises(CompatibilityError) as info:
        services.execute_run(bad)
    assert info.value.details["issues"]


def test_cli_run(tmp_path: Path, monkeypatch):
    from backbone.cli import app

    monkeypatch.setenv("BACKBONE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("BACKBONE_USER_PLUGINS_DIR", str(tmp_path / "none"))
    path = tmp_path / "cfg.yaml"
    path.write_text(yaml.safe_dump(_cfg().model_dump(mode="json")))
    result = CliRunner().invoke(app, ["run", str(path)])
    assert result.exit_code == 0, result.output
    assert "completed" in result.output
