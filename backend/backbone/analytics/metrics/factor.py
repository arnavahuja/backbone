"""Factor exposure metrics (Fama-French 3/5 factors plus momentum)."""

from __future__ import annotations

from typing import ClassVar, Final

from backbone.analytics import stats as S
from backbone.analytics.stats import align_factors, ols
from backbone.core.interfaces import Metric, MetricContext, MetricOutput
from backbone.core.registry import register
from backbone.core.specs import MetricDescriptor, MetricKind
from backbone.core.specs import MetricFormat as F

GROUP = "Factor"
CAPM: Final = ("mkt_rf",)
FF3: Final = ("mkt_rf", "smb", "hml")
FF5_MOM: Final = ("mkt_rf", "smb", "hml", "rmw", "cma", "mom")


@register("metric", name="factor", version="1.0.0", tags=["factor"], capabilities={"needs:factors"})
class FactorMetrics(Metric):
    """Alpha and loadings versus CAPM, Fama-French 3 and 5 factors plus momentum.

    Needs daily factor returns in the metric context (from WRDS/Fama-French or an import
    with columns ``mkt_rf, smb, hml, rmw, cma, mom, rf``).
    """

    descriptors: ClassVar[tuple[MetricDescriptor, ...]] = (
        MetricDescriptor(
            key="capm_alpha",
            label="CAPM alpha (ann.)",
            group=GROUP,
            format=F.PERCENT,
            higher_is_better=True,
            benchmark=False,
        ),
        MetricDescriptor(
            key="capm_alpha_t",
            label="CAPM alpha t-stat",
            group=GROUP,
            format=F.NUMBER,
            higher_is_better=True,
            benchmark=False,
        ),
        MetricDescriptor(
            key="capm_beta", label="CAPM beta", group=GROUP, format=F.NUMBER, benchmark=False
        ),
        MetricDescriptor(
            key="capm_r2", label="CAPM R²", group=GROUP, format=F.PERCENT, benchmark=False
        ),
        MetricDescriptor(
            key="ff3_alpha",
            label="FF3 alpha (ann.)",
            group=GROUP,
            format=F.PERCENT,
            higher_is_better=True,
            benchmark=False,
        ),
        MetricDescriptor(
            key="ff3_alpha_t",
            label="FF3 alpha t-stat",
            group=GROUP,
            format=F.NUMBER,
            higher_is_better=True,
            benchmark=False,
        ),
        MetricDescriptor(
            key="ff3_mkt_beta",
            label="FF3 market beta",
            group=GROUP,
            format=F.NUMBER,
            benchmark=False,
        ),
        MetricDescriptor(
            key="ff5m_alpha",
            label="FF5+MOM alpha (ann.)",
            group=GROUP,
            format=F.PERCENT,
            higher_is_better=True,
            benchmark=False,
        ),
        MetricDescriptor(
            key="ff5m_alpha_t",
            label="FF5+MOM alpha t-stat",
            group=GROUP,
            format=F.NUMBER,
            higher_is_better=True,
            benchmark=False,
        ),
        MetricDescriptor(
            key="ff5m_r2", label="FF5+MOM R²", group=GROUP, format=F.PERCENT, benchmark=False
        ),
        MetricDescriptor(
            key="factor_table",
            label="Factor loadings",
            group=GROUP,
            kind=MetricKind.TABLE,
            benchmark=False,
        ),
    )

    def compute(self, ctx: MetricContext) -> dict[str, MetricOutput]:
        """Regress excess returns on factor returns."""
        empty: dict[str, MetricOutput] = {d.key: None for d in self.descriptors}
        if ctx.factors is None or ctx.is_benchmark:
            return empty
        ts = ctx.result.timestamps
        out = dict(empty)
        table: list[dict[str, object]] = []
        models = (("CAPM", CAPM, "capm"), ("FF3", FF3, "ff3"), ("FF5+MOM", FF5_MOM, "ff5m"))
        for label, names, prefix in models:
            aligned = align_factors(ts, ctx.returns, ctx.factors, names)
            if aligned is None:
                continue
            y, x, _ = aligned
            coef, t, r2 = ols(y, x)
            out[f"{prefix}_alpha"] = S.nan_to_none(coef[0] * ctx.periods_per_year)
            out[f"{prefix}_alpha_t"] = S.nan_to_none(t[0])
            if prefix == "capm":
                out["capm_beta"] = S.nan_to_none(coef[1])
                out["capm_r2"] = S.nan_to_none(r2)
            elif prefix == "ff3":
                out["ff3_mkt_beta"] = S.nan_to_none(coef[1])
            else:
                out["ff5m_r2"] = S.nan_to_none(r2)
            for name, c, tt in zip(("alpha", *names), coef, t, strict=True):
                table.append(
                    {
                        "model": label,
                        "factor": name,
                        "loading": float(c),
                        "t_stat": S.nan_to_none(float(tt)),
                    }
                )
        out["factor_table"] = table or None
        return out
