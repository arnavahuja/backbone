from __future__ import annotations

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.extra.numpy import arrays

from backbone.analytics import stats as S
from backbone.core.interfaces import OverlayContext
from backbone.core.registry import registry
from backbone.core.types import TargetFrame
from backbone.engine.base import RunOptions
from backbone.engine.pipeline import NamedOverlay, Pipeline
from backbone.engine.returns import compute_returns
from backbone.engine.vectorized import VectorizedEngine
from tests.helpers import PPY, config, make_market, synthetic

DATA = synthetic(instruments=("AAA", "BBB", "CCC", "MKT"))
T = len(DATA.timestamps)
CFG = config()


def _ctx(data=DATA, targets_fn=None) -> OverlayContext:
    engine = VectorizedEngine()
    sim = engine.simulate_zero_cost(CFG, data, compute_returns(data), PPY, None)
    return OverlayContext(data, PPY, "MKT", 1, sim, [])


def _overlay(name, **params):
    return registry("overlay").get(name).create(params)


def _targets(values=None, data=DATA) -> TargetFrame:
    shape = (len(data.timestamps), len(data.instruments))
    vals = np.full(shape, 1.0 / shape[1]) if values is None else values
    return TargetFrame(data.timestamps, data.instruments, vals)


@settings(max_examples=40, deadline=None)
@given(
    w=arrays(np.float64, (30, 4), elements=st.floats(-3, 3)),
    cap=st.floats(0.05, 1.0),
    gross=st.floats(0.2, 3.0),
)
def test_limit_overlays_respect_caps(w, cap, gross):
    data = make_market({k: list(np.linspace(10, 11, 30)) for k in "ABCD"})
    tf = _targets(w, data)
    ctx = OverlayContext(data, PPY, None, 1, lambda t: np.zeros(30), [])
    capped = _overlay("max_position_weight", max_weight=cap).apply(tf, ctx).values
    assert np.abs(capped).max() <= cap + 1e-12
    lev = _overlay("leverage_cap", max_leverage=gross).apply(tf, ctx).values
    assert np.abs(lev).sum(axis=1).max() <= gross + 1e-9
    lim = (
        _overlay("exposure_limits", max_gross=gross, max_net=0.5, min_net=-0.5)
        .apply(tf, ctx)
        .values
    )
    assert np.abs(lim).sum(axis=1).max() <= gross + 1e-9
    net = lim.sum(axis=1)
    assert net.max() <= 0.5 + 1e-9 and net.min() >= -0.5 - 1e-9
    turn = _overlay("turnover_cap", max_turnover=0.1).apply(tf, ctx).values
    steps = np.abs(np.diff(np.vstack([np.zeros(4), turn]), axis=0)).sum(axis=1)
    assert steps.max() <= 0.2 + 1e-9


def test_vol_target_moves_realized_vol_towards_target():
    tf = _targets(np.column_stack([np.full(T, 2.0), np.zeros((T, 3))]))
    ctx = _ctx()
    out = _overlay("vol_target", target_vol=0.05, window=63).apply(tf, ctx)
    before = S.annualized_vol(ctx.simulate(tf)[200:], PPY)
    after = S.annualized_vol(ctx.simulate(out)[200:], PPY)
    assert abs(after - 0.05) < abs(before - 0.05)
    assert after == pytest.approx(0.05, rel=0.3)


def test_stop_loss_exits_and_stays_flat_until_new_signal():
    closes = [100, 100, 95, 85, 90, 120, 130]
    data = make_market({"A": closes})
    tf = TargetFrame(data.timestamps, ("A",), np.array([[1.0]] * 5 + [[0.0], [1.0]]))
    ctx = OverlayContext(data, PPY, None, 1, lambda t: np.zeros(7), [])
    out = _overlay("stop_loss", stop_pct=0.10).apply(tf, ctx).values[:, 0]
    np.testing.assert_array_equal(out, [1, 1, 1, 0, 0, 0, 1])


