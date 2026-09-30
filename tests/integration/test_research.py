"""Research tools end to end through the API (thread-based jobs, synthetic data)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backbone.api.app import create_app
from backbone.core.config import Settings
from backbone.services.container import Services
from backbone.services.jobs import JobManager

API = "/api/v1"
CONFIG = {
    "name": "research",
    "data": {
        "source": "synthetic",
        "dataset": "gbm",
        "instruments": ["AAA", "BBB", "CCC"],
        "start": "2014-01-01",
        "end": "2020-12-31",
    },
    "strategy": {"name": "sma_crossover", "params": {"fast": 10, "slow": 50}},
    "costs": [{"name": "bps_notional", "params": {"bps": 10}}],
    "benchmark": "MKT",
    "experiment": "research-exp",
}


@pytest.fixture
def client(tmp_path: Path):
    settings = Settings(data_dir=tmp_path / "data", user_plugins_dir=tmp_path / "up", max_workers=2)
    jobs = JobManager(settings, max_workers=1, use_processes=False)
    app = create_app(services=Services.create(settings), jobs=jobs)
    with TestClient(app) as c:
        c.jobs = jobs  # type: ignore[attr-defined]
        yield c
    jobs.shutdown()


def _job(client: TestClient, path: str, body: dict) -> dict:
    resp = client.post(f"{API}{path}", json=body)
    assert resp.status_code == 202, resp.text
    job = client.jobs.wait(resp.json()["id"], timeout=120)  # type: ignore[attr-defined]
    assert job.status.value == "completed", job.error
    rid = job.result["run_id"]
    result = client.get(f"{API}/research/{rid}").json()
    assert result["kind"]
    return result


def test_sweep_walk_forward_monte_carlo_sensitivity(client):
    sweep = _job(
        client,
        "/research/sweep",
        {"config": CONFIG, "grid": {"fast": [5, 10, 20], "slow": [50, 100]}},
    )
    assert sweep["summary"]["trials"] == 6
    assert sweep["summary"]["pbo"] is not None
    assert sweep["summary"]["deflated_sharpe_best"] is not None
    ids = {c["id"] for c in sweep["charts"]}
    assert {"parameter_heatmap", "bootstrap_sharpe", "sweep_top_equity"} <= ids
    assert len(sweep["tables"][0]["rows"]) == 6

    rnd = _job(
        client,
        "/research/sweep",
        {
            "config": CONFIG,
            "random": {"space": {"fast": {"min": 5, "max": 30, "type": "int"}}, "n": 5},
            "seed": 1,
        },
    )
    assert rnd["summary"]["trials"] == 5
    # sweep trials count towards the experiment's deflated Sharpe
    assert rnd["summary"]["experiment_trials"] >= 11

    wf = _job(
        client,
        "/research/walk-forward",
        {
            "config": CONFIG,
            "grid": {"fast": [5, 20], "slow": [50, 100]},
            "train_bars": 504,
            "test_bars": 126,
        },
    )
    assert wf["summary"]["windows"] >= 5
    assert {c["id"] for c in wf["charts"]} == {"walk_forward_equity", "walk_forward_is_oos"}

    run = client.post(f"{API}/runs", json={"config": CONFIG}).json()
    client.jobs.wait(run["job"]["id"], timeout=60)  # type: ignore[attr-defined]
    run_id = run["run"]["id"]
    mc = _job(client, "/research/monte-carlo", {"run_id": run_id, "n_paths": 300})
    assert 0 <= mc["summary"]["probability_of_loss"] <= 1
    mc_trades = _job(
        client, "/research/monte-carlo", {"run_id": run_id, "method": "trades", "n_paths": 200}
    )
    assert mc_trades["summary"]["method"] == "trades"

    cost = _job(
        client,
        "/research/sensitivity",
        {"config": CONFIG, "kind": "cost", "multiples": [0, 1, 5, 20, 50]},
    )
    rows = cost["tables"][0]["rows"]
    assert rows[0]["cagr"] > rows[-1]["cagr"]
    delay = _job(
        client, "/research/sensitivity", {"config": CONFIG, "kind": "delay", "delays": [0, 1, 3]}
    )
    assert len(delay["tables"][0]["rows"]) == 3
    cap = _job(
        client,
        "/research/sensitivity",
        {"config": CONFIG, "kind": "capacity", "capitals": [1e5, 1e9, 1e11]},
    )
    cap_rows = cap["tables"][0]["rows"]
    assert cap_rows[0]["cagr"] > cap_rows[-1]["cagr"]  # impact grows with capital

    regimes = client.get(f"{API}/research/regimes/{run_id}").json()
    dims = {r["dimension"] for r in regimes["tables"][0]["rows"]}
    assert dims == {"year", "trend", "volatility"}
    listed = client.get(f"{API}/research").json()
    assert len(listed) >= 8


def test_test_period_lock_and_unlock(client):
    cfg = {**CONFIG, "split": {"train_end": "2018-12-31", "validation_end": "2019-12-31"}}
    run = client.post(f"{API}/runs", json={"config": cfg}).json()
    client.jobs.wait(run["job"]["id"], timeout=60)  # type: ignore[attr-defined]
    rid = run["run"]["id"]
    assert "Test period locked" in client.get(f"{API}/runs/{rid}/logs").text
    end = client.get(f"{API}/runs/{rid}/positions").json()["timestamp"]
    assert end.startswith("2019-12")
    unlocked = client.post(f"{API}/research/unlock-test/{rid}").json()
    assert unlocked["split"]["test_unlocked"] is True
