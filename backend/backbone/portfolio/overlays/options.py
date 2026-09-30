"""Option hedging overlays: protective put, collar, put spread, tail hedge, covered calls.

Each overlay adds rolling option instruments (model-priced from volatility when no chain is
configured; flagged ``model_priced``) and allocates weight to them. Option weights are set
at roll bars and held (they drift with the option's value) until the next roll.
"""

from __future__ import annotations

from typing import Any, ClassVar

import numpy as np
from pydantic import Field

from backbone.core import columns as C
from backbone.core.errors import ConfigError
from backbone.core.interfaces import NEEDS_BENCHMARK, Overlay, OverlayContext
from backbone.core.options_math import (
    OptionLeg,
    RollingOption,
    build_option_data,
    option_instrument_id,
)
from backbone.core.params import OverlayParams
from backbone.core.registry import register
from backbone.core.types import FloatArray, MarketData, OptionRight, TargetFrame

OPTION_CAPS = frozenset({"engine:vectorized", "asset:option"})


class OptionOverlayParams(OverlayParams):
    """Common parameters."""

    underlying: str = Field("", description="Instrument to hedge with (default: benchmark)")
    tenor_days: int = Field(30, ge=5, le=730, description="Option tenor (calendar days)")
    roll_every: int = Field(21, ge=1, le=252, description="Roll every N bars")
    hedge_ratio: float = Field(1.0, ge=0, le=3, description="Option notional / long exposure")
    vol_premium: float = Field(1.1, ge=0.5, le=3, description="Implied / realized vol ratio")
    rate: float = Field(0.02, ge=-0.05, le=0.3, description="Risk-free rate for pricing")


class _OptionOverlay(Overlay):
    """Base: legs on one underlying sized to the portfolio's long exposure."""

    Params = OptionOverlayParams
    params: OptionOverlayParams
    capabilities: ClassVar[frozenset[str]] = OPTION_CAPS | {NEEDS_BENCHMARK}

    def legs(self) -> list[OptionLeg]:
        """Option legs of the structure."""
        raise NotImplementedError

    def _underlying(self, data: MarketData, benchmark: str | None) -> str:
        und = self.params.underlying or benchmark or ""
        if und not in data.instruments:
            raise ConfigError(
                f"Option underlying '{und}' is not in the data; set 'underlying' "
                "or a benchmark that is part of the data"
            )
        return und

    def synthetic_instruments(self, data: MarketData, chain: Any) -> MarketData | None:
        """Rolling option instruments for the legs."""
        benchmark = data.metadata.get("benchmark_id")
        und = self.params.underlying or (str(benchmark) if benchmark else "")
        if not und:
            und = data.instruments[0] if data.instruments else ""
        specs = [leg.spec for leg in self.legs()]
        built: MarketData | None = build_option_data(
            data, [und], specs, self.params.vol_premium, self.params.rate, chain
        )
        return built

    def notional(self, targets: TargetFrame, option_ids: set[str]) -> FloatArray:
        """Long exposure of the non-option positions (per decision bar)."""
        cols = [j for j, i in enumerate(targets.instruments) if i not in option_ids]
        return np.clip(targets.filled()[:, cols], 0, None).sum(axis=1)

    def apply(self, targets: TargetFrame, ctx: OverlayContext) -> TargetFrame:
        """Set option weights at each roll and hold them until the next."""
        und = self._underlying(ctx.data, ctx.benchmark)
        legs = self.legs()
        ids = [option_instrument_id(und, leg.spec) for leg in legs]
        missing = [i for i in ids if i not in targets.instruments]
        if missing:
            raise ConfigError(
                "Option instruments were not added to the data", details={"missing": missing}
            )
        w = targets.filled()
        notional = self.notional(targets, set(ids)) * self.params.hedge_ratio
        spot = ctx.data.aligned_panel(C.CLOSE, targets.timestamps, (und,))[:, 0]
        spent = 0.0
        for leg, inst in zip(legs, ids, strict=True):
            j = targets.instruments.index(inst)
            price = ctx.data.aligned_panel(C.CLOSE, targets.timestamps, (inst,))[:, 0]
            roll = ctx.data.aligned_panel("roll", targets.timestamps, (inst,))[:, 0] > 0
            with np.errstate(divide="ignore", invalid="ignore"):
                value_per_notional = np.nan_to_num(price / spot)
            at_roll = np.where(roll, leg.sign * leg.ratio * notional * value_per_notional, np.nan)
            w[:, j] = np.nan_to_num(_hold(at_roll))
            spent += float(np.nansum(np.where(roll & (leg.sign > 0), at_roll, 0.0)))
        ctx.notes.append(
            f"legs: {', '.join(ids)}; premium bought (sum of roll weights) {spent:.2%}"
        )
        return targets.replace(values=w)


def _hold(values: FloatArray) -> FloatArray:
    """Forward-fill values set at roll bars."""
    idx = np.where(np.isfinite(values), np.arange(len(values)), 0)
    np.maximum.accumulate(idx, out=idx)
    out = values[idx]
    out[: np.argmax(np.isfinite(values)) if np.isfinite(values).any() else len(values)] = np.nan
    return out


