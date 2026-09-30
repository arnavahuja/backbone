"""Options charts: payoff diagram, Greeks over time, hedge cost vs protection delivered."""

from __future__ import annotations

from collections.abc import Sequence
from typing import ClassVar, Final

import numpy as np

from backbone.analytics import chartkit as K
from backbone.analytics.options_stats import non_option_pnl, option_columns, option_pnl
from backbone.core.interfaces import ChartBuilder, ChartInput
from backbone.core.options_math import DAYS_PER_YEAR
from backbone.core.registry import register
from backbone.core.specs import (
    Annotation,
    AnnotationKind,
    Axis,
    AxisType,
    ChartSeries,
    ChartSpec,
    ChartType,
    MetricFormat,
    SeriesRole,
)

MOVES: Final = np.linspace(-0.4, 0.4, 81)
VOL_POINT: Final = 0.01


class _OptionsChart(ChartBuilder):
    group: ClassVar[str] = "Options"
    scopes: ClassVar[frozenset[str]] = frozenset({"single"})

    def applicable(self, runs: Sequence[ChartInput]) -> bool:
        """Needs option positions."""
        return bool(runs) and bool(option_columns(runs[0].result))


@register("chart", name="option_payoff", version="1.0.0", tags=["options"])
class OptionPayoff(_OptionsChart):
    """Portfolio P&L at option expiry versus the underlying's move (latest positions)."""

    title: ClassVar[str] = "Payoff at expiry (latest positions)"

    def build(self, runs: Sequence[ChartInput]) -> ChartSpec:
        """Delta-one legs move linearly; option legs pay their intrinsic value."""
        res = runs[0].result
        t = res.n_bars - 1
        equity = float(res.equity[t])
        strikes = res.aux.get("strike")
        pnl = np.zeros_like(MOVES)
        underlyings: set[str] = set()
        for j, meta in option_columns(res):
            und = meta.get("underlying")
            if und not in res.instruments or strikes is None:
                continue
            underlyings.add(und)
            u = res.instruments.index(und)
            spot = float(res.prices[t, u])
            units = float(res.positions[t, j])
            k = float(strikes[t, j])
            end = spot * (1 + MOVES)
            payoff = (
                np.maximum(k - end, 0) if meta.get("right") == "put" else np.maximum(end - k, 0)
            )
            pnl += units * (payoff - float(res.prices[t, j])) / equity
        for und in underlyings:
            u = res.instruments.index(und)
            pnl += float(res.weights[t, u]) * MOVES
        moves = [float(m) for m in MOVES]
        return ChartSpec(
            id="option_payoff",
            title=self.title,
            type=ChartType.LINE,
            x_axis=Axis(type=AxisType.VALUE, name="Underlying move", format=MetricFormat.PERCENT),
            y_axes=[Axis(name="P&L / equity", format=MetricFormat.PERCENT)],
            series=[
                ChartSeries(
                    name="With options",
                    data=[[m, float(p)] for m, p in zip(moves, pnl, strict=True)],
                ),
                ChartSeries(
                    name="Underlying only",
                    role=SeriesRole.REFERENCE,
                    dashed=True,
                    data=[
                        [
                            m,
                            float(
                                sum(res.weights[t, res.instruments.index(u)] for u in underlyings)
                                * m
                            ),
                        ]
                        for m in moves
                    ],
                ),
            ],
            annotations=[Annotation(kind=AnnotationKind.VLINE, value=0.0, label="spot")],
        )


@register("chart", name="option_greeks", version="1.0.0", tags=["options"])
class OptionGreeks(_OptionsChart):
    """Portfolio delta (as % of equity), vega per vol point and theta per day."""

    title: ClassVar[str] = "Greeks over time"

    def build(self, runs: Sequence[ChartInput]) -> ChartSpec:
        """Sum of units x Greek across option positions, plus delta-one underlyings."""
        res = runs[0].result
        eq = res.equity
        delta = np.zeros(res.n_bars)
        vega = np.zeros(res.n_bars)
        theta = np.zeros(res.n_bars)
        underlyings: set[str] = set()
        for j, meta in option_columns(res):
            und = meta.get("underlying")
            if und not in res.instruments:
                continue
            underlyings.add(und)
            spot = np.nan_to_num(res.prices[:, res.instruments.index(und)])
            units = res.positions[:, j]
            delta += (
                units * np.nan_to_num(res.aux.get("delta", np.zeros_like(res.prices))[:, j]) * spot
            )
            vega += (
                units
                * np.nan_to_num(res.aux.get("vega", np.zeros_like(res.prices))[:, j])
                * VOL_POINT
            )
            theta += (
                units
                * np.nan_to_num(res.aux.get("theta", np.zeros_like(res.prices))[:, j])
                / DAYS_PER_YEAR
            )
        for und in underlyings:
            delta += res.weights[:, res.instruments.index(und)] * eq
        vega_s = K.time_series("Vega (per vol point) / equity", res.timestamps, vega / eq)
        vega_s.y_axis = 1
        theta_s = K.time_series("Theta (per day) / equity", res.timestamps, theta / eq)
        theta_s.y_axis = 1
        return ChartSpec(
            id="option_greeks",
            title=self.title,
            type=ChartType.LINE,
            x_axis=K.time_axis(),
            y_axes=[
                K.value_axis("Delta / equity", MetricFormat.PERCENT),
                K.value_axis("Vega, theta / equity", MetricFormat.PERCENT),
            ],
            series=[K.time_series("Delta / equity", res.timestamps, delta / eq), vega_s, theta_s],
            time_series=True,
        )


@register("chart", name="hedge_cost_vs_protection", version="1.0.0", tags=["options"])
class HedgeCostVsProtection(_OptionsChart):
    """Cumulative option-leg P&L against the rest of the portfolio."""

    title: ClassVar[str] = "Hedge cost vs protection delivered"

    def build(self, runs: Sequence[ChartInput]) -> ChartSpec:
        """Option P&L (premium decay vs payoffs) and non-option P&L over time."""
        res = runs[0].result
        drawdown = K.time_series(
            "Portfolio drawdown", res.timestamps, res.drawdown, role=SeriesRole.NEGATIVE
        )
        drawdown.y_axis = 1
        return ChartSpec(
            id="hedge_cost_vs_protection",
            title=self.title,
            type=ChartType.LINE,
            x_axis=K.time_axis(),
            y_axes=[
                K.value_axis("Cumulative P&L", MetricFormat.CURRENCY),
                K.value_axis("Drawdown", MetricFormat.PERCENT),
            ],
            series=[
                K.time_series("Option legs P&L", res.timestamps, np.cumsum(option_pnl(res))),
                K.time_series(
                    "Rest of portfolio P&L",
                    res.timestamps,
                    np.cumsum(non_option_pnl(res)),
                    role=SeriesRole.REFERENCE,
                ),
                drawdown,
            ],
            time_series=True,
        )
