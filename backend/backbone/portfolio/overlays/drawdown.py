"""Drawdown control overlays: de-risking by drawdown level, circuit breaker, CPPI.

These rules depend on the *controlled* equity path, which depends on the rule itself, so
they iterate over bars (scalar work per bar). The controlled return at bar ``t`` is
approximated as ``scale[t - lag] * r[t]`` where ``r`` is the zero-cost return of the incoming
targets; the decision at ``t`` only uses returns up to ``t``.
"""

from __future__ import annotations

import numpy as np
from pydantic import BaseModel, Field

from backbone.core.interfaces import Overlay, OverlayContext
from backbone.core.params import OverlayParams
from backbone.core.registry import register
from backbone.core.types import FloatArray, TargetFrame


class DrawdownLevel(BaseModel):
    """Scale applied once the drawdown is at least ``drawdown``."""

    drawdown: float = Field(gt=0, lt=1, description="Drawdown threshold (e.g. 0.1 = 10%)")
    scale: float = Field(ge=0, le=1, description="Exposure scale at or beyond the threshold")


class DerisksParams(OverlayParams):
    """Drawdown de-risking schedule."""

    levels: list[DrawdownLevel] = Field(
        default_factory=lambda: [
            DrawdownLevel(drawdown=0.10, scale=0.5),
            DrawdownLevel(drawdown=0.20, scale=0.25),
        ],
        description="Thresholds and the exposure scale applied beyond each",
    )


def _effective(scale: FloatArray, t: int, lag: int) -> float:
    return float(scale[t - lag]) if t - lag >= 0 else 1.0


@register("overlay", name="drawdown_derisk", version="1.0.0", tags=["drawdown"])
class DrawdownDerisk(Overlay):
    """Reduce exposure step-wise as the controlled strategy's drawdown deepens."""

    Params = DerisksParams
    params: DerisksParams

    def apply(self, targets: TargetFrame, ctx: OverlayContext) -> TargetFrame:
        """Iterate over bars applying the schedule."""
        r = np.nan_to_num(ctx.simulate(targets))
        levels = sorted(self.params.levels, key=lambda lv: lv.drawdown)
        scale = np.ones(len(r))
        equity = peak = 1.0
        for t in range(len(r)):
            equity *= 1.0 + _effective(scale, t, ctx.lag_bars) * r[t]
            peak = max(peak, equity)
            dd = 1.0 - equity / peak
            s = 1.0
            for lv in levels:
                if dd >= lv.drawdown:
                    s = lv.scale
            scale[t] = s
        ctx.notes.append(f"de-risked on {int((scale < 1).sum())} bars")
        return targets.replace(values=targets.values * scale[:, None])


class BreakerParams(OverlayParams):
    """Circuit breaker parameters."""

    threshold: float = Field(0.15, gt=0, lt=1, description="Drawdown that trips the breaker")
    cooloff_bars: int = Field(21, ge=1, le=2520, description="Bars flat after tripping")


@register("overlay", name="circuit_breaker", version="1.0.0", tags=["drawdown"])
class CircuitBreaker(Overlay):
    """Go flat when drawdown exceeds a threshold, stay flat for a cool-off, then restart."""

    Params = BreakerParams
    params: BreakerParams

    def apply(self, targets: TargetFrame, ctx: OverlayContext) -> TargetFrame:
        """Iterate over bars; the peak resets after each cool-off."""
        p = self.params
        r = np.nan_to_num(ctx.simulate(targets))
        scale = np.ones(len(r))
        equity = peak = 1.0
        flat_until = -1
        trips = 0
        for t in range(len(r)):
            equity *= 1.0 + _effective(scale, t, ctx.lag_bars) * r[t]
            if t <= flat_until:
                scale[t] = 0.0
                peak = equity
                continue
            peak = max(peak, equity)
            if 1.0 - equity / peak >= p.threshold:
                trips += 1
                flat_until = t + p.cooloff_bars - 1
                scale[t] = 0.0
        ctx.notes.append(f"breaker tripped {trips} times")
        return targets.replace(values=targets.values * scale[:, None])


class CppiParams(OverlayParams):
    """CPPI parameters."""

    floor: float = Field(0.8, gt=0, lt=1, description="Floor as a fraction of the peak")
    multiplier: float = Field(4.0, gt=0, le=20, description="Cushion multiplier")
    max_exposure: float = Field(1.0, gt=0, le=5, description="Maximum exposure scale")
    ratchet: bool = Field(True, description="Floor follows the running peak")


@register("overlay", name="cppi", version="1.0.0", tags=["drawdown", "insurance"])
class Cppi(Overlay):
    """Constant proportion portfolio insurance: exposure = multiplier x cushion over a floor."""

    Params = CppiParams
    params: CppiParams

    def apply(self, targets: TargetFrame, ctx: OverlayContext) -> TargetFrame:
        """Iterate over bars computing the cushion."""
        p = self.params
        r = np.nan_to_num(ctx.simulate(targets))
        scale = np.ones(len(r))
        equity = peak = 1.0
        for t in range(len(r)):
            equity *= 1.0 + _effective(scale, t, ctx.lag_bars) * r[t]
            peak = max(peak, equity) if p.ratchet else 1.0
            floor = p.floor * peak
            cushion = max(equity - floor, 0.0) / equity if equity > 0 else 0.0
            scale[t] = min(p.multiplier * cushion, p.max_exposure)
        ctx.notes.append(f"average exposure scale {float(scale.mean()):.2f}")
        return targets.replace(values=targets.values * scale[:, None])
