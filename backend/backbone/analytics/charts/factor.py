"""Factor charts: exposures, rolling betas, return attribution.

They need factor returns stored with the run (``config.factors``, e.g. ``wrds:ff_factors``).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import ClassVar, Final

import numpy as np
import polars as pl
from pydantic import Field

from backbone.analytics import chartkit as K
from backbone.analytics.stats import align_factors, ols
from backbone.core import columns as C
from backbone.core.interfaces import ChartBuilder, ChartInput
from backbone.core.params import ChartParams
from backbone.core.registry import register
from backbone.core.specs import Axis, AxisType, ChartSeries, ChartSpec, ChartType, MetricFormat
from backbone.core.types import FloatArray, TimeArray, np_times

FACTORS: Final = ("mkt_rf", "smb", "hml", "rmw", "cma", "mom")


def _factors(run: ChartInput) -> pl.DataFrame | None:
    frame = run.extras.get("factors")
    return frame if isinstance(frame, pl.DataFrame) else None


def available(frame: pl.DataFrame) -> tuple[str, ...]:
    """Factor columns present in the frame."""
    return tuple(f for f in FACTORS if f in frame.columns)


def aligned(run: ChartInput) -> tuple[TimeArray, FloatArray, FloatArray, tuple[str, ...]] | None:
    """``(dates, excess returns, factor matrix, names)`` on common dates."""
    frame = _factors(run)
    if frame is None:
        return None
    names = available(frame)
    res = run.result
    got = align_factors(res.timestamps, res.returns, frame, names)
    if got is None:
        return None
    y, x, _ = got
    f_dates = np_times(frame.get_column(C.TIMESTAMP)).astype("datetime64[D]")
    common = np.intersect1d(res.timestamps.astype("datetime64[D]"), f_dates)
    return common[-len(y) :].astype("datetime64[us]"), y, x, names


class _FactorChart(ChartBuilder):
    group: ClassVar[str] = "Factor"
    scopes: ClassVar[frozenset[str]] = frozenset({"single"})

    def applicable(self, runs: Sequence[ChartInput]) -> bool:
        """Needs factor returns stored with the run."""
        return bool(runs) and _factors(runs[0]) is not None


@register("chart", name="factor_exposures", version="1.0.0", tags=["factor"])
class FactorExposures(_FactorChart):
    """Full-sample factor loadings (bars), with t-statistics in the labels."""

    title: ClassVar[str] = "Factor exposures"

    def build(self, runs: Sequence[ChartInput]) -> ChartSpec:
        """OLS of excess returns on all available factors."""
        got = aligned(runs[0])
        if got is None:
            return ChartSpec(
                id="factor_exposures",
                title=self.title,
                type=ChartType.BAR,
                warnings=["Not enough overlapping factor data"],
            )
        _, y, x, names = got
        coef, t, r2 = ols(y, x)
        labels = [f"{n} (t={tv:.1f})" for n, tv in zip(names, t[1:], strict=True)]
        return ChartSpec(
            id="factor_exposures",
            title=f"{self.title} (R² {r2:.0%})",
            type=ChartType.BAR,
            x_axis=Axis(type=AxisType.CATEGORY, categories=labels),
            y_axes=[Axis(name="Loading", format=MetricFormat.NUMBER)],
            series=[
                ChartSeries(
                    name="Loading",
                    data=[[lab, float(c)] for lab, c in zip(labels, coef[1:], strict=True)],
                )
            ],
            options={"color_by_sign": True},
        )


class RollingBetaParams(ChartParams):
    """Rolling window."""

    window: int = Field(126, ge=30, le=1260, description="Window in bars")


@register("chart", name="rolling_factor_betas", version="1.0.0", tags=["factor", "rolling"])
class RollingFactorBetas(_FactorChart):
    """Trailing multivariate factor loadings."""

    Params = RollingBetaParams
    params: RollingBetaParams
    title: ClassVar[str] = "Rolling factor betas"

    def build(self, runs: Sequence[ChartInput]) -> ChartSpec:
        """Rolling OLS (one small solve per bar)."""
        got = aligned(runs[0])
        spec = ChartSpec(
            id="rolling_factor_betas",
            title=self.title,
            type=ChartType.LINE,
            x_axis=K.time_axis(),
            y_axes=[K.value_axis("Beta", MetricFormat.NUMBER)],
            time_series=True,
        )
        if got is None:
            return spec.model_copy(update={"warnings": ["Not enough overlapping factor data"]})
        dates, y, x, names = got
        w = self.params.window
        betas = np.full((len(y), len(names)), np.nan)
        design = np.column_stack([np.ones(len(y)), x])
        for t in range(w - 1, len(y)):
            coef, *_ = np.linalg.lstsq(design[t - w + 1 : t + 1], y[t - w + 1 : t + 1], rcond=None)
            betas[t] = coef[1:]
        series = [K.time_series(n, dates, betas[:, k]) for k, n in enumerate(names)]
        return spec.model_copy(update={"series": series, "title": f"{self.title} ({w} bars)"})


@register("chart", name="factor_attribution", version="1.0.0", tags=["factor"])
class FactorAttribution(_FactorChart):
    """Cumulative return attributed to each factor, alpha and residual (full-sample betas)."""

    title: ClassVar[str] = "Return attribution"

    def build(self, runs: Sequence[ChartInput]) -> ChartSpec:
        """Contribution_t = beta_k x factor_k,t; alpha; residual; cumulated additively."""
        got = aligned(runs[0])
        spec = ChartSpec(
            id="factor_attribution",
            title=self.title,
            type=ChartType.LINE,
            x_axis=K.time_axis(),
            y_axes=[K.value_axis("Cumulative contribution", MetricFormat.PERCENT)],
            time_series=True,
        )
        if got is None:
            return spec.model_copy(update={"warnings": ["Not enough overlapping factor data"]})
        dates, y, x, names = got
        coef, _, _ = ols(y, x)
        contrib = x * coef[1:]
        alpha = np.full(len(y), coef[0])
        resid = y - contrib.sum(axis=1) - alpha
        series = [K.time_series(n, dates, np.cumsum(contrib[:, k])) for k, n in enumerate(names)]
        series.append(K.time_series("alpha", dates, np.cumsum(alpha)))
        series.append(K.time_series("residual", dates, np.cumsum(resid)))
        series.append(K.time_series("total (excess)", dates, np.cumsum(y)))
        return spec.model_copy(update={"series": series})
