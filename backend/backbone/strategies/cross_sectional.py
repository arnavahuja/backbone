"""Generic cross-sectional signals: trailing returns, any data field, and z-score composites.

All three emit signals (higher = more attractive). Pair them with ``quantile_long_short`` to
form decile long-short portfolios.
"""

from __future__ import annotations

from typing import Any, ClassVar, Final, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from backbone.core import columns as C
from backbone.core.errors import ConfigError, DataError
from backbone.core.interfaces import (
    ASSET_EQUITY,
    ENGINE_EVENT,
    ENGINE_VECTORIZED,
    FREQ_DAILY,
    NEEDS_MULTI_ASSET,
    SUPPORTS_SHORT,
    DataRequirements,
    Strategy,
)
from backbone.core.numeric import shift
from backbone.core.params import StrategyParams
from backbone.core.registry import PluginKind, register, registry
from backbone.core.types import FloatArray, MarketData, TargetFrame, TargetKind
from backbone.strategies.factor_portfolio import zscore_rows

CROSS_SECTIONAL_CAPS: Final = frozenset(
    {ENGINE_VECTORIZED, ENGINE_EVENT, ASSET_EQUITY, FREQ_DAILY, SUPPORTS_SHORT, NEEDS_MULTI_ASSET}
)
Direction = Literal["high", "low"]


def winsorize_rows(x: FloatArray, pct: float) -> FloatArray:
    """Clip each row at its ``pct`` and ``1 - pct`` quantiles (NaN-aware)."""
    if pct <= 0:
        return x
    finite = np.isfinite(x)
    lo = np.full((x.shape[0], 1), np.nan)
    hi = np.full((x.shape[0], 1), np.nan)
    rows = finite.any(axis=1)
    if rows.any():
        sub = np.where(finite[rows], x[rows], np.nan)
        lo[rows, 0] = np.nanquantile(sub, pct, axis=1)
        hi[rows, 0] = np.nanquantile(sub, 1.0 - pct, axis=1)
    return np.where(finite, np.clip(x, lo, hi), np.nan)


def period_returns(data: MarketData) -> FloatArray:
    """Per-bar total returns: the ``ret`` field where present, else close-to-close."""
    close = data.panel(C.CLOSE)
    with np.errstate(divide="ignore", invalid="ignore"):
        price_ret = close / shift(close, 1) - 1.0
    if not data.has_field(C.RETURN):
        return price_ret
    ret = data.panel(C.RETURN)
    return np.where(np.isfinite(ret), ret, price_ret)


def trailing_return(data: MarketData, lookback: int, skip: int) -> FloatArray:
    """Compounded return over ``lookback`` bars ending ``skip`` bars before each bar.

    The window for bar ``t`` is ``[t - skip - lookback + 1, t - skip]``; every bar in it must
    have a return, otherwise the value is NaN.
    """
    r = period_returns(data)
    ok = np.isfinite(r) & (r > -1)
    with np.errstate(invalid="ignore", divide="ignore"):
        growth = np.where(ok, np.log1p(np.where(ok, r, 0.0)), 0.0)
    n_t, n_i = r.shape
    prefix = np.vstack([np.zeros((1, n_i)), np.cumsum(growth, axis=0)])
    counts = np.vstack([np.zeros((1, n_i)), np.cumsum(ok, axis=0)])
    out = np.full((n_t, n_i), np.nan)
    first = skip + lookback - 1
    if first >= n_t:
        return out
    hi = np.arange(first, n_t) - skip + 1
    lo = hi - lookback
    total = prefix[hi] - prefix[lo]
    complete = (counts[hi] - counts[lo]) == lookback
    out[first:] = np.where(complete, np.expm1(total), np.nan)
    return out


def _signed(x: FloatArray, direction: Direction) -> FloatArray:
    return x if direction == "high" else -x


class _CrossSectional(Strategy):
    output_kind: ClassVar[TargetKind] = TargetKind.SIGNALS
    capabilities: ClassVar[frozenset[str]] = CROSS_SECTIONAL_CAPS

    def _frame(self, data: MarketData, score: FloatArray) -> TargetFrame:
        return TargetFrame(data.timestamps, data.instruments, score, TargetKind.SIGNALS)


class TrailingReturnParams(StrategyParams):
    """Trailing-return signal parameters (in bars of the data frequency)."""

    lookback: int = Field(11, ge=1, le=1000, description="Bars in the formation window")
    skip: int = Field(1, ge=0, le=252, description="Most recent bars skipped")
    direction: Direction = Field(
        "high", description="'high' ranks winners first (momentum), 'low' losers (reversal)"
    )


@register(
    "strategy",
    name="trailing_return",
    version="1.0.0",
    tags=["cross-sectional", "momentum", "reversal", "factor"],
)
class TrailingReturn(_CrossSectional):
    """Compounded total return over a window, optionally skipping the latest bars.

    Uses the ``ret`` field when present (dividends and delisting returns included).
    Monthly 12-2 momentum: lookback 11, skip 1. Short-term reversal: lookback 1, skip 0,
    direction low.
    """

    Params = TrailingReturnParams
    params: TrailingReturnParams

    def warmup(self) -> int:
        """Window plus skip."""
        return self.params.lookback + self.params.skip

    def generate_targets(self, data: MarketData) -> TargetFrame:
        """Signed trailing return."""
        p = self.params
        return self._frame(data, _signed(trailing_return(data, p.lookback, p.skip), p.direction))


