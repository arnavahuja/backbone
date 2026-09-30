"""Synthetic futures chains and intraday bars (offline demos and tests).

* ``futures_contracts``: quarterly contracts per root with carry, volume/open-interest migration
  before expiry and a contract multiplier.
* ``futures_continuous``: continuous series built with a roll rule and back-adjustment.
* ``gbm_intraday``: intraday OHLCV between 14:30 and 21:00 UTC on exchange sessions.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime, time, timedelta
from typing import ClassVar, Final

import numpy as np
import polars as pl
from pydantic import Field

from backbone.core import columns as C
from backbone.core.calendar import TradingCalendar
from backbone.core.errors import DataError
from backbone.core.interfaces import DataSource
from backbone.core.params import SourceParams
from backbone.core.registry import register
from backbone.core.types import (
    AssetClass,
    DataRequest,
    DatasetInfo,
    Frequency,
    Instrument,
    MarketData,
)
from backbone.data.futures import OPEN_INTEREST, BackAdjust, continuous_many
from backbone.data.normalize import normalize_frame

QUARTER_MONTHS: Final = (3, 6, 9, 12)
MONTH_CODES: Final = {3: "H", 6: "M", 9: "U", 12: "Z"}
EXPIRY_DAY: Final = 15
MIGRATION_DAYS: Final = 10
SESSION_OPEN: Final = time(14, 30)
SESSION_MINUTES: Final = 390
BASE_VOLUME: Final = 100_000.0


def _seed(*parts: object) -> int:
    return int.from_bytes(hashlib.sha256(":".join(map(str, parts)).encode()).digest()[:4],
                          "little")


class SyntheticMarketParams(SourceParams):
    """Parameters of the synthetic markets source."""

    annual_vol: float = Field(0.18, gt=0, le=2, description="Annual volatility")
    annual_carry: float = Field(0.02, ge=-0.2, le=0.2, description="Futures carry (contango)")
    multiplier: float = Field(50.0, gt=0, description="Contract multiplier")


@register("data_source", name="synthetic_markets", version="1.0.0",
          tags=["synthetic", "futures", "intraday", "offline"],
          capabilities={"asset:future", "asset:equity", "freq:daily", "freq:intraday"})
class SyntheticMarkets(DataSource):
    """Deterministic futures chains and intraday bars for demos and tests."""

    Params = SyntheticMarketParams
    params: SyntheticMarketParams
    source_version: ClassVar[str] = "1"

    def describe(self) -> list[DatasetInfo]:
        """Datasets offered."""
        return [
            DatasetInfo(source="synthetic_markets", dataset="futures_contracts",
                        description="Quarterly futures contracts per root (e.g. ES, CL)",
                        frequencies=(Frequency.D1,), asset_classes=(AssetClass.FUTURE,),
                        fields=(*C.OHLCV, OPEN_INTEREST), quality="synthetic"),
            DatasetInfo(source="synthetic_markets", dataset="futures_continuous",
                        description="Continuous futures (options: roll_rule, days_before, "
                                    "adjust)", frequencies=(Frequency.D1,),
                        asset_classes=(AssetClass.FUTURE,), quality="synthetic"),
            DatasetInfo(source="synthetic_markets", dataset="gbm_intraday",
                        description="Intraday OHLCV on exchange sessions",
                        frequencies=(Frequency.MIN5, Frequency.MIN15, Frequency.H1,
                                     Frequency.MIN1),
                        asset_classes=(AssetClass.EQUITY,), quality="synthetic"),
        ]

    def search_instruments(self, query: str) -> list[Instrument]:
        """Any symbol is accepted."""
        sym = query.strip().upper() or "ES"
        return [Instrument(id=sym, symbol=sym)]

    def fetch(self, request: DataRequest) -> MarketData:
        """Dispatch on dataset."""
        if not request.instruments:
            raise DataError("Give root symbols or tickers")
        if request.dataset == "futures_contracts":
            return self._contracts(request)
        if request.dataset == "futures_continuous":
            opts = request.options
            return continuous_many(
                self._contracts(request), str(opts.get("roll_rule", "open_interest")),
                int(opts.get("days_before", 5)), BackAdjust(opts.get("adjust", "ratio")),
            )
        if request.dataset == "gbm_intraday":
            return self._intraday(request)
        raise DataError(f"Unknown dataset '{request.dataset}'")

    # ---- futures

    def _contracts(self, request: DataRequest) -> MarketData:
        p = self.params
        sessions = TradingCalendar().sessions(request.start, request.end)
        if not sessions:
            raise DataError("No sessions in range")
        days = np.array(sessions, dtype="datetime64[D]")
        dt = 1.0 / TradingCalendar().sessions_per_year()
        frames = []
        meta: dict[str, Instrument] = {}
        for root in request.instruments:
            rng = np.random.default_rng(_seed(root, request.options.get("seed", 7)))
            spot = 100.0 * np.exp(np.cumsum(p.annual_vol * np.sqrt(dt)
                                            * rng.standard_normal(len(days))))
            expiries = _quarterly_expiries(sessions[0], sessions[-1] + timedelta(days=200))
            for exp in expiries:
                cid = f"{root}{MONTH_CODES[exp.month]}{exp.year % 100:02d}"
                alive = (days <= np.datetime64(exp)) & (
                    days > np.datetime64(exp - timedelta(days=270)))
                if not alive.any():
                    continue
                tau = (np.datetime64(exp) - days).astype(float) / 365.0
                price = spot * np.exp(p.annual_carry * tau)
                to_exp = (np.datetime64(exp) - days).astype(int)
                liquidity = np.clip((to_exp - MIGRATION_DAYS) / 60.0, 0.05, 1.0)
                liquidity = np.where(to_exp > 100, 0.3, liquidity)  # noqa: PLR2004
                noise = rng.lognormal(0, 0.2, len(days))
                frames.append(pl.DataFrame({
                    C.TIMESTAMP: [datetime.combine(d.astype(date), time(0), tzinfo=UTC)
                                  for d in days[alive]],
                    C.INSTRUMENT: cid,
                    C.OPEN: price[alive] * (1 + rng.normal(0, 0.002, alive.sum())),
                    C.HIGH: price[alive] * 1.006, C.LOW: price[alive] * 0.994,
                    C.CLOSE: price[alive],
                    C.VOLUME: (BASE_VOLUME * liquidity * noise)[alive],
                    OPEN_INTEREST: (5 * BASE_VOLUME * liquidity)[alive],
                }))
                meta[cid] = Instrument(id=cid, symbol=cid, asset_class=AssetClass.FUTURE,
                                       multiplier=p.multiplier, expiry=exp, root=root,
                                       underlying=root)
        frame = normalize_frame(pl.concat(frames))
        return MarketData(frame, Frequency.D1, meta, metadata={
            "source": "synthetic_markets", "adjustment": "raw", "quality": "synthetic"})

    # ---- intraday

    def _intraday(self, request: DataRequest) -> MarketData:
        minutes = request.frequency.minutes
        if minutes is None:
            raise DataError("gbm_intraday needs an intraday frequency")
        sessions = TradingCalendar().sessions(request.start, request.end)
        per_day = SESSION_MINUTES // minutes
        n = len(sessions) * per_day
        stamps = [datetime.combine(s, SESSION_OPEN, tzinfo=UTC) + timedelta(minutes=k * minutes)
                  for s in sessions for k in range(per_day)]
        step = self.params.annual_vol * np.sqrt(
            minutes / (SESSION_MINUTES * TradingCalendar().sessions_per_year()))
        frames = []
        for inst in request.instruments:
            rng = np.random.default_rng(_seed(inst, "intraday", request.options.get("seed", 7)))
            # a little intraday mean reversion around a slow trend
            shocks = rng.standard_normal(n) * step
            close = 50.0 * np.exp(np.cumsum(shocks - 0.3 * np.concatenate(([0], shocks[:-1]))))
            open_ = np.concatenate(([close[0]], close[:-1]))
            spread = np.abs(rng.normal(0, step, n)) * close
            frames.append(pl.DataFrame({
                C.TIMESTAMP: stamps, C.INSTRUMENT: inst, C.OPEN: open_,
                C.HIGH: np.maximum(open_, close) + spread,
                C.LOW: np.minimum(open_, close) - spread, C.CLOSE: close,
                C.VOLUME: rng.lognormal(10, 0.3, n),
            }))
        return MarketData(normalize_frame(pl.concat(frames)), request.frequency,
                          {i: Instrument(id=i, symbol=i) for i in request.instruments},
                          metadata={"source": "synthetic_markets", "quality": "synthetic"})


def _quarterly_expiries(start: date, end: date) -> list[date]:
    out = []
    for year in range(start.year, end.year + 1):
        for month in QUARTER_MONTHS:
            d = date(year, month, EXPIRY_DAY)
            if start <= d <= end + timedelta(days=100):
                out.append(d)
    return out
