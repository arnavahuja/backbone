"""Hedging overlays: beta hedge, dollar and sector neutrality, pairs hedge, currency placeholder."""

from __future__ import annotations

import numpy as np
from pydantic import BaseModel, Field

from backbone.core import columns as C
from backbone.core.errors import ConfigError
from backbone.core.interfaces import Overlay, OverlayContext
from backbone.core.numeric import rolling_mean
from backbone.core.params import OverlayParams
from backbone.core.portfolio_math import simple_returns
from backbone.core.registry import register
from backbone.core.types import FloatArray, TargetFrame


def rolling_beta(y: FloatArray, x: FloatArray, window: int) -> FloatArray:
    """Trailing OLS beta of each column of ``y`` on the vector ``x`` (min 2/3 of window)."""
    xs = np.broadcast_to(x[:, None], y.shape)
    both = np.isfinite(y) & np.isfinite(xs)
    yy = np.where(both, y, np.nan)
    xx = np.where(both, xs, np.nan)
    minp = max(window * 2 // 3, 3)
    mx, my = rolling_mean(xx, window, minp), rolling_mean(yy, window, minp)
    cov = rolling_mean(xx * yy, window, minp) - mx * my
    var = rolling_mean(xx * xx, window, minp) - mx**2
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(var > 0, cov / var, np.nan)


def hedge_column(targets: TargetFrame, ctx: OverlayContext, instrument: str) -> tuple[str, int]:
    """Resolve the hedge instrument (param or benchmark) and its column."""
    hedge = instrument or ctx.benchmark
    if not hedge:
        raise ConfigError("Hedge overlay needs a hedge instrument or a benchmark")
    if hedge not in targets.instruments:
        raise ConfigError(
            f"Hedge instrument '{hedge}' is not in the data; add it to the "
            "instruments or set it as benchmark"
        )
    return hedge, targets.instruments.index(hedge)


class BetaHedgeParams(OverlayParams):
    """Beta hedge parameters."""

    hedge_instrument: str = Field("", description="Index future or ETF (default: benchmark)")
    window: int = Field(126, ge=20, le=1260, description="Beta estimation window (bars)")
    hedge_ratio: float = Field(1.0, ge=0, le=2, description="Fraction of beta to hedge")


@register(
    "overlay",
    name="beta_hedge",
    version="1.0.0",
    tags=["hedging"],
    capabilities={"engine:vectorized", "supports:short"},
)
class BetaHedge(Overlay):
    """Short the hedge instrument to neutralize the portfolio's trailing beta."""

    Params = BetaHedgeParams
    params: BetaHedgeParams

    def apply(self, targets: TargetFrame, ctx: OverlayContext) -> TargetFrame:
        """Hedge weight = -ratio x sum(w_i x beta_i)."""
        p = self.params
        hedge, j = hedge_column(targets, ctx, p.hedge_instrument)
        close = ctx.data.aligned_panel(C.CLOSE, targets.timestamps, targets.instruments)
        rets = simple_returns(close)
        betas = rolling_beta(rets, rets[:, j], p.window)
        w = targets.filled()
        w[:, j] = 0.0
        port_beta = np.nansum(np.nan_to_num(betas) * w, axis=1)
        w[:, j] = -p.hedge_ratio * port_beta
        ctx.notes.append(f"average hedge weight {float(w[:, j].mean()):.2f} in {hedge}")
        return targets.replace(values=w, extra_instruments=(*targets.extra_instruments, hedge))


class NeutralParams(OverlayParams):
    """Dollar neutrality parameters."""

    keep_gross: bool = Field(True, description="Rescale to the original gross exposure")


@register(
    "overlay",
    name="dollar_neutral",
    version="1.0.0",
    tags=["hedging"],
    capabilities={"engine:vectorized", "supports:short"},
)
class DollarNeutral(Overlay):
    """Demean active weights each bar so long and short dollars match."""

    Params = NeutralParams
    params: NeutralParams

    def apply(self, targets: TargetFrame, ctx: OverlayContext) -> TargetFrame:
        """Subtract the mean of active weights."""
        w = targets.filled()
        active = w != 0
        n = active.sum(axis=1, keepdims=True)
        with np.errstate(divide="ignore", invalid="ignore"):
            mean = np.where(n > 0, w.sum(axis=1, keepdims=True) / n, 0.0)
        out = np.where(active, w - mean, 0.0)
        if self.params.keep_gross:
            g0 = np.abs(w).sum(axis=1, keepdims=True)
            g1 = np.abs(out).sum(axis=1, keepdims=True)
            with np.errstate(divide="ignore", invalid="ignore"):
                out = np.where(g1 > 0, out * g0 / g1, 0.0)
        return targets.replace(values=out)


class SectorNeutralParams(OverlayParams):
    """Sector neutrality parameters."""

    field: str = Field("sector", description="Text data field with the group label")
    groups: dict[str, str] = Field(default_factory=dict, description="Explicit group map")


@register(
    "overlay",
    name="sector_neutral",
    version="1.0.0",
    tags=["hedging", "sector"],
    capabilities={"engine:vectorized", "supports:short"},
)
class SectorNeutral(Overlay):
    """Demean active weights within each sector so every sector is net flat."""

    Params = SectorNeutralParams
    params: SectorNeutralParams

    def apply(self, targets: TargetFrame, ctx: OverlayContext) -> TargetFrame:
        """Group-wise demeaning."""
        text = ctx.data.latest_text(self.params.field)
        labels = np.array(
            [self.params.groups.get(i) or text.get(i) or "other" for i in targets.instruments]
        )
        w = targets.filled()
        out = np.zeros_like(w)
        for g in np.unique(labels):
            cols = labels == g
            sub = w[:, cols]
            active = sub != 0
            n = active.sum(axis=1, keepdims=True)
            with np.errstate(divide="ignore", invalid="ignore"):
                mean = np.where(n > 1, sub.sum(axis=1, keepdims=True) / n, 0.0)
            out[:, cols] = np.where(active & (n > 1), sub - mean, 0.0)
        return targets.replace(values=out)


class Pair(BaseModel):
    """A hedged pair: positions in ``leg`` are hedged with ``hedge``."""

    leg: str
    hedge: str


class PairsHedgeParams(OverlayParams):
    """Pairs hedge parameters."""

    pairs: list[Pair] = Field(default_factory=list, description="Pairs to hedge")
    window: int = Field(126, ge=20, le=1260, description="Hedge ratio window (bars)")


@register(
    "overlay",
    name="pairs_hedge",
    version="1.0.0",
    tags=["hedging", "pairs"],
    capabilities={"engine:vectorized", "supports:short"},
)
class PairsHedge(Overlay):
    """For each pair, offset the leg's position with ``-beta`` of the hedge instrument."""

    Params = PairsHedgeParams
    params: PairsHedgeParams

    def apply(self, targets: TargetFrame, ctx: OverlayContext) -> TargetFrame:
        """Add hedge-instrument weights from trailing betas."""
        w = targets.filled()
        close = ctx.data.aligned_panel(C.CLOSE, targets.timestamps, targets.instruments)
        rets = simple_returns(close)
        for pair in self.params.pairs:
            if pair.leg not in targets.instruments or pair.hedge not in targets.instruments:
                raise ConfigError(f"Pair {pair.leg}/{pair.hedge} not in the data")
            i, j = targets.instruments.index(pair.leg), targets.instruments.index(pair.hedge)
            beta = rolling_beta(rets[:, [i]], rets[:, j], self.params.window)[:, 0]
            w[:, j] += -np.nan_to_num(beta) * w[:, i]
        return targets.replace(values=w)


class CurrencyParams(OverlayParams):
    """Currency hedge parameters (placeholder)."""

    hedge_ratio: float = Field(1.0, ge=0, le=1, description="Fraction of FX exposure to hedge")


@register("overlay", name="currency_hedge", version="0.1.0", tags=["hedging", "fx"])
class CurrencyHedge(Overlay):
    """Placeholder: v1 is USD-only, so there is no FX exposure to hedge (targets unchanged)."""

    Params = CurrencyParams
    params: CurrencyParams

    def apply(self, targets: TargetFrame, ctx: OverlayContext) -> TargetFrame:
        """Return targets unchanged and record why."""
        ctx.notes.append("USD-only in v1: no currency exposure to hedge")
        return targets