class FieldSignalParams(StrategyParams):
    """Field-signal parameters."""

    field: str = Field("book_to_market", description="Data field used as the signal")
    direction: Direction = Field("high", description="'high' ranks large values first")
    min_value: float | None = Field(
        None, description="Values at or below this are excluded (e.g. 0 drops negative book)"
    )
    log: bool = Field(False, description="Use log(value) (positive values only)")


@register(
    "strategy",
    name="field_signal",
    version="1.0.0",
    tags=["cross-sectional", "factor", "fundamentals"],
)
class FieldSignal(_CrossSectional):
    """Rank instruments on any point-in-time data field.

    Works with fundamentals joined on their availability date (``extra_datasets``) and with
    the derived ratios ``book_to_market``, ``book_to_market_dec`` (Fama-French timing) and
    ``gross_profitability``.
    """

    Params = FieldSignalParams
    params: FieldSignalParams

    def data_requirements(self) -> DataRequirements:
        """Close plus the signal field."""
        return DataRequirements(fields=(C.CLOSE, self.params.field))

    def generate_targets(self, data: MarketData) -> TargetFrame:
        """The field, filtered and signed."""
        p = self.params
        if not data.has_field(p.field):
            raise DataError(
                f"The data has no '{p.field}' field",
                details={"fields": list(data.fields)},
            )
        x = data.panel(p.field).astype(np.float64)
        if p.min_value is not None:
            x = np.where(x > p.min_value, x, np.nan)
        if p.log:
            with np.errstate(divide="ignore", invalid="ignore"):
                x = np.where(x > 0, np.log(x), np.nan)
        return self._frame(data, _signed(x, p.direction))


class Component(BaseModel):
    """One signal in a composite."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy: str = Field(description="Name of a signal strategy")
    params: dict[str, Any] = Field(default_factory=dict, description="Its parameters")
    weight: float = Field(1.0, ge=0, le=10, description="Weight in the composite")


def _default_components() -> list[Component]:
    return [
        Component(strategy="trailing_return", params={"lookback": 11, "skip": 1}),
        Component(strategy="field_signal", params={"field": "gross_profitability"}),
    ]


class CompositeParams(StrategyParams):
    """Composite parameters."""

    components: list[Component] = Field(
        default_factory=_default_components,
        min_length=1,
        description="Signal strategies combined after z-scoring",
    )
    winsor_pct: float = Field(
        0.01, ge=0, lt=0.5, description="Winsorize each signal at this tail fraction"
    )
    require_all: bool = Field(True, description="Exclude instruments missing any signal")


@register(
    "strategy",
    name="composite_signal",
    version="1.0.0",
    tags=["cross-sectional", "factor", "composite"],
)
class CompositeSignal(_CrossSectional):
    """Weighted average of cross-sectional z-scores of other signal strategies.

    Each component is any registered strategy that emits signals (including user plugins).
    Each signal is winsorized, z-scored per bar, and averaged with the given weights.
    """

    Params = CompositeParams
    params: CompositeParams

    def _children(self) -> list[tuple[float, Strategy]]:
        out = []
        for comp in self.params.components:
            child: Strategy = registry(PluginKind.STRATEGY).get(comp.strategy).create(comp.params)
            if child.output_kind is not TargetKind.SIGNALS:
                raise ConfigError(f"Component '{comp.strategy}' does not emit signals")
            out.append((comp.weight, child))
        return out

    def data_requirements(self) -> DataRequirements:
        """Union of the components' requirements."""
        reqs = [c.data_requirements() for _, c in self._children()]
        fields = tuple(dict.fromkeys(f for r in reqs for f in r.fields))
        return DataRequirements(fields=fields, lookback=max(r.lookback for r in reqs))

    def warmup(self) -> int:
        """Longest component warm-up."""
        return max((c.warmup() for _, c in self._children()), default=0)

    def generate_targets(self, data: MarketData) -> TargetFrame:
        """Weighted mean of winsorized z-scores."""
        p = self.params
        shape = (len(data.timestamps), len(data.instruments))
        total = np.zeros(shape)
        weight = np.zeros(shape)
        complete = np.ones(shape, dtype=bool)
        for w, child in self._children():
            raw = child.generate_targets(data).reindex(data.timestamps, data.instruments).values
            z = zscore_rows(winsorize_rows(raw, p.winsor_pct))
            ok = np.isfinite(z)
            complete &= ok
            if w == 0:
                continue
            total += np.where(ok, w * z, 0.0)
            weight += np.where(ok, w, 0.0)
        with np.errstate(divide="ignore", invalid="ignore"):
            score = np.where(weight > 0, total / weight, np.nan)
        if p.require_all:
            score = np.where(complete, score, np.nan)
        return self._frame(data, score)