class ProtectivePutParams(OptionOverlayParams):
    """Protective put parameters."""

    moneyness: float = Field(0.95, gt=0.3, le=1.2, description="Put strike / spot")


@register("overlay", name="protective_put", version="1.0.0", tags=["options", "hedging"])
class ProtectivePut(_OptionOverlay):
    """Buy puts on the underlying covering the portfolio's long exposure, rolled regularly."""

    Params = ProtectivePutParams
    params: ProtectivePutParams

    def legs(self) -> list[OptionLeg]:
        """One long put."""
        p = self.params
        return [
            OptionLeg(RollingOption(OptionRight.PUT, p.moneyness, p.tenor_days, p.roll_every), 1.0)
        ]


class CollarParams(OptionOverlayParams):
    """Collar parameters."""

    put_moneyness: float = Field(0.90, gt=0.3, le=1.2, description="Long put strike / spot")
    call_moneyness: float = Field(1.10, gt=0.8, le=2.0, description="Short call strike / spot")


@register("overlay", name="collar", version="1.0.0", tags=["options", "hedging"])
class Collar(_OptionOverlay):
    """Long put financed by a short call on the same notional."""

    Params = CollarParams
    params: CollarParams

    def legs(self) -> list[OptionLeg]:
        """Long put, short call."""
        p = self.params
        return [
            OptionLeg(
                RollingOption(OptionRight.PUT, p.put_moneyness, p.tenor_days, p.roll_every), 1.0
            ),
            OptionLeg(
                RollingOption(OptionRight.CALL, p.call_moneyness, p.tenor_days, p.roll_every), -1.0
            ),
        ]


class PutSpreadParams(OptionOverlayParams):
    """Put spread parameters."""

    long_moneyness: float = Field(0.95, gt=0.3, le=1.2, description="Long put strike / spot")
    short_moneyness: float = Field(0.85, gt=0.3, le=1.2, description="Short put strike / spot")


@register("overlay", name="put_spread", version="1.0.0", tags=["options", "hedging"])
class PutSpread(_OptionOverlay):
    """Long a higher-strike put, short a lower-strike put (cheaper, capped protection)."""

    Params = PutSpreadParams
    params: PutSpreadParams

    def legs(self) -> list[OptionLeg]:
        """Long put, short further OTM put."""
        p = self.params
        return [
            OptionLeg(
                RollingOption(OptionRight.PUT, p.long_moneyness, p.tenor_days, p.roll_every), 1.0
            ),
            OptionLeg(
                RollingOption(OptionRight.PUT, p.short_moneyness, p.tenor_days, p.roll_every), -1.0
            ),
        ]


class TailHedgeParams(OptionOverlayParams):
    """Tail hedge parameters."""

    moneyness: float = Field(0.80, gt=0.3, le=1.0, description="Deep OTM put strike / spot")
    annual_budget: float = Field(0.01, gt=0, le=0.2, description="Premium per year / equity")
    tenor_days: int = Field(60, ge=5, le=730, description="Option tenor (calendar days)")


@register("overlay", name="tail_hedge", version="1.0.0", tags=["options", "hedging", "tail"])
class TailHedge(_OptionOverlay):
    """Spend a fixed premium budget per year on deep out-of-the-money puts."""

    Params = TailHedgeParams
    params: TailHedgeParams

    def legs(self) -> list[OptionLeg]:
        """One deep OTM put."""
        p = self.params
        return [
            OptionLeg(RollingOption(OptionRight.PUT, p.moneyness, p.tenor_days, p.roll_every), 1.0)
        ]

    def apply(self, targets: TargetFrame, ctx: OverlayContext) -> TargetFrame:
        """Weight at each roll = budget per roll period (the premium itself)."""
        und = self._underlying(ctx.data, ctx.benchmark)
        spec = self.legs()[0].spec
        inst = option_instrument_id(und, spec)
        if inst not in targets.instruments:
            raise ConfigError("Tail hedge instrument missing from the data")
        roll = ctx.data.aligned_panel("roll", targets.timestamps, (inst,))[:, 0] > 0
        per_roll = self.params.annual_budget * self.params.roll_every / ctx.periods_per_year
        w = targets.filled()
        w[:, targets.instruments.index(inst)] = np.nan_to_num(
            _hold(np.where(roll, per_roll, np.nan))
        )
        ctx.notes.append(f"premium per roll {per_roll:.3%} of equity")
        return targets.replace(values=w)


class CoveredCallParams(OptionOverlayParams):
    """Covered call overwrite parameters."""

    moneyness: float = Field(1.05, gt=0.8, le=2.0, description="Short call strike / spot")


@register("overlay", name="covered_call_overwrite", version="1.0.0", tags=["options", "income"])
class CoveredCallOverwrite(_OptionOverlay):
    """Sell calls on the underlying against the portfolio's long exposure (income)."""

    Params = CoveredCallParams
    params: CoveredCallParams

    def legs(self) -> list[OptionLeg]:
        """One short call."""
        p = self.params
        return [
            OptionLeg(
                RollingOption(OptionRight.CALL, p.moneyness, p.tenor_days, p.roll_every), -1.0
            )
        ]
