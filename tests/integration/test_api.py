"""API end to end with fixture (synthetic) data and a thread-based job manager."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backbone.api.app import create_app
from backbone.core.config import Settings
from backbone.services.container import Services
from backbone.services.jobs import JobManager

API = "/api/v1"


@pytest.fixture
def client(tmp_path: Path):
    settings = Settings(data_dir=tmp_path / "data", user_plugins_dir=tmp_path / "up")
    services = Services.create(settings)
    jobs = JobManager(settings, max_workers=1, use_processes=False)
    app = create_app(services=services, jobs=jobs)
    with TestClient(app) as c:
        c.app_jobs = jobs  # type: ignore[attr-defined]
        yield c
    jobs.shutdown()


def _config(strategy: str = "sma_crossover", params: dict | None = None, name: str = "t"):
    return {
        "name": name,
        "data": {
            "source": "synthetic",
            "dataset": "gbm",
            "instruments": ["AAA", "BBB"],
            "start": "2018-01-01",
            "end": "2020-12-31",
        },
        "strategy": {
            "name": strategy,
            "params": params if params is not None else {"fast": 10, "slow": 50},
        },
        "costs": [{"name": "bps_notional", "params": {"bps": 5}}],
        "benchmark": "MKT",
        "experiment": "api-test",
    }


def _run(client: TestClient, config: dict) -> str:
    resp = client.post(f"{API}/runs", json={"config": config})
    assert resp.status_code == 202, resp.text
    body = resp.json()
    job = client.app_jobs.wait(body["job"]["id"], timeout=60)  # type: ignore[attr-defined]
    assert job.status.value == "completed", job.error
    return str(body["run"]["id"])


def test_plugins_expose_schema_and_health(client):
    plugins = client.get(f"{API}/plugins/strategy").json()
    sma = next(p for p in plugins if p["name"] == "sma_crossover")
    assert sma["params_schema"]["properties"]["fast"]["default"] == 20
    assert "vectorized" in sma["implements"]
    health = client.get(f"{API}/plugins/health").json()
    assert health["counts"]["strategy"] >= 3
    assert health["failures"] == []


def test_structured_errors(client):
    resp = client.get(f"{API}/runs/nope")
    assert resp.status_code == 404
    assert resp.json()["code"] == "not_found"
    bad = _config(params={"fast": 50, "slow": 10})
    resp = client.post(f"{API}/runs", json={"config": bad})
    assert resp.status_code == 422
    body = resp.json()
    assert body["code"] == "incompatible_config"
    assert "Traceback" not in resp.text
    resp = client.post(f"{API}/runs", json={"config": {"nope": 1}})
    assert resp.status_code == 422 and resp.json()["code"] == "validation_error"


def test_validate_endpoint(client):
    ok = client.post(f"{API}/runs/validate", json={"config": _config()}).json()
    assert ok["ok"] is True
    cfg = _config()
    cfg["execution"] = {"engine": "vectorized"}
    cfg["costs"] = []
    warn = client.post(f"{API}/runs/validate", json={"config": cfg}).json()
    assert any(i["level"] == "warning" for i in warn["issues"])


def test_full_run_flow(client):
    run_id = _run(client, _config())
    run = client.get(f"{API}/runs/{run_id}").json()
    assert run["status"] == "completed"
    metrics = client.get(f"{API}/runs/{run_id}/metrics").json()
    assert metrics["values"]["sharpe"]["value"] is not None
    assert any(d["key"] == "cagr" for d in metrics["descriptors"])
    charts = client.get(f"{API}/runs/{run_id}/charts").json()
    names = {c["name"] for c in charts}
    assert {"equity_curve", "drawdown_underwater", "monthly_heatmap"} <= names
    eq = client.get(f"{API}/runs/{run_id}/charts/equity_curve", params={"max_points": 100})
    spec = eq.json()
    assert spec["type"] == "line" and len(spec["series"][0]["data"]) <= 100
    assert spec["series"][1]["role"] == "benchmark"
    windowed = client.get(
        f"{API}/runs/{run_id}/metrics", params={"start": "2019-01-01", "end": "2019-12-31"}
    ).json()
    assert windowed["values"]["cagr"]["value"] != metrics["values"]["cagr"]["value"]
    trades = client.get(f"{API}/runs/{run_id}/trades").json()
    assert trades["total"] > 0
    positions = client.get(f"{API}/runs/{run_id}/positions").json()
    assert positions["equity"] > 0
    assert "completed" in client.get(f"{API}/runs/{run_id}/logs").text
    html = client.get(f"{API}/runs/{run_id}/export", params={"format": "html"})
    assert html.status_code == 200 and "<svg" in html.text
    csv = client.get(f"{API}/runs/{run_id}/export", params={"format": "csv"})
    names = zipfile.ZipFile(io.BytesIO(csv.content)).namelist()
    assert "series.csv" in names and "trades.csv" in names


def test_compare_five_runs_across_every_comparison_chart(client):
    variants = [
        ("sma_crossover", {"fast": 10, "slow": 50}),
        ("sma_crossover", {"fast": 20, "slow": 100}),
        ("buy_and_hold", {}),
        ("ts_momentum", {"lookback": 126}),
        ("mean_reversion", {}),
    ]
    ids = [_run(client, _config(s, p, name=f"r{k}")) for k, (s, p) in enumerate(variants)]
    table = client.post(f"{API}/compare/metrics", json={"run_ids": ids}).json()
    sharpe = next(r for r in table["rows"] if r["key"] == "sharpe")
    assert sharpe["best"] in ids and sharpe["worst"] in ids and sharpe["best"] != sharpe["worst"]
    charts = {c["name"] for c in client.get(f"{API}/compare/charts").json()}
    assert len(charts) >= 7
    for chart in sorted(charts):
        for align in (False, True):
            resp = client.post(
                f"{API}/compare/charts/{chart}", json={"run_ids": ids, "align": align}
            )
            assert resp.status_code == 200, (chart, resp.text)
            series_ids = {s.get("run_id") for s in resp.json()["series"]} - {None}
            assert series_ids <= set(ids)
    combo = client.post(
        f"{API}/compare/combine", json={"run_ids": ids, "weights": [0.2] * 5}
    ).json()
    assert combo["metrics"]["sharpe"]["value"] is not None
    assert len(combo["correlation"]) == 5
    aligned = client.post(f"{API}/compare/metrics", json={"run_ids": ids, "align": True})
    assert aligned.status_code == 200


def test_clone_labels_presets_delete(client):
    run_id = _run(client, _config())
    clone = client.post(
        f"{API}/runs/{run_id}/clone",
        json={"changes": {"strategy": {"params": {"fast": 15}}}, "run": False},
    )
    assert clone.json()["config"]["strategy"]["params"] == {"fast": 15, "slow": 50}
    upd = client.patch(f"{API}/runs/{run_id}", json={"name": "renamed", "tags": ["x"]}).json()
    assert upd["name"] == "renamed" and upd["tags"] == ["x"]
    assert client.get(f"{API}/runs", params={"tag": "x"}).json()[0]["id"] == run_id
    preset = client.post(f"{API}/presets", json={"name": "p1", "config": _config()}).json()
    assert client.get(f"{API}/presets").json()[0]["name"] == "p1"
    assert client.delete(f"{API}/presets/{preset['id']}").status_code == 204
    assert client.delete(f"{API}/runs/{run_id}").status_code == 204
    assert client.get(f"{API}/runs/{run_id}").status_code == 404


def test_data_import_via_upload_and_catalog(client):
    csv = b"Date,Close,Volume\n2021-01-04,10,100\n2021-01-05,11,120\n2021-01-06,12,90\n"
    resp = client.post(
        f"{API}/data/import/preview", files={"file": ("mydata.csv", csv, "text/csv")}
    )
    assert resp.status_code == 200, resp.text
    preview = resp.json()
    assert preview["mapping"]["columns"]["close"] == "Close"
    mapping = {**preview["mapping"], "fixed_symbol": "MYD"}
    record = client.post(
        f"{API}/data/import", json={"token": preview["token"], "mapping": mapping}
    ).json()
    assert record["instruments"] == ["MYD"]
    catalog = client.get(f"{API}/data/catalog").json()
    assert any(r["id"] == record["id"] for r in catalog)
    quality = client.get(f"{API}/data/datasets/{record['id']}/quality").json()
    assert quality["rows"] == 3
    prev = client.get(f"{API}/data/datasets/{record['id']}/preview").json()
    assert len(prev["rows"]) == 3


def test_job_websocket_streams_to_completion(client):
    resp = client.post(f"{API}/runs", json={"config": _config()})
    job_id = resp.json()["job"]["id"]
    with client.websocket_connect(f"{API}/ws/jobs/{job_id}") as ws:
        events = []
        while True:
            msg = ws.receive_json()
            events.append(msg)
            status = msg.get("job", {}).get("status")
            if status in ("completed", "failed", "cancelled"):
                break
    assert events[-1]["job"]["status"] == "completed"
    json.dumps(events)


def test_lookahead_endpoint(client):
    body = client.post(f"{API}/runs/lookahead-check", json={"config": _config()}).json()
    assert body["passed"] is True
