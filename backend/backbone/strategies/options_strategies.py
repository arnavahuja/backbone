"""Option strategies: covered call and protective put on each underlying.

Options are model-priced when no chain is configured.
"""

from __future__ import annotations

from typing import Any, ClassVar

import numpy as np
from pydantic import Field

from backbone.core import columns as C
from backbone.core.interfaces import (
    ASSET_EQUITY,
    ASSET_OPTION,
    ENGINE_EVENT,
    ENGINE_VECTORIZED,
    FREQ_DAILY,
    Strategy,
)
from backbone.core.options_math import RollingOption, build_option_data, option_instrument_id
from backbone.core.params import StrategyParams
from backbone.core.registry import register
from backbone.core.types import MarketData, OptionRight, TargetFrame

CAPS = frozenset({ENGINE_VECTORIZED, ENGINE_EVENT, ASSET_EQUITY, ASSET_OPTION, FREQ_DAILY})


class OptionStrategyParams(StrategyParams):
    """Parameters shared by the option strategies."""

    moneyness: float = Field(1.05, gt=0.3, le=2.0, description="Strike / spot")
    tenor_days: int = Field(30, ge=5, le=730, description="Option tenor (calendar days)")
    roll_every: int = Field(21, ge=1, le=252, description="Roll every N bars")
    vol_premium: float = Field(1.1, ge=0.5, le=3, description="Implied / realized vol ratio")
    rate: float = Field(0.02, ge=-0.05, le=0.3, description="Risk-free rate for pricing")


class _OptionStrategy(Strategy):
    Params = OptionStrategyParams
    params: OptionStrategyParams
    capabilities: ClassVar[frozenset[str]] = CAPS
    right: ClassVar[OptionRight] = OptionRight.CALL
    sign: ClassVar[float] = -1.0

    def spec(self) -> RollingOption:
        """The rolling option leg."""
        p = self.params
        return RollingOption(self.right, p.moneyness, p.tenor_days, p.roll_every)

    def _underlyings(self, data: MarketData) -> list[str]:
        return [
            i
            for i in data.instruments
            if (m := data.instrument_meta.get(i)) is None or m.right is None
        ]

    def synthetic_instruments(self, data: MarketData, chain: Any) -> MarketData | None:
        """One rolling option per underlying."""
        built: MarketData | None = build_option_data(
            data,
            self._underlyings(data),
            [self.spec()],
            self.params.vol_premium,
            self.params.rate,
            chain,
        )
        return built

    def generate_targets(self, data: MarketData) -> TargetFrame:
        """Equal-weight underlyings; option notional equal to each position, set at rolls."""
        unds = self._underlyings(data)
        n = max(len(unds), 1)
        w = np.zeros((len(data.timestamps), len(data.instruments)))
        close = data.panel(C.CLOSE)
        for und in unds:
            j = data.instruments.index(und)
            w[:, j] = np.where(np.isfinite(close[:, j]), 1.0 / n, 0.0)
            inst = option_instrument_id(und, self.spec())
            if inst not in data.instruments:
                continue
            k = data.instruments.index(inst)
            roll = np.nan_to_num(data.panel("roll")[:, k]) > 0
            with np.errstate(divide="ignore", invalid="ignore"):
                at_roll = np.where(roll, self.sign / n * close[:, k] / close[:, j], np.nan)
            idx = np.maximum.accumulate(np.where(np.isfinite(at_roll), np.arange(len(w)), 0))
            w[:, k] = np.nan_to_num(at_roll[idx])
        return TargetFrame(data.timestamps, data.instruments, w)


@register("strategy", name="covered_call", version="1.0.0", tags=["options", "income"])
class CoveredCall(_OptionStrategy):
    """Hold each underlying and sell a rolling out-of-the-money call against it."""


class ProtectivePutParams(OptionStrategyParams):
    """Protective put parameters."""

    moneyness: float = Field(0.95, gt=0.3, le=2.0, description="Put strike / spot")


@register("strategy", name="protective_put_strategy", version="1.0.0", tags=["options", "hedging"])
class ProtectivePutStrategy(_OptionStrategy):
    """Hold each underlying and buy a rolling protective put on it."""

    Params = ProtectivePutParams
    params: ProtectivePutParams
    right: ClassVar[OptionRight] = OptionRight.PUT
    sign: ClassVar[float] = 1.0
