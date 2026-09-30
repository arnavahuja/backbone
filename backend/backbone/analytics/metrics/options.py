"""Option hedge metrics: what the option legs cost and what they delivered."""

from __future__ import annotations

from typing import ClassVar

import numpy as np
from pydantic import Field

from backbone.analytics import stats as S
from backbone.analytics.options_stats import non_option_pnl, option_columns, option_pnl
from backbone.core.interfaces import Metric, MetricContext, MetricOutput
from backbone.core.params import MetricParams
from backbone.core.registry import register
from backbone.core.specs import MetricDescriptor
from backbone.core.specs import MetricFormat as F

GROUP = "Options"


class OptionMetricParams(MetricParams):
    """Parameters."""

    stress_drawdown: float = Field(
        0.10, gt=0, lt=1, description="Drawdown of the unhedged book defining stress"
    )


def _d(key: str, label: str, fmt: F, hib: bool | None = True) -> MetricDescriptor:
    return MetricDescriptor(
        key=key, label=label, group=GROUP, format=fmt, higher_is_better=hib, benchmark=False
    )


@register("metric", name="options_hedge", version="1.0.0", tags=["options"])
class OptionHedgeMetrics(Metric):
    """Hedge cost (carry of option legs) versus protection delivered in stress periods."""

    Params = OptionMetricParams
    params: OptionMetricParams
    descriptors: ClassVar[tuple[MetricDescriptor, ...]] = (
        _d("option_pnl_total", "Option legs P&L", F.CURRENCY),
        _d("option_cost_per_year", "Option carry per year (% equity)", F.PERCENT),
        _d("option_pnl_in_stress", "Option P&L in stress periods", F.CURRENCY),
        _d("option_pnl_outside_stress", "Option P&L outside stress", F.CURRENCY),
        _d("hedge_efficiency", "Stress payoff / total carry", F.RATIO),
        _d("model_priced", "Model-priced options (1 = yes)", F.INTEGER, None),
    )

    def compute(self, ctx: MetricContext) -> dict[str, MetricOutput]:
        """Split option P&L between stress (unhedged drawdown) and calm periods."""
        res = ctx.result
        empty: dict[str, MetricOutput] = {d.key: None for d in self.descriptors}
        if ctx.is_benchmark or not option_columns(res):
            return empty
        opt = option_pnl(res)
        base = non_option_pnl(res)
        unhedged = res.initial_capital + np.cumsum(base)
        dd = unhedged / np.maximum.accumulate(unhedged) - 1.0
        stress = dd <= -self.params.stress_drawdown
        years = res.n_bars / ctx.periods_per_year
        calm = float(opt[~stress].sum())
        avg_eq = float(np.mean(res.equity))
        in_stress = float(opt[stress].sum())
        return {
            "option_pnl_total": float(opt.sum()),
            "option_cost_per_year": S.nan_to_none(calm / years / avg_eq) if years else None,
            "option_pnl_in_stress": in_stress,
            "option_pnl_outside_stress": calm,
            "hedge_efficiency": S.nan_to_none(in_stress / -calm) if calm < 0 else None,
            "model_priced": 1.0 if res.metadata.get("data", {}).get("model_priced") else 0.0,
        }