def test_trailing_take_profit_and_time_exit():
    closes = [100, 110, 120, 105, 104, 103]
    data = make_market({"A": closes})
    tf = TargetFrame(data.timestamps, ("A",), np.ones((6, 1)))
    ctx = OverlayContext(data, PPY, None, 1, lambda t: np.zeros(6), [])
    trail = _overlay("trailing_stop", trail_pct=0.10).apply(tf, ctx).values[:, 0]
    np.testing.assert_array_equal(trail, [1, 1, 1, 0, 0, 0])
    tp = _overlay("take_profit", target_pct=0.15).apply(tf, ctx).values[:, 0]
    np.testing.assert_array_equal(tp, [1, 1, 0, 0, 0, 0])
    te = _overlay("time_exit", max_bars=2).apply(tf, ctx).values[:, 0]
    np.testing.assert_array_equal(te, [1, 1, 0, 0, 0, 0])


def test_dollar_neutral_and_beta_hedge():
    ctx = _ctx()
    w = np.column_stack([np.full(T, 0.5), np.full(T, 0.3), np.full(T, -0.1), np.zeros(T)])
    neutral = _overlay("dollar_neutral").apply(_targets(w), ctx).values
    np.testing.assert_allclose(neutral.sum(axis=1), 0.0, atol=1e-12)
    long_only = _targets(np.column_stack([np.full((T, 3), 1 / 3), np.zeros(T)]))
    hedged = _overlay("beta_hedge", window=63).apply(long_only, ctx)
    assert hedged.values[200:, 3].mean() < -0.3  # shorts the market
    r_before = ctx.simulate(long_only)[200:]
    r_after = ctx.simulate(hedged)[200:]
    mkt = compute_returns(DATA).close_to_close[200:, 3]
    beta_before = S.relative_stats(r_before, mkt, PPY, 0).beta
    beta_after = S.relative_stats(r_after, mkt, PPY, 0).beta
    assert abs(beta_after) < 0.25 * abs(beta_before)


def test_drawdown_overlays_reduce_drawdown():
    ctx = _ctx()
    tf = _targets(np.column_stack([np.zeros((T, 3)), np.full(T, 2.0)]))
    base_dd = S.max_drawdown(ctx.simulate(tf))
    for name in ("drawdown_derisk", "circuit_breaker", "cppi"):
        out = _overlay(name).apply(tf, _ctx())
        assert S.max_drawdown(ctx.simulate(out)) > base_dd, name


def test_regime_filters_reduce_exposure():
    ctx = _ctx()
    tf = _targets()
    trend = _overlay("trend_filter", window=50).apply(tf, ctx).values
    assert np.abs(trend).sum() < np.abs(tf.values).sum()
    vol = _overlay("vol_regime_filter").apply(tf, ctx).values
    assert np.abs(vol).sum() < np.abs(tf.values).sum()


def test_pipeline_records_overlay_reports_and_changes_results():
    strat = registry("strategy").get("buy_and_hold").create()
    engine = VectorizedEngine()
    opts = RunOptions(
        periods_per_year=PPY, benchmark_id="MKT", strategy_instruments=("AAA", "BBB", "CCC")
    )
    plain = engine.run(CFG, DATA, strat, Pipeline(), opts)
    overlays = (
        NamedOverlay("vol_target", _overlay("vol_target", target_vol=0.05)),
        NamedOverlay("max_position_weight", _overlay("max_position_weight", max_weight=0.2)),
    )
    with_ov = engine.run(CFG, DATA, strat, Pipeline(None, overlays), opts)
    assert [r.name for r in with_ov.overlay_reports] == ["vol_target", "max_position_weight"]
    assert with_ov.overlay_reports[1].cells_changed > 0
    assert not np.allclose(plain.returns, with_ov.returns)
    assert np.abs(with_ov.target_weights).max() <= 0.2 + 1e-12
