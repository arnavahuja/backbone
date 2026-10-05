"""Continuous futures construction with pluggable roll rules and back-adjustment.

Input: individual contracts in canonical long form (``instrument_id`` = contract id) with
instrument metadata (``root``, ``expiry``) and optionally ``volume`` / ``open_interest``.
Output: one continuous series per root plus the roll schedule. Individual contracts stay in
the cache for strategies that trade them directly in the event engine.

Roll rules decide, for each date, which contract is "active" using only information up to
that date. Back-adjustment (``ratio`` or ``difference``) removes roll gaps from the price
history; ``ratio`` keeps prices positive and returns exact, ``difference`` keeps point values.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Final

import numpy as np
import polars as pl

from backbone.core import columns as C
from backbone.core.errors import DataError
from backbone.core.types import (
    AssetClass,
    FloatArray,
    Instrument,
    IntArray,
    MarketData,
    TimeArray,
    pl_times,
)

ROLL_FIELD: Final = "roll"
ACTIVE_FIELD: Final = "active_contract"
OPEN_INTEREST: Final = "open_interest"


class BackAdjust(StrEnum):
    """Back-adjustment method."""

    RATIO = "ratio"
    DIFFERENCE = "difference"
    NONE = "none"


RollRule = Callable[["ContractPanel", int], IntArray]
"""``(panel, days_before_expiry) -> active contract column per date``."""


@dataclass(frozen=True)
class ContractPanel:
    """Contracts of one root aligned on a date grid (columns sorted by expiry)."""

    timestamps: TimeArray
    contracts: tuple[str, ...]
    expiries: tuple[date, ...]
    close: FloatArray
    open: FloatArray
    high: FloatArray
    low: FloatArray
    volume: FloatArray
    open_interest: FloatArray


def _front_by_expiry(panel: ContractPanel, days_before: int) -> IntArray:
    """First contract whose expiry is more than ``days_before`` days after the date."""
    dates = panel.timestamps.astype("datetime64[D]")
    exp = np.array(panel.expiries, dtype="datetime64[D]")
    cutoff = exp[None, :] - np.timedelta64(days_before, "D")
    eligible = (dates[:, None] < cutoff) & np.isfinite(panel.close)
    first = np.argmax(eligible, axis=1)
    return np.where(eligible.any(axis=1), first, len(panel.contracts) - 1)


def roll_fixed_days(panel: ContractPanel, days_before: int) -> IntArray:
    """Roll a fixed number of calendar days before expiry."""
    return _front_by_expiry(panel, days_before)


def _roll_by_liquidity(panel: ContractPanel, days_before: int, field: FloatArray) -> IntArray:
    """Move to the next contract once its liquidity exceeds the current one (never back)."""
    base = _front_by_expiry(panel, days_before)
    n_t = len(base)
    active = base.copy()
    liq = np.nan_to_num(field, nan=-1.0)
    rows = np.arange(n_t)
    nxt = np.minimum(base + 1, len(panel.contracts) - 1)
    switch = liq[rows, nxt] > liq[rows, base]
    active = np.where(switch, nxt, base)
    # never roll backwards (a later contract once chosen stays until it expires)
    return np.maximum.accumulate(active)


def roll_volume(panel: ContractPanel, days_before: int) -> IntArray:
    """Roll when the next contract's volume exceeds the front's (expiry is a hard stop)."""
    return _roll_by_liquidity(panel, days_before, panel.volume)


def roll_open_interest(panel: ContractPanel, days_before: int) -> IntArray:
    """Roll when the next contract's open interest exceeds the front's."""
    return _roll_by_liquidity(panel, days_before, panel.open_interest)


ROLL_RULES: Final[dict[str, RollRule]] = {
    "fixed_days": roll_fixed_days,
    "volume": roll_volume,
    "open_interest": roll_open_interest,
}
"""Roll rules by name. Add an entry here (or pass a callable) to plug in a new rule."""


def contract_panel(data: MarketData, root: str) -> ContractPanel:
    """Align the contracts of ``root`` on the common date grid, sorted by expiry."""
    meta = data.instrument_meta
    ids = [i for i in data.instruments if meta.get(i) and meta[i].root == root]
    if not ids:
        raise DataError(f"No contracts for root '{root}' (instrument metadata needs root/expiry)")
    ids.sort(key=lambda i: meta[i].expiry or date.max)
    sub = data.select_instruments(ids)
    cols = [sub.instruments.index(i) for i in ids]

    def field(name: str) -> FloatArray:
        if not sub.has_field(name):
            return np.full((len(sub.timestamps), len(ids)), np.nan)
        return sub.panel(name)[:, cols]

    close = field(C.CLOSE)
    return ContractPanel(
        timestamps=sub.timestamps,
        contracts=tuple(ids),
        expiries=tuple(meta[i].expiry or date.max for i in ids),
        close=close,
        open=np.where(np.isfinite(field(C.OPEN)), field(C.OPEN), close),
        high=np.where(np.isfinite(field(C.HIGH)), field(C.HIGH), close),
        low=np.where(np.isfinite(field(C.LOW)), field(C.LOW), close),
        volume=field(C.VOLUME),
        open_interest=field(OPEN_INTEREST),
    )


def build_continuous(
    data: MarketData,
    root: str,
    rule: str | RollRule = "open_interest",
    days_before_expiry: int = 5,
    adjust: BackAdjust = BackAdjust.RATIO,
) -> MarketData:
    """Continuous series for ``root``.

    Returns a single-instrument MarketData (``instrument_id = root``) with OHLCV, ``roll``
    (1.0 on the bar where the active contract changes) and ``active_contract``.
    """
    panel = contract_panel(data, root)
    roll_fn = ROLL_RULES[rule] if isinstance(rule, str) else rule
    active = roll_fn(panel, days_before_expiry)
    rows = np.arange(len(active))
    rolls = np.zeros(len(active), dtype=bool)
    rolls[1:] = active[1:] != active[:-1]

    def pick(arr: FloatArray) -> FloatArray:
        return arr[rows, active]

    close, open_, high, low = (
        pick(panel.close),
        pick(panel.open),
        pick(panel.high),
        pick(panel.low),
    )
    # On a roll bar the holder earns the old contract's return, then switches. Rescale history
    # before the roll by new/old (ratio) or shift it by new - old (difference).
    old_close = panel.close[rows, np.concatenate(([active[0]], active[:-1]))]
    if adjust is BackAdjust.RATIO:
        with np.errstate(divide="ignore", invalid="ignore"):
            step = np.where(rolls & np.isfinite(old_close), close / old_close, 1.0)
        step = np.where(np.isfinite(step) & (step > 0), step, 1.0)
        # factor for bar t = product of steps at rolls strictly after t
        factor = np.concatenate((np.cumprod(step[::-1])[::-1][1:], [1.0]))
        close, open_, high, low = (x * factor for x in (close, open_, high, low))
    elif adjust is BackAdjust.DIFFERENCE:
        step = np.where(rolls & np.isfinite(old_close), close - old_close, 0.0)
        offset = np.concatenate((np.cumsum(step[::-1])[::-1][1:], [0.0]))
        close, open_, high, low = (x + offset for x in (close, open_, high, low))
    frame = pl.DataFrame(
        {
            C.TIMESTAMP: pl_times(panel.timestamps),
            C.INSTRUMENT: [root] * len(rows),
            C.OPEN: open_,
            C.HIGH: high,
            C.LOW: low,
            C.CLOSE: close,
            C.VOLUME: pick(panel.volume),
            ROLL_FIELD: rolls.astype(np.float64),
            ACTIVE_FIELD: [panel.contracts[k] for k in active],
        }
    ).filter(pl.col(C.CLOSE).is_not_nan() & pl.col(C.CLOSE).is_not_null())
    first = data.instrument_meta[panel.contracts[0]]
    inst = Instrument(
        id=root,
        symbol=root,
        asset_class=AssetClass.FUTURE,
        multiplier=first.multiplier,
        currency=first.currency,
        exchange=first.exchange,
        root=root,
    )
    return MarketData(
        frame,
        data.frequency,
        {root: inst},
        metadata={
            **data.metadata,
            "continuous": True,
            "roll_rule": rule if isinstance(rule, str) else getattr(rule, "__name__", "custom"),
            "back_adjust": adjust.value,
        },
    )


def continuous_many(
    data: MarketData, rule: str, days_before: int, adjust: BackAdjust
) -> MarketData:
    """Continuous series for every root present in the instrument metadata."""
    roots = sorted({m.root for m in data.instrument_meta.values() if m.root})
    if not roots:
        raise DataError("No futures roots in the instrument metadata")
    out: MarketData | None = None
    meta: dict[str, Instrument] = {}
    for root in roots:
        series = build_continuous(data, root, rule, days_before, adjust)
        meta.update(series.instrument_meta)
        out = series if out is None else out.concat(series)
    assert out is not None
    return MarketData(out.frame, out.frequency, meta, out.metadata)
