"""Regime filters: benchmark trend, volatility regime, user-supplied regime series."""

from __future__ import annotations

import warnings

import numpy as np
from pydantic import Field

from backbone.core import columns as C
from backbone.core.errors import ConfigError
from backbone.core.interfaces import Overlay, OverlayContext
from backbone.core.numeric import rolling_mean, rolling_std
from backbone.core.params import OverlayParams
from backbone.core.portfolio_math import simple_returns
from backbone.core.registry import register
from backbone.core.types import FloatArray, TargetFrame


def reference_series(
    targets: TargetFrame, ctx: OverlayContext, instrument: str, field: str = C.CLOSE
) -> FloatArray:
    """A field of the regime instrument (param or benchmark) on the targets' timestamps."""
    ref = instrument or ctx.benchmark
    if not ref:
        raise ConfigError("Regime filter needs an instrument or a benchmark")
    if ref not in ctx.data.instruments:
        raise ConfigError(f"Regime instrument '{ref}' is not in the data")
    if not ctx.data.has_field(field):
        raise ConfigError(f"Field '{field}' is not in the data")
    return ctx.data.aligned_panel(field, targets.timestamps, (ref,))[:, 0]


class TrendParams(OverlayParams):
    """Trend filter parameters."""

    instrument: str = Field("", description="Instrument to test (default: benchmark)")
    window: int = Field(200, ge=5, le=1260, description="Moving average window (bars)")
    risk_off_scale: float = Field(0.0, ge=0, le=1, description="Exposure when below trend")


@register("overlay", name="trend_filter", version="1.0.0", tags=["regime"])
class TrendFilter(Overlay):
    """Cut exposure when the reference instrument trades below its moving average."""

    Params = TrendParams
    params: TrendParams

    def apply(self, targets: TargetFrame, ctx: OverlayContext) -> TargetFrame:
        """Scale rows in the risk-off regime."""
        p = self.params
        price = reference_series(targets, ctx, p.instrument)
        sma = rolling_mean(price, p.window)
        risk_off = np.isfinite(sma) & (price < sma)
        ctx.notes.append(f"risk-off {float(risk_off.mean()):.0%} of bars")
        scale = np.where(risk_off, p.risk_off_scale, 1.0)
        return targets.replace(values=targets.values * scale[:, None])


class VolRegimeParams(OverlayParams):
    """Volatility regime parameters."""

    instrument: str = Field("", description="Instrument to test (default: benchmark)")
    window: int = Field(21, ge=5, le=252, description="Realized vol window (bars)")
    lookback: int = Field(252, ge=21, le=2520, description="History for the percentile (bars)")
    percentile: float = Field(0.8, gt=0, lt=1, description="High-vol threshold percentile")
    risk_off_scale: float = Field(0.5, ge=0, le=1, description="Exposure in the high-vol regime")


@register("overlay", name="vol_regime_filter", version="1.0.0", tags=["regime"])
class VolRegimeFilter(Overlay):
    """Cut exposure when current volatility is above its trailing percentile."""

    Params = VolRegimeParams
    params: VolRegimeParams

    def apply(self, targets: TargetFrame, ctx: OverlayContext) -> TargetFrame:
        """Compare vol with its trailing distribution (rows <= t only)."""
        p = self.params
        vol = rolling_std(
            simple_returns(reference_series(targets, ctx, p.instrument)[:, None]), p.window
        )[:, 0]
        n = len(vol)
        view = np.lib.stride_tricks.sliding_window_view(
            np.concatenate([np.full(p.lookback - 1, np.nan), vol]), p.lookback
        )[:n]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)  # warm-up rows are all NaN
            threshold = np.nanquantile(
                np.where(np.isfinite(view), view, np.nan), p.percentile, axis=1
            )
        high = np.isfinite(vol) & np.isfinite(threshold) & (vol > threshold)
        ctx.notes.append(f"high-vol regime {float(high.mean()):.0%} of bars")
        scale = np.where(high, p.risk_off_scale, 1.0)
        return targets.replace(values=targets.values * scale[:, None])


class UserRegimeParams(OverlayParams):
    """User regime parameters."""

    field: str = Field("regime", description="Data field with the regime series")
    instrument: str = Field("", description="Instrument carrying the field (default: benchmark)")
    risk_off_scale: float = Field(0.0, ge=0, le=1, description="Exposure when regime <= 0")


@register("overlay", name="user_regime", version="1.0.0", tags=["regime"])
class UserRegime(Overlay):
    """Scale exposure using a user-supplied regime series (value <= 0 means risk-off)."""

    Params = UserRegimeParams
    params: UserRegimeParams

    def apply(self, targets: TargetFrame, ctx: OverlayContext) -> TargetFrame:
        """Scale rows where the regime series is non-positive."""
        p = self.params
        regime = reference_series(targets, ctx, p.instrument, p.field)
        risk_off = np.isfinite(regime) & (regime <= 0)
        scale = np.where(risk_off, p.risk_off_scale, 1.0)
        return targets.replace(values=targets.values * scale[:, None])
